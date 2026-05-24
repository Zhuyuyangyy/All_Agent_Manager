"""
evolution_guard.py — 免疫审查模块

审查新技能的安全性和合理性，防止危险技能自动激活。
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from backend.skill_memory import SkillTemplate, SkillStatus
from backend.plugin_manager import PluginManager, SafeLevel


class ReviewStatus(StrEnum):
    """审查状态"""
    PENDING = "pending"      # 待审查
    APPROVED = "approved"    # 已批准
    REJECTED = "rejected"    # 已拒绝
    NEEDS_INFO = "needs_info"  # 需要更多信息


class RiskLevel(StrEnum):
    """风险级别"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ReviewRule:
    """审查规则"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    description: str = ""
    check_type: str = ""  # keyword, plugin, agent, pattern
    check_value: str = ""
    risk_level: RiskLevel = RiskLevel.MEDIUM
    action: str = "flag"  # flag, block, require_approval
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "check_type": self.check_type,
            "check_value": self.check_value,
            "risk_level": self.risk_level.value,
            "action": self.action,
            "enabled": self.enabled,
        }


@dataclass
class SkillReview:
    """技能审查记录"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    skill_id: str = ""
    skill_name: str = ""
    status: ReviewStatus = ReviewStatus.PENDING
    risk_level: RiskLevel = RiskLevel.LOW

    # 审查详情
    triggered_rules: list[dict] = field(default_factory=list)
    risk_factors: list[str] = field(default_factory=list)
    safety_checks: list[dict] = field(default_factory=list)

    # 审查者信息
    reviewer: str | None = None
    reviewed_at: str | None = None
    review_notes: str = ""

    # 时间戳
    submitted_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # 自动审批建议
    auto_approve_suggestion: bool = False
    suggestion_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "status": self.status.value,
            "risk_level": self.risk_level.value,
            "triggered_rules": self.triggered_rules,
            "risk_factors": self.risk_factors,
            "safety_checks": self.safety_checks,
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at,
            "review_notes": self.review_notes,
            "submitted_at": self.submitted_at,
            "auto_approve_suggestion": self.auto_approve_suggestion,
            "suggestion_reason": self.suggestion_reason,
        }


class EvolutionGuard:
    """
    免疫审查器。
    审查新技能的安全性，防止危险技能自动激活。
    """

    def __init__(
        self,
        plugin_manager: PluginManager,
        storage_path: str | Path = "storage/reviews.json",
    ):
        self.plugin_manager = plugin_manager
        self.storage_path = Path(storage_path)
        self._rules: list[ReviewRule] = []
        self._reviews: list[SkillReview] = []
        self._load()
        self._init_default_rules()

    def _load(self) -> None:
        """从文件加载审查记录"""
        if not self.storage_path.exists():
            return

        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for rule_data in data.get("rules", []):
                self._rules.append(ReviewRule(
                    id=rule_data["id"],
                    name=rule_data["name"],
                    description=rule_data.get("description", ""),
                    check_type=rule_data["check_type"],
                    check_value=rule_data["check_value"],
                    risk_level=RiskLevel(rule_data.get("risk_level", "medium")),
                    action=rule_data.get("action", "flag"),
                    enabled=rule_data.get("enabled", True),
                ))

            for review_data in data.get("reviews", []):
                self._reviews.append(SkillReview(
                    id=review_data["id"],
                    skill_id=review_data["skill_id"],
                    skill_name=review_data["skill_name"],
                    status=ReviewStatus(review_data["status"]),
                    risk_level=RiskLevel(review_data.get("risk_level", "low")),
                    triggered_rules=review_data.get("triggered_rules", []),
                    risk_factors=review_data.get("risk_factors", []),
                    safety_checks=review_data.get("safety_checks", []),
                    reviewer=review_data.get("reviewer"),
                    reviewed_at=review_data.get("reviewed_at"),
                    review_notes=review_data.get("review_notes", ""),
                    submitted_at=review_data.get("submitted_at", datetime.now().isoformat()),
                ))
        except Exception:
            pass

    def _save(self) -> None:
        """保存审查记录到文件"""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": 1,
            "updated_at": datetime.now().isoformat(),
            "rules": [r.to_dict() for r in self._rules],
            "reviews": [r.to_dict() for r in self._reviews],
        }

        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _init_default_rules(self) -> None:
        """初始化默认审查规则"""
        if self._rules:  # 已有规则则跳过
            return

        default_rules = [
            ReviewRule(
                name="危险插件检查",
                description="检查技能是否使用高风险插件",
                check_type="plugin_risk",
                check_value="high",
                risk_level=RiskLevel.HIGH,
                action="require_approval",
            ),
            ReviewRule(
                name="未授权 Agent 检查",
                description="检查技能是否调用未授权的 Agent",
                check_type="agent_unauthorized",
                check_value="",
                risk_level=RiskLevel.MEDIUM,
                action="flag",
            ),
            ReviewRule(
                name="敏感关键词检查",
                description="检查技能描述是否包含敏感关键词",
                check_type="keyword",
                check_value="delete,remove,drop,truncate,格式化,删除,清空",
                risk_level=RiskLevel.HIGH,
                action="require_approval",
            ),
            ReviewRule(
                name="外部网络访问检查",
                description="检查技能是否访问外部网络",
                check_type="network_access",
                check_value="http,https,api,fetch",
                risk_level=RiskLevel.MEDIUM,
                action="flag",
            ),
            ReviewRule(
                name="文件系统写入检查",
                description="检查技能是否写入文件系统",
                check_type="file_write",
                check_value="write,save,export,保存,导出",
                risk_level=RiskLevel.LOW,
                action="flag",
            ),
            # 新增规则
            ReviewRule(
                name="系统命令执行检查",
                description="检查技能是否执行系统命令",
                check_type="keyword",
                check_value="exec,system,shell,command,subprocess,os.system,eval",
                risk_level=RiskLevel.CRITICAL,
                action="block",
            ),
            ReviewRule(
                name="环境变量访问检查",
                description="检查技能是否访问敏感环境变量",
                check_type="keyword",
                check_value="env,environment,secret,token,password,api_key",
                risk_level=RiskLevel.HIGH,
                action="require_approval",
            ),
            ReviewRule(
                name="递归深度检查",
                description="检查技能步骤是否过深（可能导致无限循环）",
                check_type="step_depth",
                check_value="10",
                risk_level=RiskLevel.MEDIUM,
                action="flag",
            ),
        ]

        self._rules.extend(default_rules)
        self._save()

    # ── 规则管理 ──

    def add_rule(self, rule: ReviewRule) -> ReviewRule:
        """添加审查规则"""
        self._rules.append(rule)
        self._save()
        return rule

    def get_rule(self, rule_id: str) -> ReviewRule | None:
        """获取规则"""
        for rule in self._rules:
            if rule.id == rule_id:
                return rule
        return None

    def list_rules(self, enabled_only: bool = True) -> list[ReviewRule]:
        """列出规则"""
        if enabled_only:
            return [r for r in self._rules if r.enabled]
        return list(self._rules)

    def update_rule(self, rule: ReviewRule) -> ReviewRule:
        """更新规则"""
        for i, r in enumerate(self._rules):
            if r.id == rule.id:
                self._rules[i] = rule
                self._save()
                return rule
        return rule

    def delete_rule(self, rule_id: str) -> bool:
        """删除规则"""
        for i, r in enumerate(self._rules):
            if r.id == rule_id:
                del self._rules[i]
                self._save()
                return True
        return False

    # ── 技能审查 ──

    def review_skill(self, skill: SkillTemplate) -> SkillReview:
        """审查技能"""
        review = SkillReview(
            skill_id=skill.id,
            skill_name=skill.name,
        )

        # 执行所有启用的规则检查
        for rule in self._rules:
            if not rule.enabled:
                continue

            triggered = self._check_rule(rule, skill)
            if triggered:
                review.triggered_rules.append(rule.to_dict())

                # 更新风险级别
                if rule.risk_level == RiskLevel.CRITICAL:
                    review.risk_level = RiskLevel.CRITICAL
                elif rule.risk_level == RiskLevel.HIGH and review.risk_level not in (RiskLevel.CRITICAL,):
                    review.risk_level = RiskLevel.HIGH
                elif rule.risk_level == RiskLevel.MEDIUM and review.risk_level == RiskLevel.LOW:
                    review.risk_level = RiskLevel.MEDIUM

        # 执行安全检查
        review.safety_checks = self._run_safety_checks(skill)

        # 确定最终状态
        if review.risk_level in (RiskLevel.CRITICAL, RiskLevel.HIGH):
            review.status = ReviewStatus.PENDING
        elif review.risk_level == RiskLevel.MEDIUM:
            review.status = ReviewStatus.PENDING
        else:
            review.status = ReviewStatus.APPROVED

        # 检查是否有阻断规则
        for rule in review.triggered_rules:
            if rule.get("action") == "block":
                review.status = ReviewStatus.REJECTED
                review.risk_factors.append(f"阻断规则触发: {rule['name']}")
                break

        # 自动生成审批建议
        review.auto_approve_suggestion, review.suggestion_reason = self._generate_approval_suggestion(review, skill)

        self._reviews.append(review)
        self._save()

        return review

    def _generate_approval_suggestion(
        self,
        review: SkillReview,
        skill: SkillTemplate,
    ) -> tuple[bool, str]:
        """生成自动审批建议"""
        # 低风险且无阻断规则 → 建议批准
        if review.risk_level == RiskLevel.LOW and not review.triggered_rules:
            return True, "低风险技能，无触发规则"

        # 中等风险但所有安全检查通过 → 建议批准
        if review.risk_level == RiskLevel.MEDIUM:
            all_checks_passed = all(
                check.get("passed", False) for check in review.safety_checks
            )
            if all_checks_passed and len(review.triggered_rules) <= 1:
                return True, "中等风险但安全检查全部通过"

        # 高风险 → 不建议自动批准
        if review.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            return False, "高风险技能需要人工审查"

        return False, "需要进一步评估"

    def _check_rule(self, rule: ReviewRule, skill: SkillTemplate) -> bool:
        """检查单个规则是否触发"""
        if rule.check_type == "keyword":
            keywords = rule.check_value.split(",")
            text = f"{skill.name} {skill.description}".lower()
            # 也检查步骤中的动作
            for step in skill.steps:
                text += f" {step.action}".lower()
            return any(kw.strip().lower() in text for kw in keywords)

        elif rule.check_type == "plugin_risk":
            for plugin_name in skill.required_plugins:
                plugin = self.plugin_manager.get_plugin_by_name(plugin_name)
                if plugin and plugin.safe_level.value == rule.check_value:
                    return True

        elif rule.check_type == "agent_unauthorized":
            for agent in skill.preferred_agents:
                if agent not in ["openclaw", "hermes", "openhanako", "auto"]:
                    return True

        elif rule.check_type == "network_access":
            keywords = rule.check_value.split(",")
            text = f"{skill.name} {skill.description}".lower()
            for step in skill.steps:
                text += f" {step.action}".lower()
            return any(kw.strip().lower() in text for kw in keywords)

        elif rule.check_type == "file_write":
            keywords = rule.check_value.split(",")
            for step in skill.steps:
                if any(kw.strip().lower() in step.action.lower() for kw in keywords):
                    return True

        elif rule.check_type == "step_depth":
            max_depth = int(rule.check_value)
            return len(skill.steps) > max_depth

        return False

    def _run_safety_checks(self, skill: SkillTemplate) -> list[dict]:
        """执行安全检查"""
        checks = []

        # 检查 1: 插件是否都可用
        for plugin_name in skill.required_plugins:
            plugin = self.plugin_manager.get_plugin_by_name(plugin_name)
            if not plugin:
                checks.append({
                    "check": "plugin_availability",
                    "plugin": plugin_name,
                    "passed": False,
                    "message": f"插件 {plugin_name} 未注册",
                })
            elif plugin.status.value != "active":
                checks.append({
                    "check": "plugin_availability",
                    "plugin": plugin_name,
                    "passed": False,
                    "message": f"插件 {plugin_name} 状态异常: {plugin.status.value}",
                })
            else:
                checks.append({
                    "check": "plugin_availability",
                    "plugin": plugin_name,
                    "passed": True,
                    "message": f"插件 {plugin_name} 可用",
                })

        # 检查 2: Agent 权限
        for agent in skill.preferred_agents:
            # 检查插件是否允许此 Agent
            for plugin_name in skill.required_plugins:
                plugin = self.plugin_manager.get_plugin_by_name(plugin_name)
                if plugin and plugin.allowed_agents:
                    if agent not in plugin.allowed_agents:
                        checks.append({
                            "check": "agent_permission",
                            "agent": agent,
                            "plugin": plugin_name,
                            "passed": False,
                            "message": f"Agent {agent} 未被允许使用插件 {plugin_name}",
                        })
                    else:
                        checks.append({
                            "check": "agent_permission",
                            "agent": agent,
                            "plugin": plugin_name,
                            "passed": True,
                            "message": f"Agent {agent} 有权使用插件 {plugin_name}",
                        })

        return checks

    # ── 审查决策 ──

    def approve_skill(
        self,
        review_id: str,
        reviewer: str = "admin",
        notes: str = "",
    ) -> SkillReview | None:
        """批准技能"""
        for review in self._reviews:
            if review.id == review_id:
                review.status = ReviewStatus.APPROVED
                review.reviewer = reviewer
                review.reviewed_at = datetime.now().isoformat()
                review.review_notes = notes
                self._save()
                return review
        return None

    def reject_skill(
        self,
        review_id: str,
        reviewer: str = "admin",
        notes: str = "",
    ) -> SkillReview | None:
        """拒绝技能"""
        for review in self._reviews:
            if review.id == review_id:
                review.status = ReviewStatus.REJECTED
                review.reviewer = reviewer
                review.reviewed_at = datetime.now().isoformat()
                review.review_notes = notes
                self._save()
                return review
        return None

    def request_info(
        self,
        review_id: str,
        reviewer: str = "admin",
        notes: str = "",
    ) -> SkillReview | None:
        """请求更多信息"""
        for review in self._reviews:
            if review.id == review_id:
                review.status = ReviewStatus.NEEDS_INFO
                review.reviewer = reviewer
                review.reviewed_at = datetime.now().isoformat()
                review.review_notes = notes
                self._save()
                return review
        return None

    # ── 批量操作 ──

    def batch_approve(
        self,
        review_ids: list[str],
        reviewer: str = "admin",
        notes: str = "",
    ) -> list[SkillReview]:
        """批量批准技能"""
        results = []
        for review_id in review_ids:
            review = self.approve_skill(review_id, reviewer, notes)
            if review:
                results.append(review)
        return results

    def batch_reject(
        self,
        review_ids: list[str],
        reviewer: str = "admin",
        notes: str = "",
    ) -> list[SkillReview]:
        """批量拒绝技能"""
        results = []
        for review_id in review_ids:
            review = self.reject_skill(review_id, reviewer, notes)
            if review:
                results.append(review)
        return results

    def auto_approve_suggestions(self) -> list[SkillReview]:
        """自动批准建议的低风险技能"""
        results = []
        for review in self._reviews:
            if review.status == ReviewStatus.PENDING and review.auto_approve_suggestion:
                review.status = ReviewStatus.APPROVED
                review.reviewer = "auto_system"
                review.reviewed_at = datetime.now().isoformat()
                review.review_notes = f"自动批准: {review.suggestion_reason}"
                results.append(review)
        if results:
            self._save()
        return results

    # ── 查询 ──

    def get_review(self, review_id: str) -> SkillReview | None:
        """获取审查记录"""
        for review in self._reviews:
            if review.id == review_id:
                return review
        return None

    def list_reviews(
        self,
        status: ReviewStatus | None = None,
        limit: int = 50,
    ) -> list[SkillReview]:
        """列出审查记录"""
        reviews = list(self._reviews)

        if status:
            reviews = [r for r in reviews if r.status == status]

        # 按提交时间倒序
        reviews.sort(key=lambda r: r.submitted_at, reverse=True)

        return reviews[:limit]

    def get_pending_reviews(self) -> list[SkillReview]:
        """获取待审查列表"""
        return self.list_reviews(status=ReviewStatus.PENDING)

    # ── 统计 ──

    def get_stats(self) -> dict:
        """获取审查统计"""
        pending = len([r for r in self._reviews if r.status == ReviewStatus.PENDING])
        approved = len([r for r in self._reviews if r.status == ReviewStatus.APPROVED])
        rejected = len([r for r in self._reviews if r.status == ReviewStatus.REJECTED])
        auto_approved = len([
            r for r in self._reviews
            if r.status == ReviewStatus.APPROVED and r.reviewer == "auto_system"
        ])

        return {
            "total_reviews": len(self._reviews),
            "pending": pending,
            "approved": approved,
            "rejected": rejected,
            "auto_approved": auto_approved,
            "total_rules": len([r for r in self._rules if r.enabled]),
            "risk_distribution": {
                "low": len([r for r in self._reviews if r.risk_level == RiskLevel.LOW]),
                "medium": len([r for r in self._reviews if r.risk_level == RiskLevel.MEDIUM]),
                "high": len([r for r in self._reviews if r.risk_level == RiskLevel.HIGH]),
                "critical": len([r for r in self._reviews if r.risk_level == RiskLevel.CRITICAL]),
            },
            "suggestion_stats": {
                "total_with_suggestion": len([
                    r for r in self._reviews if r.auto_approve_suggestion
                ]),
                "pending_with_suggestion": len([
                    r for r in self._reviews
                    if r.status == ReviewStatus.PENDING and r.auto_approve_suggestion
                ]),
            },
        }


def build_evolution_guard_from_env(plugin_manager: PluginManager) -> EvolutionGuard:
    """从环境变量构建免疫审查器"""
    storage_path = os.getenv("REVIEW_STORAGE_PATH", "storage/reviews.json")
    return EvolutionGuard(plugin_manager=plugin_manager, storage_path=storage_path)


import os
