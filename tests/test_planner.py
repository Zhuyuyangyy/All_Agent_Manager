"""Tests for task_planner module"""

import pytest

from backend.models import AgentChoice
from backend.project_discovery import DiscoveredTask, TaskPriority, TaskType
from backend.task_planner import ExecutionPlan, PlanMode, TaskPlanner


class TestTaskPlanner:
    def setup_method(self):
        self.planner = TaskPlanner(mode=PlanMode.RULES)

    def test_simple_task_no_split(self):
        plan = self.planner.plan("修复登录页面的 bug")

        assert len(plan.sub_tasks) == 1
        assert plan.sub_tasks[0].agent == AgentChoice.OPENCLAW
        assert plan.metadata["needs_split"] is False

    def test_complex_task_with_split(self):
        plan = self.planner.plan(
            "重构用户认证模块，添加 OAuth 支持，并更新 API 文档"
        )

        assert len(plan.sub_tasks) > 1
        assert plan.metadata["needs_split"] is True

    def test_agent_routing_code_task(self):
        plan = self.planner.plan("写一个 Python 脚本处理 CSV 文件")
        assert plan.sub_tasks[0].agent == AgentChoice.OPENCLAW

    def test_agent_routing_research_task(self):
        plan = self.planner.plan("调研最新的 AI 框架并做分析报告")
        assert plan.sub_tasks[0].agent == AgentChoice.HERMES

    def test_agent_routing_wechat_task(self):
        plan = self.planner.plan("发送微信消息给用户")
        assert plan.sub_tasks[0].agent == AgentChoice.OPENHANAKO

    def test_priority_detection_urgent(self):
        plan = self.planner.plan("紧急修复生产环境的 bug")
        assert plan.sub_tasks[0].priority == TaskPriority.URGENT

    def test_priority_detection_high(self):
        plan = self.planner.plan("重要功能：实现支付模块")
        assert plan.sub_tasks[0].priority == TaskPriority.HIGH

    def test_plan_from_discovered_task(self):
        task = DiscoveredTask(
            id="test_1",
            goal="实现用户注册功能",
            source="file_scanner",
            task_type=TaskType.FEATURE,
            priority=TaskPriority.HIGH,
        )

        plan = self.planner.plan_from_discovered(task)
        assert plan.original_goal == "实现用户注册功能"
        assert plan.sub_tasks[0].agent == AgentChoice.OPENCLAW

    def test_agent_stats_update(self):
        self.planner.update_agent_stats(AgentChoice.OPENCLAW, success=True, duration=10.0)
        self.planner.update_agent_stats(AgentChoice.OPENCLAW, success=True, duration=20.0)
        self.planner.update_agent_stats(AgentChoice.OPENCLAW, success=False)

        stats = self.planner.get_agent_stats()
        assert stats["openclaw"]["completed"] == 2
        assert stats["openclaw"]["failed"] == 1
        assert stats["openclaw"]["avg_time"] == 15.0

    def test_plan_history(self):
        self.planner.plan("任务1")
        self.planner.plan("任务2")

        history = self.planner.get_plan_history()
        assert len(history) == 2
        assert history[0]["original_goal"] == "任务1"

    def test_complexity_analysis(self):
        # 简单任务
        assert self.planner._analyze_complexity("修复 bug") == "low"

        # 复杂任务
        assert self.planner._analyze_complexity("整个项目的重构和迁移") == "high"

    def test_needs_splitting(self):
        assert self.planner._needs_splitting("简单任务", "low") is False
        assert self.planner._needs_splitting("复杂任务", "high") is True
        assert self.planner._needs_splitting("任务A，然后任务B", "medium") is True
