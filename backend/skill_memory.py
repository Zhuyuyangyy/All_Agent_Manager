"""
skill_memory.py — 技能记忆库模块

存储、匹配、管理从成功任务中提炼的技能模板。
让调度系统"越用越聪明"。
"""

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class SkillStatus(StrEnum):
    """技能状态"""
    DRAFT = "draft"          # 草稿，待确认
    ACTIVE = "active"        # 已激活，可自动使用
    DISABLED = "disabled"    # 已禁用
    ARCHIVED = "archived"    # 已归档


class SkillSource(StrEnum):
    """技能来源"""
    MANUAL = "manual"        # 人工创建
    AUTO_EXTRACT = "auto"    # 从任务自动提取
    IMPORTED = "imported"    # 从外部导入


@dataclass
class SkillStep:
    """技能执行步骤"""
    step_id: int
    action: str              # 动作描述
    agent: str               # 执行的 Agent
    plugin: str | None = None  # 需要的插件
    fallback: str | None = None  # 备选方案
    timeout: float = 300     # 超时时间
    retry_on_fail: bool = True  # 失败是否重试

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "action": self.action,
            "agent": self.agent,
            "plugin": self.plugin,
            "fallback": self.fallback,
            "timeout": self.timeout,
            "retry_on_fail": self.retry_on_fail,
        }


@dataclass
class SkillTemplate:
    """技能模板"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    description: str = ""
    status: SkillStatus = SkillStatus.DRAFT
    source: SkillSource = SkillSource.MANUAL

    # 适用场景
    trigger_keywords: list[str] = field(default_factory=list)
    trigger_patterns: list[str] = field(default_factory=list)
    applicable_task_types: list[str] = field(default_factory=list)

    # 执行流程
    steps: list[SkillStep] = field(default_factory=list)
    required_plugins: list[str] = field(default_factory=list)
    preferred_agents: list[str] = field(default_factory=list)

    # 统计
    total_uses: int = 0
    success_count: int = 0
    fail_count: int = 0
    avg_duration: float = 0
    last_used: str | None = None
    last_success: str | None = None
    last_failure: str | None = None
    failure_reasons: list[str] = field(default_factory=list)

    # 元数据
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    created_by: str = "system"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "source": self.source.value,
            "trigger_keywords": self.trigger_keywords,
            "trigger_patterns": self.trigger_patterns,
            "applicable_task_types": self.applicable_task_types,
            "steps": [s.to_dict() for s in self.steps],
            "required_plugins": self.required_plugins,
            "preferred_agents": self.preferred_agents,
            "total_uses": self.total_uses,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "success_rate": round(self.success_count / self.total_uses * 100, 1) if self.total_uses > 0 else 0,
            "avg_duration": round(self.avg_duration, 2),
            "last_used": self.last_used,
            "last_success": self.last_success,
            "last_failure": self.last_failure,
            "failure_reasons": self.failure_reasons[-5:],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    def record_success(self, duration: float) -> None:
        """记录一次成功使用"""
        self.total_uses += 1
        self.success_count += 1
        self.last_used = datetime.now().isoformat()
        self.last_success = self.last_used
        # 更新平均耗时
        self.avg_duration = (
            self.avg_duration * (self.total_uses - 1) + duration
        ) / self.total_uses
        self.updated_at = self.last_used

    def record_failure(self, error: str) -> None:
        """记录一次失败"""
        self.total_uses += 1
        self.fail_count += 1
        self.last_used = datetime.now().isoformat()
        self.last_failure = self.last_used
        self.failure_reasons.append(error)
        # 只保留最近 10 条
        if len(self.failure_reasons) > 10:
            self.failure_reasons = self.failure_reasons[-10:]
        self.updated_at = self.last_used

    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_uses == 0:
            return 0
        return self.success_count / self.total_uses * 100


class SkillMemory:
    """
    技能记忆库。
    存储、检索、匹配技能模板。
    """

    def __init__(self, storage_path: str | Path = "storage/skills.json"):
        self.storage_path = Path(storage_path)
        self._skills: dict[str, SkillTemplate] = {}
        self._load()

    def _load(self) -> None:
        """从文件加载技能"""
        if not self.storage_path.exists():
            return

        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for skill_data in data.get("skills", []):
                skill = self._deserialize_skill(skill_data)
                self._skills[skill.id] = skill
        except Exception:
            pass

    def _save(self) -> None:
        """保存技能到文件"""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": 1,
            "updated_at": datetime.now().isoformat(),
            "skills": [self._serialize_skill(s) for s in self._skills.values()],
        }

        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _serialize_skill(self, skill: SkillTemplate) -> dict:
        """序列化技能"""
        d = skill.to_dict()
        d["steps"] = [s.to_dict() for s in skill.steps]
        return d

    def _deserialize_skill(self, data: dict) -> SkillTemplate:
        """反序列化技能"""
        steps = []
        for step_data in data.get("steps", []):
            steps.append(SkillStep(
                step_id=step_data["step_id"],
                action=step_data["action"],
                agent=step_data["agent"],
                plugin=step_data.get("plugin"),
                fallback=step_data.get("fallback"),
                timeout=step_data.get("timeout", 300),
                retry_on_fail=step_data.get("retry_on_fail", True),
            ))

        return SkillTemplate(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            status=SkillStatus(data.get("status", "draft")),
            source=SkillSource(data.get("source", "manual")),
            trigger_keywords=data.get("trigger_keywords", []),
            trigger_patterns=data.get("trigger_patterns", []),
            applicable_task_types=data.get("applicable_task_types", []),
            steps=steps,
            required_plugins=data.get("required_plugins", []),
            preferred_agents=data.get("preferred_agents", []),
            total_uses=data.get("total_uses", 0),
            success_count=data.get("success_count", 0),
            fail_count=data.get("fail_count", 0),
            avg_duration=data.get("avg_duration", 0),
            last_used=data.get("last_used"),
            last_success=data.get("last_success"),
            last_failure=data.get("last_failure"),
            failure_reasons=data.get("failure_reasons", []),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            created_by=data.get("created_by", "system"),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )

    # ── CRUD 操作 ──

    def create_skill(self, skill: SkillTemplate) -> SkillTemplate:
        """创建新技能"""
        self._skills[skill.id] = skill
        self._save()
        return skill

    def get_skill(self, skill_id: str) -> SkillTemplate | None:
        """获取技能"""
        return self._skills.get(skill_id)

    def update_skill(self, skill: SkillTemplate) -> SkillTemplate:
        """更新技能"""
        skill.updated_at = datetime.now().isoformat()
        self._skills[skill.id] = skill
        self._save()
        return skill

    def delete_skill(self, skill_id: str) -> bool:
        """删除技能"""
        if skill_id in self._skills:
            del self._skills[skill_id]
            self._save()
            return True
        return False

    def list_skills(
        self,
        status: SkillStatus | None = None,
        tags: list[str] | None = None,
    ) -> list[SkillTemplate]:
        """列出技能"""
        skills = list(self._skills.values())

        if status:
            skills = [s for s in skills if s.status == status]

        if tags:
            skills = [s for s in skills if any(t in s.tags for t in tags)]

        return skills

    # ── 技能匹配 ──

    def match_skill(
        self,
        task_goal: str,
        task_type: str | None = None,
    ) -> SkillTemplate | None:
        """
        根据任务描述匹配最合适的技能。
        优先级：精确关键词 > 模糊关键词 > 任务类型 > 无匹配
        """
        task_lower = task_goal.lower()
        best_match: SkillTemplate | None = None
        best_score = 0

        for skill in self._skills.values():
            if skill.status != SkillStatus.ACTIVE:
                continue

            score = 0

            # 关键词匹配
            for keyword in skill.trigger_keywords:
                if keyword.lower() in task_lower:
                    score += 10

            # 模式匹配（简单包含）
            for pattern in skill.trigger_patterns:
                if pattern.lower() in task_lower:
                    score += 5

            # 任务类型匹配
            if task_type and task_type in skill.applicable_task_types:
                score += 3

            # 成功率加成
            if skill.total_uses > 0:
                score += skill.success_rate / 100 * 2

            if score > best_score:
                best_score = score
                best_match = skill

        # 只有分数足够高才返回匹配
        if best_score >= 5:
            return best_match

        return None

    def find_fallback_chain(self, failed_skill: SkillTemplate) -> list[SkillTemplate]:
        """查找失败技能的备选方案"""
        fallbacks = []

        for skill in self._skills.values():
            if skill.id == failed_skill.id:
                continue
            if skill.status != SkillStatus.ACTIVE:
                continue

            # 检查是否有重叠的触发关键词
            overlap = set(failed_skill.trigger_keywords) & set(skill.trigger_keywords)
            if overlap:
                fallbacks.append(skill)

        # 按成功率排序
        fallbacks.sort(key=lambda s: s.success_rate, reverse=True)

        return fallbacks

    # ── 统计 ──

    def get_stats(self) -> dict:
        """获取技能统计"""
        all_skills = list(self._skills.values())
        active = [s for s in all_skills if s.status == SkillStatus.ACTIVE]
        drafts = [s for s in all_skills if s.status == SkillStatus.DRAFT]

        total_uses = sum(s.total_uses for s in all_skills)
        total_success = sum(s.success_count for s in all_skills)

        return {
            "total_skills": len(all_skills),
            "active_skills": len(active),
            "draft_skills": len(drafts),
            "total_uses": total_uses,
            "total_success": total_success,
            "overall_success_rate": round(total_success / total_uses * 100, 1) if total_uses > 0 else 0,
            "top_skills": sorted(
                [s.to_dict() for s in all_skills],
                key=lambda x: x["total_uses"],
                reverse=True
            )[:5],
        }

    # ── 技能激活/禁用 ──

    def activate_skill(self, skill_id: str) -> bool:
        """激活技能"""
        skill = self._skills.get(skill_id)
        if skill:
            skill.status = SkillStatus.ACTIVE
            self._save()
            return True
        return False

    def disable_skill(self, skill_id: str) -> bool:
        """禁用技能"""
        skill = self._skills.get(skill_id)
        if skill:
            skill.status = SkillStatus.DISABLED
            self._save()
            return True
        return False

    def archive_skill(self, skill_id: str) -> bool:
        """归档技能"""
        skill = self._skills.get(skill_id)
        if skill:
            skill.status = SkillStatus.ARCHIVED
            self._save()
            return True
        return False


def build_skill_memory_from_env() -> SkillMemory:
    """从环境变量构建技能记忆库"""
    storage_path = os.getenv("SKILL_STORAGE_PATH", "storage/skills.json")
    return SkillMemory(storage_path=storage_path)
