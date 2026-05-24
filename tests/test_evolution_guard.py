"""Tests for evolution_guard module"""

import pytest
import tempfile
import os

from backend.evolution_guard import (
    EvolutionGuard,
    ReviewRule,
    ReviewStatus,
    RiskLevel,
)
from backend.plugin_manager import PluginManager, PluginRecord, PluginCapability, SafeLevel
from backend.skill_memory import SkillTemplate, SkillStep


class TestEvolutionGuard:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.plugin_storage = os.path.join(self.temp_dir, "test_plugins.json")
        self.review_storage = os.path.join(self.temp_dir, "test_reviews.json")

        self.plugin_manager = PluginManager(storage_path=self.plugin_storage)
        self.guard = EvolutionGuard(
            plugin_manager=self.plugin_manager,
            storage_path=self.review_storage,
        )

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_default_rules_loaded(self):
        rules = self.guard.list_rules()
        assert len(rules) > 0

    def test_add_rule(self):
        rule = ReviewRule(
            name="custom_rule",
            check_type="keyword",
            check_value="dangerous",
            risk_level=RiskLevel.HIGH,
            action="block",
        )

        created = self.guard.add_rule(rule)
        assert created.name == "custom_rule"

    def test_review_skill_safe(self):
        skill = SkillTemplate(
            name="safe_skill",
            description="A safe skill for data processing",
            steps=[SkillStep(step_id=1, action="process data", agent="openclaw")],
        )

        review = self.guard.review_skill(skill)
        assert review.status == ReviewStatus.APPROVED
        assert review.risk_level == RiskLevel.LOW

    def test_review_skill_with_keywords(self):
        skill = SkillTemplate(
            name="dangerous_skill",
            description="This skill will delete all files",
        )

        review = self.guard.review_skill(skill)
        # 应该触发敏感关键词规则
        assert len(review.triggered_rules) > 0
        assert review.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH)

    def test_review_skill_with_high_risk_plugin(self):
        # 注册一个高风险插件
        plugin = PluginRecord(
            name="dangerous_plugin",
            safe_level=SafeLevel.HIGH,
        )
        self.plugin_manager.register_plugin(plugin)

        skill = SkillTemplate(
            name="plugin_skill",
            required_plugins=["dangerous_plugin"],
        )

        review = self.guard.review_skill(skill)
        assert review.risk_level == RiskLevel.HIGH

    def test_approve_skill(self):
        skill = SkillTemplate(name="test_skill")
        review = self.guard.review_skill(skill)

        approved = self.guard.approve_skill(review.id, reviewer="admin", notes="Looks good")
        assert approved.status == ReviewStatus.APPROVED
        assert approved.reviewer == "admin"

    def test_reject_skill(self):
        skill = SkillTemplate(name="test_skill")
        review = self.guard.review_skill(skill)

        rejected = self.guard.reject_skill(review.id, reviewer="admin", notes="Too risky")
        assert rejected.status == ReviewStatus.REJECTED

    def test_pending_reviews(self):
        # 创建一个会触发规则的技能
        skill = SkillTemplate(
            name="needs_review",
            description="This will delete data",
        )
        self.guard.review_skill(skill)

        pending = self.guard.get_pending_reviews()
        assert len(pending) > 0

    def test_get_stats(self):
        skill = SkillTemplate(name="test")
        self.guard.review_skill(skill)

        stats = self.guard.get_stats()
        assert stats["total_reviews"] >= 1
        assert "pending" in stats
        assert "approved" in stats

    def test_persistence(self):
        skill = SkillTemplate(name="persistent_skill")
        self.guard.review_skill(skill)

        new_guard = EvolutionGuard(
            plugin_manager=self.plugin_manager,
            storage_path=self.review_storage,
        )

        reviews = new_guard.list_reviews()
        assert len(reviews) > 0

    def test_list_rules(self):
        rules = self.guard.list_rules()
        assert len(rules) > 0

        # 测试只获取启用的规则
        all_rules = self.guard.list_rules(enabled_only=False)
        assert len(all_rules) >= len(rules)

    def test_auto_approval_suggestion(self):
        """测试自动审批建议"""
        skill = SkillTemplate(
            name="safe_skill",
            description="A safe skill for data processing",
            steps=[SkillStep(step_id=1, action="process data", agent="openclaw")],
        )

        review = self.guard.review_skill(skill)
        # 低风险技能应该有自动审批建议
        assert review.auto_approve_suggestion is True
        assert "低风险" in review.suggestion_reason

    def test_auto_approve_suggestions(self):
        """测试批量自动批准"""
        # 创建一个低风险技能
        skill = SkillTemplate(
            name="safe_skill",
            description="A safe skill",
        )
        self.guard.review_skill(skill)

        # 获取待审查列表
        pending = self.guard.get_pending_reviews()
        # 低风险技能应该被自动批准
        auto_approved = self.guard.auto_approve_suggestions()
        # 检查是否有被自动批准的
        assert isinstance(auto_approved, list)

    def test_batch_approve(self):
        """测试批量批准"""
        # 创建多个技能
        skill1 = SkillTemplate(name="skill1")
        skill2 = SkillTemplate(name="skill2")
        review1 = self.guard.review_skill(skill1)
        review2 = self.guard.review_skill(skill2)

        # 批量批准
        results = self.guard.batch_approve([review1.id, review2.id], notes="Batch approve")
        assert len(results) == 2
        assert all(r.status == ReviewStatus.APPROVED for r in results)

    def test_batch_reject(self):
        """测试批量拒绝"""
        skill1 = SkillTemplate(name="skill1")
        skill2 = SkillTemplate(name="skill2")
        review1 = self.guard.review_skill(skill1)
        review2 = self.guard.review_skill(skill2)

        results = self.guard.batch_reject([review1.id, review2.id], notes="Batch reject")
        assert len(results) == 2
        assert all(r.status == ReviewStatus.REJECTED for r in results)

    def test_system_command_rule(self):
        """测试系统命令执行规则"""
        skill = SkillTemplate(
            name="dangerous_skill",
            description="Execute system commands",
            steps=[SkillStep(step_id=1, action="exec rm -rf /", agent="openclaw")],
        )

        review = self.guard.review_skill(skill)
        # 应该触发系统命令执行规则
        assert review.risk_level == RiskLevel.CRITICAL

    def test_step_depth_rule(self):
        """测试递归深度规则"""
        # 创建一个步骤过多的技能
        steps = [
            SkillStep(step_id=i, action=f"step {i}", agent="openclaw")
            for i in range(1, 15)  # 超过默认限制 10
        ]
        skill = SkillTemplate(
            name="deep_skill",
            steps=steps,
        )

        review = self.guard.review_skill(skill)
        # 应该触发递归深度规则
        assert len(review.triggered_rules) > 0

    def test_stats_with_suggestions(self):
        """测试包含建议统计的统计信息"""
        skill = SkillTemplate(name="test_skill")
        self.guard.review_skill(skill)

        stats = self.guard.get_stats()
        assert "auto_approved" in stats
        assert "suggestion_stats" in stats
        assert "total_with_suggestion" in stats["suggestion_stats"]
