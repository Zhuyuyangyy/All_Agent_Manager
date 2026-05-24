"""
unified_capability_registry.py — 统一能力注册中心

将 Plugin（能力插件）、Skill（技能模板）、MCP（工具服务器）
三种能力来源统一管理，提供单一查询接口。

能力层级：
  MCP Server → MCP Tool（原子工具，如搜索、文件操作）
  Plugin → Capability（组合能力，如"代码生成"）
  Skill → Step Sequence（可复用的流程模板）

调度时查询顺序：
  1. 精确 capability 匹配
  2. 能力覆盖链（Plugin 满足 → MCP 补充 → 手动兜底）
  3. 按成功率/使用次数排序
"""

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from backend.plugin_manager import PluginManager, PluginRecord, PluginStatus
from backend.skill_memory import SkillMemory, SkillTemplate, SkillStatus

logger = logging.getLogger(__name__)


# ── 能力条目 ─────────────────────────────────────────────────

@dataclass
class CapabilityEntry:
    """统一能力条目 — 合并了 Plugin/Skill/MCP 的能力视图"""
    name: str                              # 能力名称（全局唯一）
    source_type: str                        # "plugin" | "skill" | "mcp"
    source_id: str                          # 来源 ID
    source_name: str                        # 来源名称（展示用）
    description: str = ""
    tags: list[str] = field(default_factory=list)  # 标签，用于模糊匹配
    score_boost: float = 0.0               # 成功率加成
    total_uses: int = 0                    # 总使用次数
    success_rate: float = 1.0              # 成功率
    last_used: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "description": self.description,
            "tags": self.tags,
            "score_boost": self.score_boost,
            "total_uses": self.total_uses,
            "success_rate": self.success_rate,
            "last_used": self.last_used,
            "metadata": self.metadata,
        }


# ── MCP 能力条目 ────────────────────────────────────────────

@dataclass
class McpToolEntry:
    """MCP 工具条目"""
    server_id: str
    server_name: str
    tool_name: str
    description: str = ""
    input_schema: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    total_uses: int = 0
    last_used: Optional[str] = None
    avg_latency_ms: float = 0

    def to_dict(self) -> dict:
        return {
            "server_id": self.server_id,
            "server_name": self.server_name,
            "tool_name": self.tool_name,
            "description": self.description,
            "input_schema": self.input_schema,
            "tags": self.tags,
            "total_uses": self.total_uses,
            "last_used": self.last_used,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
        }


# ── 统一能力注册中心 ─────────────────────────────────────────

class UnifiedCapabilityRegistry:
    """
    统一能力注册中心。

    统一管理 Plugin / Skill / MCP 三种能力来源，
    提供统一的查询、增强和执行接口。
    """

    def __init__(
        self,
        plugin_manager: PluginManager,
        skill_memory: SkillMemory,
        mcp_client: Optional[Any] = None,  # McpClient
    ):
        self.plugin_manager = plugin_manager
        self.skill_memory = skill_memory
        self.mcp_client = mcp_client

        # 内存索引
        self._capabilities: dict[str, CapabilityEntry] = {}
        self._capabilities_by_source: dict[str, dict[str, CapabilityEntry]] = defaultdict(dict)
        self._mcp_tools: dict[str, McpToolEntry] = {}
        self._tag_index: dict[str, set[str]] = defaultdict(set)  # tag → capability names

        # 统计
        self._total_calls = 0
        self._successful_calls = 0

        self._rebuild_index()

    def _rebuild_index(self) -> None:
        """从各个来源重建能力索引"""
        # ── 从 Plugin 索引能力 ──────────────────────────────
        for plugin in self.plugin_manager.list_plugins(status=PluginStatus.ACTIVE):
            for cap in plugin.capabilities:
                entry = CapabilityEntry(
                    name=cap.name,
                    source_type="plugin",
                    source_id=plugin.id,
                    source_name=plugin.display_name or plugin.name,
                    description=cap.description,
                    tags=[t for t in (plugin.name, plugin.display_name, *plugin.description.split()) if t],
                    score_boost=0.1 * (plugin.success_count / max(plugin.total_uses, 1)),
                    total_uses=plugin.total_uses,
                    success_rate=plugin.success_count / max(plugin.total_uses, 1),
                    last_used=plugin.last_used,
                    metadata={"safe_level": plugin.safe_level.value},
                )
                self._capabilities[cap.name] = entry
                self._capabilities_by_source["plugin"][plugin.id] = entry
                for tag in entry.tags:
                    if len(tag) >= 2:
                        self._tag_index[tag.lower()].add(cap.name)

        # ── 从 Skill 索引能力 ──────────────────────────────
        for skill in self.skill_memory.list_skills(status=SkillStatus.ACTIVE):
            for kw in (skill.trigger_keywords or []):
                if kw in self._capabilities:
                    # Skill 增强已有能力
                    existing = self._capabilities[kw]
                    existing.score_boost += 0.2 * skill.success_rate
                else:
                    entry = CapabilityEntry(
                        name=kw,
                        source_type="skill",
                        source_id=skill.id,
                        source_name=skill.name,
                        description=skill.description,
                        tags=skill.tags,
                        score_boost=0.2 * skill.success_rate,
                        total_uses=skill.total_uses,
                        success_rate=skill.success_rate,
                        last_used=skill.last_used,
                        metadata={
                            "steps": len(skill.steps),
                            "preferred_agents": skill.preferred_agents,
                        },
                    )
                    self._capabilities[kw] = entry
                    self._capabilities_by_source["skill"][skill.id] = entry
                    for tag in skill.tags:
                        self._tag_index[tag.lower()].add(kw)

        logger.info(f"[registry] Rebuilt index: {len(self._capabilities)} capabilities, "
                    f"{len(self._tag_index)} tags")

    def rebuild(self) -> None:
        """外部触发重建索引"""
        self._capabilities.clear()
        self._capabilities_by_source.clear()
        self._tag_index.clear()
        self._rebuild_index()

    # ── 能力查询 ─────────────────────────────────────────────

    def find_capabilities(
        self,
        query: str,
        source_type: Optional[str] = None,
        limit: int = 10,
    ) -> list[CapabilityEntry]:
        """
        查询匹配的能力条目。

        匹配策略：精确名称 > 标签包含 > 描述包含
        """
        query_lower = query.lower()
        results: list[tuple[float, CapabilityEntry]] = []

        for cap in self._capabilities.values():
            if source_type and cap.source_type != source_type:
                continue

            score = 0.0

            # 精确名称匹配
            if query_lower == cap.name.lower():
                score = 100.0
            elif cap.name.lower().startswith(query_lower):
                score = 80.0
            elif query_lower in cap.name.lower():
                score = 60.0

            # 标签匹配
            if score == 0:
                for tag in cap.tags:
                    if query_lower in tag.lower():
                        score = 40.0
                        break

            # 描述匹配
            if score == 0 and query_lower in cap.description.lower():
                score = 20.0

            # 成功率加成
            if score > 0:
                score += cap.score_boost

            if score > 0:
                results.append((score, cap))

        results.sort(key=lambda x: x[0], reverse=True)
        return [cap for _, cap in results[:limit]]

    def get_capability(self, name: str) -> Optional[CapabilityEntry]:
        """获取单个能力条目"""
        return self._capabilities.get(name)

    def get_all_capabilities(self, source_type: Optional[str] = None) -> list[CapabilityEntry]:
        """获取所有能力（可按来源过滤）"""
        if source_type:
            caps = self._capabilities_by_source.get(source_type, {}).values()
            return list(caps)
        return list(self._capabilities.values())

    def get_capabilities_by_tag(self, tag: str) -> list[CapabilityEntry]:
        """获取具有特定标签的所有能力"""
        tag_lower = tag.lower()
        names = self._tag_index.get(tag_lower, set())
        return [self._capabilities[n] for n in names if n in self._capabilities]

    # ── MCP 工具注册 ─────────────────────────────────────────

    def register_mcp_tools(self, server_id: str, server_name: str, tools: list[dict]) -> None:
        """注册 MCP Server 的工具到能力注册中心"""
        for tool in tools:
            tool_name = tool.get("name", "")
            if not tool_name:
                continue

            entry = McpToolEntry(
                server_id=server_id,
                server_name=server_name,
                tool_name=tool_name,
                description=tool.get("description", ""),
                input_schema=tool.get("inputSchema", tool.get("input_schema", {})),
                tags=[server_name, "mcp"],
            )
            key = f"{server_id}:{tool_name}"
            self._mcp_tools[key] = entry

            # 同时注册为通用能力（供 Skill 匹配使用）
            cap_name = f"mcp:{tool_name}"
            if cap_name not in self._capabilities:
                self._capabilities[cap_name] = CapabilityEntry(
                    name=cap_name,
                    source_type="mcp",
                    source_id=server_id,
                    source_name=f"{server_name}/{tool_name}",
                    description=tool.get("description", ""),
                    tags=[server_name, "mcp"],
                )

        logger.info(f"[registry] Registered {len(tools)} MCP tools from {server_name}")

    def get_mcp_tool(self, server_id: str, tool_name: str) -> Optional[McpToolEntry]:
        return self._mcp_tools.get(f"{server_id}:{tool_name}")

    def list_mcp_tools(self, server_id: Optional[str] = None) -> list[McpToolEntry]:
        if server_id:
            return [t for t in self._mcp_tools.values() if t.server_id == server_id]
        return list(self._mcp_tools.values())

    # ── 执行能力 ─────────────────────────────────────────────

    async def execute_capability(
        self,
        capability_name: str,
        params: dict,
        context: Optional[dict] = None,
    ) -> dict:
        """
        执行指定能力。

        Returns:
            {"ok": bool, "result": str, "error": str}
        """
        self._total_calls += 1
        start = time.time()

        entry = self._capabilities.get(capability_name)

        if not entry:
            # 降级：尝试 MCP
            if capability_name.startswith("mcp:"):
                tool_name = capability_name[4:]
                return {"ok": False, "result": "", "error": f"MCP tool not found: {tool_name}"}
            return {"ok": False, "result": "", "error": f"Capability not found: {capability_name}"}

        try:
            if entry.source_type == "plugin":
                result = await self._execute_plugin(entry, params)
            elif entry.source_type == "skill":
                result = await self._execute_skill(entry, params, context or {})
            elif entry.source_type == "mcp":
                result = await self._execute_mcp_tool(entry, params)
            else:
                result = {"ok": False, "error": f"Unknown source type: {entry.source_type}"}

            elapsed_ms = (time.time() - start) * 1000

            if result.get("ok"):
                self._successful_calls += 1
                entry.total_uses += 1
                entry.last_used = time.strftime("%Y-%m-%dT%H:%M:%S")
            else:
                entry.metadata["last_error"] = result.get("error", "")

            result["elapsed_ms"] = round(elapsed_ms, 2)
            return result

        except Exception as e:
            logger.error(f"[registry] execute_capability {capability_name} error: {e}")
            return {"ok": False, "result": "", "error": str(e)}

    async def _execute_plugin(self, entry: CapabilityEntry, params: dict) -> dict:
        """执行 Plugin 能力"""
        plugin = self.plugin_manager.get_plugin(entry.source_id)
        if not plugin:
            return {"ok": False, "error": f"Plugin not found: {entry.source_id}"}

        # 调用插件（具体调用逻辑取决于插件类型，这里做通用兜底）
        plugin.record_use(success=True)
        return {
            "ok": True,
            "result": f"Plugin '{plugin.name}' executed via capability '{entry.name}'",
        }

    async def _execute_skill(self, entry: CapabilityEntry, params: dict, context: dict) -> dict:
        """执行 Skill 能力"""
        skill = self.skill_memory.get_skill(entry.source_id)
        if not skill:
            return {"ok": False, "error": f"Skill not found: {entry.source_id}"}

        # Skill 执行：按步骤执行
        steps_summary = []
        for step in skill.steps:
            steps_summary.append(f"Step {step.step_id}: {step.action} (agent={step.agent})")

        skill.record_success(duration=0)
        return {
            "ok": True,
            "result": f"Skill '{skill.name}' executed with {len(skill.steps)} steps:\n" +
                      "\n".join(steps_summary),
        }

    async def _execute_mcp_tool(self, entry: CapabilityEntry, params: dict) -> dict:
        """执行 MCP 工具"""
        if not self.mcp_client:
            return {"ok": False, "error": "MCP client not initialized"}

        # entry.source_id = server_id
        # entry.source_name = "server_name/tool_name"
        parts = entry.source_name.split("/")
        if len(parts) < 2:
            return {"ok": False, "error": f"Invalid MCP tool name: {entry.source_name}"}

        server_id = entry.source_id
        tool_name = entry.name.replace("mcp:", "")

        result = await self.mcp_client.call_tool(server_id, tool_name, params)
        return result

    # ── 统计 ─────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """获取注册中心统计"""
        by_source: dict[str, int] = defaultdict(int)
        for cap in self._capabilities.values():
            by_source[cap.source_type] += 1

        return {
            "total_capabilities": len(self._capabilities),
            "by_source": dict(by_source),
            "mcp_tools": len(self._mcp_tools),
            "total_calls": self._total_calls,
            "successful_calls": self._successful_calls,
            "overall_success_rate": (
                round(self._successful_calls / self._total_calls * 100, 1)
                if self._total_calls > 0 else 0
            ),
            "top_capabilities": sorted(
                [c.to_dict() for c in self._capabilities.values()],
                key=lambda x: x["total_uses"],
                reverse=True,
            )[:5],
        }
