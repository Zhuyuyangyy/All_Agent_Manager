"""
skill_loader.py — Skill 生命周期管理器

管理 Skill 的：
  1. 生命周期（创建→草稿→激活→使用→归档）
  2. Slash 命令注入（将 Skill 暴露为 /skill_name 斜杠命令）
  3. 从 Hermes Agent ~/.hermes/skills/ 目录同步 Skill
  4. Skill 执行引擎（给定 SkillTemplate，执行完整步骤链）

参照 hermes-agent 的 skill_commands.py 设计：
  - 每个 Skill 可通过斜杠命令触发
  - Skill 的步骤链（SkillStep）映射到具体 Agent 调用
  - 支持 fallback：某 Agent 不可用时切换到备选 Agent
"""

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from backend.skill_memory import SkillMemory, SkillTemplate, SkillStatus, SkillStep

logger = logging.getLogger(__name__)


# ── Slash 命令条目 ──────────────────────────────────────────

@dataclass
class SlashCommand:
    """斜杠命令条目"""
    name: str
    skill_id: str
    description: str
    args_hint: str = ""          # 参数提示，如 "[query]"
    category: str = "General"
    agent: str = "hermes"        # 默认执行 Agent
    examples: list[str] = field(default_factory=list)


# ── Skill 执行上下文 ─────────────────────────────────────────

@dataclass
class SkillExecutionContext:
    """Skill 执行时的上下文"""
    skill_id: str
    skill_name: str
    user_id: str = "default"
    chat_id: str = ""
    params: dict = field(default_factory=dict)
    current_step: int = 0
    history: list[dict] = field(default_factory=list)   # 步骤执行历史
    started_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "params": self.params,
            "current_step": self.current_step,
            "history": self.history,
            "started_at": self.started_at,
        }


# ── Skill 执行结果 ──────────────────────────────────────────

@dataclass
class SkillExecutionResult:
    """Skill 执行结果"""
    ok: bool
    skill_id: str
    skill_name: str
    final_output: str = ""
    error: str = ""
    steps_completed: int = 0
    total_steps: int = 0
    duration_ms: float = 0
    step_results: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "final_output": self.final_output,
            "error": self.error,
            "steps_completed": self.steps_completed,
            "total_steps": self.total_steps,
            "duration_ms": round(self.duration_ms, 2),
            "step_results": self.step_results,
        }


# ── Skill 执行器接口 ──────────────────────────────────────

class SkillExecutor:
    """
    Skill 执行器 — 执行一个 Skill 的步骤链。

    每一个步骤由一个 SkillStep 描述：
      step_id, action, agent, plugin, fallback, timeout, retry_on_fail

    SkillExecutor 调用 worker_factory(agent, step_id, action) 来执行每个步骤。
    """

    def __init__(
        self,
        skill_memory: SkillMemory,
        worker_factory: Callable[[str, str, str], Any],  # (agent, step_id, action) → coroutine
    ):
        self.skill_memory = skill_memory
        self.worker_factory = worker_factory

    async def execute_skill(
        self,
        skill_id: str,
        params: dict,
        context: Optional[SkillExecutionContext] = None,
    ) -> SkillExecutionResult:
        """
        执行完整的 Skill 步骤链。

        Args:
            skill_id: Skill 的 ID
            params: 执行参数（如 {"query": "..."}）
            context: 执行上下文

        Returns:
            SkillExecutionResult
        """
        skill = self.skill_memory.get_skill(skill_id)
        if not skill:
            return SkillExecutionResult(
                ok=False,
                skill_id=skill_id,
                skill_name="<unknown>",
                error=f"Skill not found: {skill_id}",
            )

        if skill.status != SkillStatus.ACTIVE:
            return SkillExecutionResult(
                ok=False,
                skill_id=skill_id,
                skill_name=skill.name,
                error=f"Skill is not active (status={skill.status.value})",
            )

        start = time.time()
        step_results: list[dict] = []
        ctx = context or SkillExecutionContext(skill_id=skill_id, skill_name=skill.name)
        ctx.params.update(params)

        for step in skill.steps:
            ctx.current_step = step.step_id
            step_start = time.time()

            # 选择 Agent（支持 fallback）
            agent = self._select_agent(step, skill)

            for attempt in range(step.retry_on_fail and 2 or 1):
                try:
                    worker = self.worker_factory(agent, str(step.step_id), step.action)
                    result = await worker.run()

                    step_duration = (time.time() - step_start) * 1000

                    step_results.append({
                        "step_id": step.step_id,
                        "action": step.action,
                        "agent": agent,
                        "ok": True,
                        "result": result,
                        "duration_ms": round(step_duration, 2),
                        "attempt": attempt + 1,
                    })
                    ctx.history.append(step_results[-1])

                    # 记录成功
                    skill.record_success(duration=step_duration)
                    break

                except Exception as e:
                    if attempt < (step.retry_on_fail and 1 or 0):
                        logger.warning(f"[skill-executor] Step {step.step_id} attempt {attempt + 1} failed: {e}")
                        await asyncio.sleep(2 ** attempt)
                        continue

                    step_duration = (time.time() - step_start) * 1000
                    error_msg = str(e)

                    step_results.append({
                        "step_id": step.step_id,
                        "action": step.action,
                        "agent": agent,
                        "ok": False,
                        "error": error_msg,
                        "duration_ms": round(step_duration, 2),
                        "attempt": attempt + 1,
                    })
                    ctx.history.append(step_results[-1])
                    skill.record_failure(error_msg)

                    # 如果配置了 fallback，尝试 fallback
                    if step.fallback and agent != step.fallback:
                        agent = step.fallback
                        continue

                    # 失败终止
                    duration_ms = (time.time() - start) * 1000
                    return SkillExecutionResult(
                        ok=False,
                        skill_id=skill_id,
                        skill_name=skill.name,
                        error=f"Step {step.step_id} failed: {error_msg}",
                        steps_completed=len(step_results) - 1,
                        total_steps=len(skill.steps),
                        duration_ms=duration_ms,
                        step_results=step_results,
                    )

        duration_ms = (time.time() - start) * 1000
        final_output = "\n\n".join(
            r.get("result", r.get("error", ""))
            for r in step_results
        )

        return SkillExecutionResult(
            ok=True,
            skill_id=skill_id,
            skill_name=skill.name,
            final_output=final_output,
            steps_completed=len(skill.steps),
            total_steps=len(skill.steps),
            duration_ms=duration_ms,
            step_results=step_results,
        )

    def _select_agent(self, step: SkillStep, skill: SkillTemplate) -> str:
        """选择执行步骤的 Agent（优先 Skill 的 preferred_agents）"""
        if skill.preferred_agents and step.agent in skill.preferred_agents:
            return step.agent
        if step.agent:
            return step.agent
        return "hermes"


# ── Slash 命令注册表 ───────────────────────────────────────

class SlashCommandRegistry:
    """
    斜杠命令注册表。

    从 SkillMemory 中提取所有 ACTIVE 的 Skill，
    生成可被 Agent/前端消费的斜杠命令列表。

    参照 hermes_cli/commands.py 的 CommandDef 设计。
    """

    CATEGORY_LABELS = {
        "code": "代码与开发",
        "research": "研究与调研",
        "file": "文件操作",
        "data": "数据分析",
        "web": "网络搜索",
        "communication": "沟通协作",
        "personal": "个人效率",
    }

    def __init__(self, skill_memory: SkillMemory):
        self.skill_memory = skill_memory
        self._commands: dict[str, SlashCommand] = {}

    def rebuild(self) -> None:
        """从 SkillMemory 重建斜杠命令列表"""
        self._commands.clear()

        for skill in self.skill_memory.list_skills(status=SkillStatus.ACTIVE):
            cmd = self._skill_to_command(skill)
            if cmd:
                self._commands[cmd.name] = cmd

        logger.info(f"[slash] Rebuilt {len(self._commands)} slash commands")

    def _skill_to_command(self, skill: SkillTemplate) -> Optional[SlashCommand]:
        """将 SkillTemplate 转换为 SlashCommand"""
        if not skill.trigger_keywords:
            return None

        # 取第一个 keyword 作为命令名
        primary_kw = skill.trigger_keywords[0]

        # 推断分类
        category = self._infer_category(skill)

        # 推断默认 Agent
        agent = "hermes"
        if skill.preferred_agents:
            agent = skill.preferred_agents[0]
        elif skill.steps:
            agent = skill.steps[0].agent

        return SlashCommand(
            name=primary_kw,
            skill_id=skill.id,
            description=skill.description or skill.name,
            args_hint=self._build_args_hint(skill),
            category=category,
            agent=agent,
            examples=self._build_examples(skill),
        )

    def _infer_category(self, skill: SkillTemplate) -> str:
        """从 Skill 的 trigger_keywords 推断分类"""
        all_keywords = " ".join(skill.trigger_keywords).lower()

        if any(k in all_keywords for k in ["代码", "code", "python", "bug", "debug", "写代码"]):
            return "代码与开发"
        if any(k in all_keywords for k in ["研究", "research", "分析", "调研", "report"]):
            return "研究与调研"
        if any(k in all_keywords for k in ["文件", "file", "整理", "整理文件"]):
            return "文件操作"
        if any(k in all_keywords for k in ["数据", "data", "统计", "分析"]):
            return "数据分析"
        if any(k in all_keywords for k in ["搜索", "search", "web", "查资料"]):
            return "网络搜索"
        if any(k in all_keywords for k in ["微信", "wechat", "通知", "提醒"]):
            return "沟通协作"
        return "个人效率"

    def _build_args_hint(self, skill: SkillTemplate) -> str:
        """构建参数提示"""
        if not skill.trigger_keywords:
            return ""
        if len(skill.trigger_keywords) > 1:
            return f"[{skill.trigger_keywords[1]}]"
        return "[args]"

    def _build_examples(self, skill: SkillTemplate) -> list[str]:
        """构建使用示例"""
        examples = []
        if skill.trigger_keywords:
            cmd = skill.trigger_keywords[0]
            examples.append(f"/{cmd} {skill.trigger_keywords[1] or 'query'}")
        return examples

    def get_command(self, name: str) -> Optional[SlashCommand]:
        return self._commands.get(name)

    def get_all_commands(self) -> list[SlashCommand]:
        return list(self._commands.values())

    def get_commands_by_category(self) -> dict[str, list[SlashCommand]]:
        result: dict[str, list[SlashCommand]] = {}
        for cmd in self._commands.values():
            if cmd.category not in result:
                result[cmd.category] = []
            result[cmd.category].append(cmd)
        return result

    def match_command(self, text: str) -> Optional[SlashCommand]:
        """
        从文本中匹配斜杠命令。

        支持：
          /skill_name
          /skill_name arg1 arg2
          skill_name: arg1 arg2
        """
        text = text.strip()
        if text.startswith("/"):
            parts = text[1:].split(None, 1)
            cmd_name = parts[0].lower()
            return self._commands.get(cmd_name)

        # 不带 / 的命令（如 "skill_name: query"）
        for name, cmd in self._commands.items():
            if text.lower().startswith(name):
                return cmd

        return None


# ── Skill 同步器 ──────────────────────────────────────────

class SkillSynchronizer:
    """
    从 Hermes Agent ~/.hermes/skills/ 目录同步 Skill。

    读取 Hermès 的 Skill 文件（SKILL.md + references/），
    转换为 SkillTemplate 并存入 SkillMemory。
    """

    # Hermes Skill 目录的典型路径
    DEFAULT_SKILL_DIRS = [
        Path.home() / ".hermes" / "skills",
        Path.home() / "skills",
    ]

    def __init__(self, skill_memory: SkillMemory, skill_dir: Optional[Path] = None):
        self.skill_memory = skill_memory
        self.skill_dir = skill_dir or self._find_skill_dir()

    def _find_skill_dir(self) -> Optional[Path]:
        for d in self.DEFAULT_SKILL_DIRS:
            if d.exists():
                return d
        return None

    def sync_all(self) -> dict:
        """
        同步所有 Hermès Skill。

        Returns:
            {"added": int, "updated": int, "errors": list[str]}
        """
        if not self.skill_dir:
            return {"added": 0, "updated": 0, "errors": ["Skill directory not found"]}

        added = 0
        updated = 0
        errors = []

        for skill_path in self.skill_dir.iterdir():
            if not skill_path.is_dir():
                continue

            try:
                result = self._sync_single(skill_path)
                if result == "added":
                    added += 1
                elif result == "updated":
                    updated += 1
            except Exception as e:
                errors.append(f"{skill_path.name}: {e}")
                logger.error(f"[skill-sync] Failed to sync {skill_path.name}: {e}")

        logger.info(f"[skill-sync] Done: added={added}, updated={updated}, errors={len(errors)}")
        return {"added": added, "updated": updated, "errors": errors}

    def _sync_single(self, skill_path: Path) -> str:
        """同步单个 Skill，返回 'added' | 'updated'"""
        skill_md = skill_path / "SKILL.md"
        if not skill_md.exists():
            return "skipped"

        # 解析 SKILL.md 的 frontmatter
        content = skill_md.read_text(encoding="utf-8")
        metadata, body = self._parse_skill_md(content)

        # 检查是否已存在
        existing = self._find_by_name(metadata.get("name", skill_path.name))

        skill = self._build_template(metadata, body, skill_path)

        if existing:
            skill.id = existing.id
            self.skill_memory.update_skill(skill)
            return "updated"
        else:
            self.skill_memory.create_skill(skill)
            return "added"

    def _parse_skill_md(self, content: str) -> tuple[dict, str]:
        """解析 SKILL.md 的 YAML frontmatter"""
        import re

        match = re.match(r"^---\n(.*?)\n---\n(.*)$", content, re.DOTALL)
        if not match:
            return {}, content

        import yaml
        try:
            metadata = yaml.safe_load(match.group(1)) or {}
        except Exception:
            metadata = {}

        return metadata, match.group(2)

    def _build_template(self, metadata: dict, body: str, skill_path: Path) -> SkillTemplate:
        """从元数据构建 SkillTemplate"""
        from backend.skill_memory import SkillSource, SkillStatus, SkillStep

        steps = []
        for i, step_data in enumerate(metadata.get("steps", [])):
            steps.append(SkillStep(
                step_id=i + 1,
                action=step_data.get("action", ""),
                agent=step_data.get("agent", "hermes"),
                plugin=step_data.get("plugin"),
                fallback=step_data.get("fallback"),
                timeout=step_data.get("timeout", 300),
                retry_on_fail=step_data.get("retry_on_fail", True),
            ))

        tags = metadata.get("tags", [])
        if not isinstance(tags, list):
            tags = [tags]

        return SkillTemplate(
            name=metadata.get("name", skill_path.name),
            description=metadata.get("description", ""),
            status=SkillStatus.ACTIVE,
            source=SkillSource.IMPORTED,
            trigger_keywords=metadata.get("trigger_keywords", [skill_path.name]),
            trigger_patterns=metadata.get("trigger_patterns", []),
            applicable_task_types=metadata.get("applicable_task_types", []),
            steps=steps,
            required_plugins=metadata.get("required_plugins", []),
            preferred_agents=metadata.get("preferred_agents", []),
            created_by="hermes-import",
            tags=tags,
        )

    def _find_by_name(self, name: str) -> Optional[SkillTemplate]:
        for skill in self.skill_memory.list_skills():
            if skill.name == name:
                return skill
        return None

