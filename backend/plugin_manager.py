"""
plugin_manager.py — 插件管理器模块

管理 Agent 可用的插件和能力，支持能力匹配和失败 fallback。
"""

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class PluginStatus(StrEnum):
    """插件状态"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    INSTALLING = "installing"


class SafeLevel(StrEnum):
    """安全级别"""
    LOW = "low"          # 安全，无需审批
    MEDIUM = "medium"    # 中等，建议审批
    HIGH = "high"        # 高风险，必须审批


@dataclass
class PluginCapability:
    """插件能力"""
    name: str
    description: str = ""
    input_types: list[str] = field(default_factory=list)
    output_types: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_types": self.input_types,
            "output_types": self.output_types,
        }


@dataclass
class PluginRecord:
    """插件记录"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    display_name: str = ""
    description: str = ""
    version: str = "1.0.0"
    status: PluginStatus = PluginStatus.ACTIVE
    safe_level: SafeLevel = SafeLevel.MEDIUM

    # 能力
    capabilities: list[PluginCapability] = field(default_factory=list)

    # 配置
    allowed_agents: list[str] = field(default_factory=list)
    requires_approval: bool = False
    fallback_plugins: list[str] = field(default_factory=list)

    # 统计
    total_uses: int = 0
    success_count: int = 0
    fail_count: int = 0
    last_used: str | None = None
    failure_history: list[dict] = field(default_factory=list)

    # 元数据
    installed_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "version": self.version,
            "status": self.status.value,
            "safe_level": self.safe_level.value,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "capability_names": [c.name for c in self.capabilities],
            "allowed_agents": self.allowed_agents,
            "requires_approval": self.requires_approval,
            "fallback_plugins": self.fallback_plugins,
            "total_uses": self.total_uses,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "success_rate": round(self.success_count / self.total_uses * 100, 1) if self.total_uses > 0 else 0,
            "last_used": self.last_used,
            "failure_history": self.failure_history[-5:],
            "installed_at": self.installed_at,
            "updated_at": self.updated_at,
            "config": self.config,
        }

    def has_capability(self, capability_name: str) -> bool:
        """检查是否有指定能力"""
        return any(c.name == capability_name for c in self.capabilities)

    def record_use(self, success: bool, error: str | None = None) -> None:
        """记录使用"""
        self.total_uses += 1
        self.last_used = datetime.now().isoformat()
        self.updated_at = self.last_used

        if success:
            self.success_count += 1
        else:
            self.fail_count += 1
            if error:
                self.failure_history.append({
                    "error": error,
                    "timestamp": self.last_used,
                })
                # 只保留最近 20 条
                if len(self.failure_history) > 20:
                    self.failure_history = self.failure_history[-20:]


class PluginManager:
    """
    插件管理器。
    管理插件注册、能力查询、fallback 链。
    """

    def __init__(self, storage_path: str | Path = "storage/plugins.json"):
        self.storage_path = Path(storage_path)
        self._plugins: dict[str, PluginRecord] = {}
        self._load()

    def _load(self) -> None:
        """从文件加载插件"""
        if not self.storage_path.exists():
            return

        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for plugin_data in data.get("plugins", []):
                plugin = self._deserialize_plugin(plugin_data)
                self._plugins[plugin.id] = plugin
        except Exception:
            pass

    def _save(self) -> None:
        """保存插件到文件"""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": 1,
            "updated_at": datetime.now().isoformat(),
            "plugins": [self._serialize_plugin(p) for p in self._plugins.values()],
        }

        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _serialize_plugin(self, plugin: PluginRecord) -> dict:
        """序列化插件"""
        d = plugin.to_dict()
        d["capabilities"] = [c.to_dict() for c in plugin.capabilities]
        return d

    def _deserialize_plugin(self, data: dict) -> PluginRecord:
        """反序列化插件"""
        capabilities = []
        for cap_data in data.get("capabilities", []):
            capabilities.append(PluginCapability(
                name=cap_data["name"],
                description=cap_data.get("description", ""),
                input_types=cap_data.get("input_types", []),
                output_types=cap_data.get("output_types", []),
            ))

        return PluginRecord(
            id=data["id"],
            name=data["name"],
            display_name=data.get("display_name", data["name"]),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            status=PluginStatus(data.get("status", "active")),
            safe_level=SafeLevel(data.get("safe_level", "medium")),
            capabilities=capabilities,
            allowed_agents=data.get("allowed_agents", []),
            requires_approval=data.get("requires_approval", False),
            fallback_plugins=data.get("fallback_plugins", []),
            total_uses=data.get("total_uses", 0),
            success_count=data.get("success_count", 0),
            fail_count=data.get("fail_count", 0),
            last_used=data.get("last_used"),
            failure_history=data.get("failure_history", []),
            installed_at=data.get("installed_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            config=data.get("config", {}),
        )

    # ── CRUD 操作 ──

    def register_plugin(self, plugin: PluginRecord) -> PluginRecord:
        """注册插件"""
        self._plugins[plugin.id] = plugin
        self._save()
        return plugin

    def get_plugin(self, plugin_id: str) -> PluginRecord | None:
        """获取插件"""
        return self._plugins.get(plugin_id)

    def get_plugin_by_name(self, name: str) -> PluginRecord | None:
        """按名称获取插件"""
        for plugin in self._plugins.values():
            if plugin.name == name:
                return plugin
        return None

    def update_plugin(self, plugin: PluginRecord) -> PluginRecord:
        """更新插件"""
        plugin.updated_at = datetime.now().isoformat()
        self._plugins[plugin.id] = plugin
        self._save()
        return plugin

    def unregister_plugin(self, plugin_id: str) -> bool:
        """注销插件"""
        if plugin_id in self._plugins:
            del self._plugins[plugin_id]
            self._save()
            return True
        return False

    def list_plugins(
        self,
        status: PluginStatus | None = None,
        agent: str | None = None,
    ) -> list[PluginRecord]:
        """列出插件"""
        plugins = list(self._plugins.values())

        if status:
            plugins = [p for p in plugins if p.status == status]

        if agent:
            plugins = [p for p in plugins if agent in p.allowed_agents or not p.allowed_agents]

        return plugins

    # ── 能力查询 ──

    def find_plugins_for_capability(
        self,
        capability: str,
        agent: str | None = None,
    ) -> list[PluginRecord]:
        """查找拥有指定能力的插件"""
        results = []

        for plugin in self._plugins.values():
            if plugin.status != PluginStatus.ACTIVE:
                continue

            if not plugin.has_capability(capability):
                continue

            # 检查 Agent 权限
            if agent and plugin.allowed_agents and agent not in plugin.allowed_agents:
                continue

            results.append(plugin)

        # 按成功率排序
        results.sort(key=lambda p: p.success_rate if p.total_uses > 0 else 0.5, reverse=True)

        return results

    def find_plugins_for_task(self, task_requirements: list[str]) -> list[PluginRecord]:
        """根据任务需求查找插件"""
        matching = []

        for plugin in self._plugins.values():
            if plugin.status != PluginStatus.ACTIVE:
                continue

            # 检查能力匹配
            plugin_caps = {c.name for c in plugin.capabilities}
            if set(task_requirements) & plugin_caps:
                matching.append(plugin)

        return matching

    def get_fallback_chain(self, plugin_name: str) -> list[PluginRecord]:
        """获取插件的 fallback 链"""
        plugin = self.get_plugin_by_name(plugin_name)
        if not plugin:
            return []

        chain = []
        visited = {plugin_name}

        for fallback_name in plugin.fallback_plugins:
            if fallback_name in visited:
                continue

            fallback = self.get_plugin_by_name(fallback_name)
            if fallback and fallback.status == PluginStatus.ACTIVE:
                chain.append(fallback)
                visited.add(fallback_name)

        return chain

    # ── 能力库查询 ──

    def get_all_capabilities(self) -> dict[str, list[str]]:
        """获取所有可用能力及对应的插件"""
        capabilities: dict[str, list[str]] = {}

        for plugin in self._plugins.values():
            if plugin.status != PluginStatus.ACTIVE:
                continue

            for cap in plugin.capabilities:
                if cap.name not in capabilities:
                    capabilities[cap.name] = []
                capabilities[cap.name].append(plugin.name)

        return capabilities

    # ── 统计 ──

    def get_stats(self) -> dict:
        """获取插件统计"""
        all_plugins = list(self._plugins.values())
        active = [p for p in all_plugins if p.status == PluginStatus.ACTIVE]

        total_uses = sum(p.total_uses for p in all_plugins)
        total_success = sum(p.success_count for p in all_plugins)

        return {
            "total_plugins": len(all_plugins),
            "active_plugins": len(active),
            "total_uses": total_uses,
            "total_success": total_success,
            "overall_success_rate": round(total_success / total_uses * 100, 1) if total_uses > 0 else 0,
            "capabilities": self.get_all_capabilities(),
        }

    # ── 插件启用/禁用 ──

    def enable_plugin(self, plugin_id: str) -> bool:
        """启用插件"""
        plugin = self._plugins.get(plugin_id)
        if plugin:
            plugin.status = PluginStatus.ACTIVE
            self._save()
            return True
        return False

    def disable_plugin(self, plugin_id: str) -> bool:
        """禁用插件"""
        plugin = self._plugins.get(plugin_id)
        if plugin:
            plugin.status = PluginStatus.INACTIVE
            self._save()
            return True
        return False


def build_plugin_manager_from_env() -> PluginManager:
    """从环境变量构建插件管理器"""
    storage_path = os.getenv("PLUGIN_STORAGE_PATH", "storage/plugins.json")
    return PluginManager(storage_path=storage_path)
