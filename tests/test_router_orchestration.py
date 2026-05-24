import asyncio
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.core.router import AgentRouter, RoutingDecision
from backend.core.task_schema import AgentTask, AgentResult
from backend.core.base_adapter import BaseAgentAdapter
from backend.orchestration.execution_plan import ExecutionPlan, ExecutionMode
from backend.orchestration.orchestrator import MultiAgentOrchestrator
from backend.orchestration.aggregator import ResultAggregator
from backend.adapters.openclaw_adapter import OpenClawAdapter
from backend.adapters.openhanako_adapter import OpenHanakoAdapter
from backend.adapters.hermes_adapter import HermesAdapter


class MockAdapter(BaseAgentAdapter):
    agent_name = "mock_agent"
    agent_type = "test_agent"
    capabilities = ["test"]

    def can_handle(self, task: AgentTask) -> float:
        return 0.5

    def run(self, task: AgentTask) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_name=self.agent_name,
            status="completed",
            result=f"mock handled: {task.content}",
        )


class FailingAdapter(BaseAgentAdapter):
    agent_name = "fail_agent"
    agent_type = "test_agent"
    capabilities = ["test"]

    def can_handle(self, task: AgentTask) -> float:
        return 0.8

    def run(self, task: AgentTask) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_name=self.agent_name,
            status="failed",
            result="",
            error="always fails",
        )


def _make_task(content="test task", task_type="general"):
    return AgentTask(
        task_id="test_001",
        user_id="test_user",
        source="test",
        content=content,
        task_type=task_type,
    )


class TestAgentRouter:
    def test_register_and_get_agent(self):
        router = AgentRouter()
        adapter = MockAdapter()
        router.register(adapter)
        assert router.get_agent("mock_agent") is not None
        assert router.get_agent("nonexistent") is None

    def test_list_agents(self):
        router = AgentRouter()
        router.register(MockAdapter())
        agents = router.list_agents()
        assert len(agents) == 1
        assert agents[0]["agent_name"] == "mock_agent"

    def test_unregister(self):
        router = AgentRouter()
        router.register(MockAdapter())
        assert router.unregister("mock_agent") is True
        assert router.get_agent("mock_agent") is None
        assert router.unregister("mock_agent") is False

    def test_route_with_decision(self):
        router = AgentRouter()
        router.register(OpenClawAdapter())
        router.register(OpenHanakoAdapter())
        router.register(HermesAdapter())

        task = _make_task("fix this bug", "code_repair")
        decision = router.route_with_decision(task)
        assert isinstance(decision, RoutingDecision)
        assert decision.selected_agent in ("openclaw", "hanako", "hermes")
        assert decision.score > 0
        assert decision.confidence in ("high", "medium", "low")
        assert len(decision.reasons) > 0

    def test_dispatch_success(self):
        router = AgentRouter()
        router.register(OpenClawAdapter())
        task = _make_task("fix bug")
        result = router.dispatch(task)
        assert result.status == "completed"
        assert result.agent_name == "openclaw"

    def test_dispatch_no_agents(self):
        router = AgentRouter()
        task = _make_task("test")
        result = router.dispatch(task)
        assert result.status == "failed"
        assert result.agent_name == "router"

    def test_dispatch_fallback(self):
        router = AgentRouter()
        router.register(FailingAdapter())
        router.register(MockAdapter())
        task = _make_task("test")
        result = router.dispatch(task)
        assert result.status == "completed"
        assert result.metadata.get("fallback_from") == "fail_agent"

    def test_get_stats(self):
        router = AgentRouter()
        router.register(MockAdapter())
        stats = router.get_stats()
        assert stats["total_agents"] == 1
        assert stats["enabled_agents"] == 1

    def test_get_history(self):
        router = AgentRouter()
        router.register(MockAdapter())
        task = _make_task("test")
        router.dispatch(task)
        history = router.get_history()
        assert len(history) == 1
        assert history[0]["agent_name"] == "mock_agent"


class TestAdapters:
    def test_openclaw_mock_mode(self):
        adapter = OpenClawAdapter()
        task = _make_task("fix bug", "code_repair")
        result = adapter.run(task)
        assert result.status == "completed"
        assert "OpenClaw" in result.result

    def test_hanako_mock_mode(self):
        adapter = OpenHanakoAdapter()
        task = _make_task("chat with me", "chat")
        result = adapter.run(task)
        assert result.status == "completed"
        assert "Hanako" in result.result

    def test_hermes_mock_mode(self):
        adapter = HermesAdapter()
        task = _make_task("plan project", "long_task")
        result = adapter.run(task)
        assert result.status == "completed"
        assert "Hermes" in result.result

    def test_openclaw_can_handle(self):
        adapter = OpenClawAdapter()
        task = _make_task("fix bug", "code_repair")
        score = adapter.can_handle(task)
        assert score >= 0.7

    def test_hanako_can_handle(self):
        adapter = OpenHanakoAdapter()
        task = _make_task("chat", "chat")
        score = adapter.can_handle(task)
        assert score >= 0.9

    def test_hermes_can_handle(self):
        adapter = HermesAdapter()
        task = _make_task("project architecture", "architecture_planning")
        score = adapter.can_handle(task)
        assert score >= 0.9

    def test_health_check_mock(self):
        for Adapter in (OpenClawAdapter, OpenHanakoAdapter, HermesAdapter):
            adapter = Adapter()
            health = adapter.health_check()
            assert health["status"] == "ok"


class TestOrchestrator:
    def _make_orchestrator(self):
        router = AgentRouter()
        router.register(OpenClawAdapter())
        router.register(OpenHanakoAdapter())
        router.register(HermesAdapter())
        aggregator = ResultAggregator()
        return MultiAgentOrchestrator(router, aggregator)

    @pytest.mark.asyncio
    async def test_single_execution(self):
        orch = self._make_orchestrator()
        plan = ExecutionPlan.single("test_single", "openclaw", "fix bug")
        result = await orch.execute(plan)
        assert result.status == "completed"
        assert len(result.step_results) == 1

    @pytest.mark.asyncio
    async def test_pipeline_execution(self):
        orch = self._make_orchestrator()
        plan = ExecutionPlan.pipeline("test_pipeline", "analyze and summarize", [
            ("hermes", "analyze the project"),
            ("hanako", "rewrite in friendly tone"),
        ])
        result = await orch.execute(plan)
        assert result.status == "completed"
        assert len(result.step_results) == 2

    @pytest.mark.asyncio
    async def test_parallel_execution(self):
        orch = self._make_orchestrator()
        plan = ExecutionPlan.parallel("test_parallel", "full check", [
            ("openclaw", "check code"),
            ("hermes", "analyze roadmap"),
            ("hanako", "make friendly"),
        ])
        result = await orch.execute(plan)
        assert result.status == "completed"
        assert len(result.step_results) == 3

    @pytest.mark.asyncio
    async def test_agent_not_found(self):
        orch = self._make_orchestrator()
        plan = ExecutionPlan.single("test_missing", "nonexistent_agent", "test")
        result = await orch.execute(plan)
        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_create_plan_from_task(self):
        orch = self._make_orchestrator()
        plan = orch.create_plan_from_task("fix this bug", mode=ExecutionMode.SINGLE)
        assert plan.mode == ExecutionMode.SINGLE
        assert plan.steps[0].agent == "openclaw"

    @pytest.mark.asyncio
    async def test_get_stats(self):
        orch = self._make_orchestrator()
        plan = ExecutionPlan.single("test_stats", "openclaw", "test")
        await orch.execute(plan)
        stats = orch.get_stats()
        assert stats["total"] == 1
        assert stats["completed"] == 1


class TestExecutionPlan:
    def test_single_plan(self):
        plan = ExecutionPlan.single("p1", "openclaw", "fix bug")
        assert plan.mode == ExecutionMode.SINGLE
        assert len(plan.steps) == 1
        assert plan.steps[0].agent == "openclaw"

    def test_pipeline_plan(self):
        plan = ExecutionPlan.pipeline("p2", "analyze", [
            ("hermes", "step1"),
            ("hanako", "step2"),
        ])
        assert plan.mode == ExecutionMode.PIPELINE
        assert len(plan.steps) == 2

    def test_parallel_plan(self):
        plan = ExecutionPlan.parallel("p3", "check", [
            ("openclaw", "step1"),
            ("hermes", "step2"),
        ])
        assert plan.mode == ExecutionMode.PARALLEL
        assert len(plan.steps) == 2

    def test_add_step(self):
        plan = ExecutionPlan.single("p4", "openclaw", "test")
        plan.add_step("hanako", "follow up")
        assert len(plan.steps) == 2

    def test_to_dict(self):
        plan = ExecutionPlan.single("p5", "openclaw", "test")
        d = plan.to_dict()
        assert d["plan_id"] == "p5"
        assert d["mode"] == "single"
