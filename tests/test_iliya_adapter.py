import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.models import AgentChoice, RoutingDecision
from backend.scheduler import route_task
from backend.command_safety import is_command_safe, BLOCKED_COMMANDS
from backend.core.task_schema import AgentTask, AgentResult
from backend.core.base_adapter import BaseAgentAdapter
from backend.core.router import AgentRouter
from backend.adapters.iliya_adapter import IliyaAdapter
from backend.adapters.openclaw_adapter import OpenClawAdapter
from backend.adapters.openhanako_adapter import OpenHanakoAdapter
from backend.adapters.hermes_adapter import HermesAdapter
from backend.workers import DemoWorkerClient, RoutingWorkerClient
from backend.orchestration.execution_plan import ExecutionPlan, ExecutionMode
from backend.orchestration.orchestrator import MultiAgentOrchestrator
from backend.orchestration.aggregator import ResultAggregator


def _make_task(content="test task", task_type="general", context=None):
    return AgentTask(
        task_id="test_001",
        user_id="test_user",
        source="test",
        content=content,
        task_type=task_type,
        context=context or {},
    )


# ══════════════════════════════════════════════════════════
#  1. command_safety 模块
# ══════════════════════════════════════════════════════════

class TestCommandSafety:
    def test_safe_commands_pass(self):
        safe, reason = is_command_safe("dir")
        assert safe is True
        assert reason == ""

    def test_safe_commands_python(self):
        safe, reason = is_command_safe("python --version")
        assert safe is True

    def test_safe_commands_echo(self):
        safe, reason = is_command_safe("echo hello")
        assert safe is True

    def test_blocked_rm(self):
        safe, reason = is_command_safe("rm -rf /")
        assert safe is False
        assert "rm" in reason

    def test_blocked_shutdown(self):
        safe, reason = is_command_safe("shutdown /s")
        assert safe is False

    def test_blocked_format(self):
        safe, reason = is_command_safe("format C:")
        assert safe is False

    def test_blocked_taskkill(self):
        safe, reason = is_command_safe("taskkill /F /PID 123")
        assert safe is False

    def test_blocked_reg(self):
        safe, reason = is_command_safe("reg add HKLM\\Software\\Test")
        assert safe is False

    def test_blocked_with_path_separator(self):
        safe, reason = is_command_safe("some\\rm file")
        assert safe is False

    def test_blocked_with_slash(self):
        safe, reason = is_command_safe("/rm file")
        assert safe is False


# ══════════════════════════════════════════════════════════
#  2. IliyaAdapter 标准接口
# ══════════════════════════════════════════════════════════

class TestIliyaAdapterBasic:
    def test_inherits_base_adapter(self):
        adapter = IliyaAdapter()
        assert isinstance(adapter, BaseAgentAdapter)

    def test_agent_name(self):
        adapter = IliyaAdapter()
        assert adapter.agent_name == "iliya"

    def test_agent_type(self):
        adapter = IliyaAdapter()
        assert adapter.agent_type == "orchestrator_agent"

    def test_capabilities(self):
        adapter = IliyaAdapter()
        caps = adapter.get_capabilities()
        assert "intent_recognition" in caps
        assert "command_execution" in caps
        assert "file_operation" in caps
        assert "agent_routing" in caps
        assert "skill_management" in caps
        assert len(caps) == 10

    def test_supports_capability(self):
        adapter = IliyaAdapter()
        assert adapter.supports_capability("command_execution") is True
        assert adapter.supports_capability("nonexistent") is False

    def test_health_check(self):
        adapter = IliyaAdapter()
        health = adapter.health_check()
        assert health["status"] == "ok"
        assert health["agent_name"] == "iliya"
        assert health["shell_enabled"] is False
        assert "capabilities_count" in health

    def test_get_snapshot(self):
        adapter = IliyaAdapter()
        snap = adapter.get_snapshot()
        assert snap["agent_id"] == "iliya"
        assert snap["status"] == "idle"
        assert snap["capabilities"] == adapter.capabilities

    def test_to_dict(self):
        adapter = IliyaAdapter()
        d = adapter.to_dict()
        assert d["agent_name"] == "iliya"
        assert d["agent_type"] == "orchestrator_agent"
        assert d["enabled"] is True

    def test_heartbeat(self):
        adapter = IliyaAdapter()
        old_hb = adapter.last_heartbeat
        import time
        time.sleep(0.01)
        adapter.heartbeat()
        assert adapter.last_heartbeat > old_hb

    def test_normalize_input(self):
        adapter = IliyaAdapter()
        task = _make_task("hello", "general", {"key": "val"})
        result = adapter.normalize_input(task)
        assert result["task_id"] == "test_001"
        assert result["content"] == "hello"
        assert result["task_type"] == "general"
        assert result["context"] == {"key": "val"}

    def test_normalize_output(self):
        adapter = IliyaAdapter()
        task = _make_task()
        result = adapter.normalize_output(task, "raw output")
        assert result.task_id == "test_001"
        assert result.agent_name == "iliya"
        assert result.status == "completed"
        assert result.result == "raw output"


# ══════════════════════════════════════════════════════════
#  3. IliyaAdapter can_handle 路由评分
# ══════════════════════════════════════════════════════════

class TestIliyaAdapterCanHandle:
    def test_capability_match_high_score(self):
        adapter = IliyaAdapter()
        task = _make_task("test", "command_execution")
        score = adapter.can_handle(task)
        assert score == 0.95

    def test_intent_recognition_match(self):
        adapter = IliyaAdapter()
        task = _make_task("test", "intent_recognition")
        score = adapter.can_handle(task)
        assert score == 0.95

    def test_keyword_dispatch(self):
        adapter = IliyaAdapter()
        task = _make_task("调度任务到 openclaw")
        score = adapter.can_handle(task)
        assert score >= 0.65

    def test_keyword_iliya(self):
        adapter = IliyaAdapter()
        task = _make_task("iliya 帮我执行命令")
        score = adapter.can_handle(task)
        assert score >= 0.65

    def test_keyword_multiple(self):
        adapter = IliyaAdapter()
        task = _make_task("调度分发编排任务")
        score = adapter.can_handle(task)
        assert score >= 0.80

    def test_dispatched_task_type(self):
        adapter = IliyaAdapter()
        task = _make_task("some task", "dispatched")
        score = adapter.can_handle(task)
        assert score == 0.70

    def test_low_score_for_unrelated(self):
        adapter = IliyaAdapter()
        task = _make_task("fix the bug in the code")
        score = adapter.can_handle(task)
        assert score <= 0.20


# ══════════════════════════════════════════════════════════
#  4. IliyaAdapter 命令执行
# ══════════════════════════════════════════════════════════

class TestIliyaAdapterCommandExecution:
    def test_command_execution_disabled_by_default(self):
        adapter = IliyaAdapter()
        task = _make_task("dir", "command_execution", {"action": "execute", "command": "dir"})
        result = adapter.run(task)
        assert result.status == "failed"
        assert "未启用" in result.error

    def test_command_execution_with_allow_shell(self):
        adapter = IliyaAdapter(config={"allow_shell": True})
        task = _make_task("echo hello", "command_execution", {"action": "execute", "command": "echo hello"})
        result = adapter.run(task)
        assert result.status == "completed"
        assert "hello" in result.result

    def test_command_execution_blocked_command(self):
        adapter = IliyaAdapter(config={"allow_shell": True})
        task = _make_task("rm -rf /", "command_execution", {"action": "execute", "command": "rm -rf /"})
        result = adapter.run(task)
        assert result.status == "failed"
        assert "安全策略" in result.error

    def test_command_execution_with_force(self):
        adapter = IliyaAdapter()
        task = _make_task("echo test", "command_execution", {"action": "execute", "command": "echo test", "force": True})
        result = adapter.run(task)
        assert result.status == "completed"
        assert "test" in result.result

    def test_command_execution_timeout(self):
        adapter = IliyaAdapter(config={"allow_shell": True})
        python_exe = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".venv", "Scripts", "python.exe")
        if not os.path.exists(python_exe):
            python_exe = sys.executable
        task = _make_task("long sleep", "command_execution", {"action": "execute", "command": f'"{python_exe}" -c "import time; time.sleep(30)"', "timeout": 1})
        result = adapter.run(task)
        assert result.status == "failed"
        assert "超时" in result.error or "timed out" in result.error.lower() or "timeout" in result.error.lower()

    def test_command_execution_return_code(self):
        adapter = IliyaAdapter(config={"allow_shell": True})
        task = _make_task("exit 1", "command_execution", {"action": "execute", "command": "exit 1"})
        result = adapter.run(task)
        assert result.status == "failed"
        assert result.metadata.get("return_code") == 1

    @pytest.mark.asyncio
    async def test_command_execution_async(self):
        adapter = IliyaAdapter(config={"allow_shell": True})
        task = _make_task("echo async", "command_execution", {"action": "execute", "command": "echo async"})
        result = await adapter.run_async(task)
        assert result.status == "completed"
        assert "async" in result.result


# ══════════════════════════════════════════════════════════
#  5. IliyaAdapter 文件操作
# ══════════════════════════════════════════════════════════

class TestIliyaAdapterFileOperation:
    def test_file_read(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("hello world")
            tmp_path = f.name
        try:
            adapter = IliyaAdapter()
            task = _make_task(tmp_path, "file_operation", {"action": "read", "path": tmp_path})
            result = adapter.run(task)
            assert result.status == "completed"
            assert "hello world" in result.result
        finally:
            os.unlink(tmp_path)

    def test_file_read_not_found(self):
        adapter = IliyaAdapter()
        task = _make_task("/nonexistent/path", "file_operation", {"action": "read", "path": "/nonexistent/path"})
        result = adapter.run(task)
        assert result.status == "failed"
        assert "不存在" in result.error

    def test_file_write(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = os.path.join(tmp_dir, "test_write.txt")
            adapter = IliyaAdapter()
            task = _make_task("test content", "file_operation", {"action": "write", "path": tmp_path, "file_content": "test content"})
            result = adapter.run(task)
            assert result.status == "completed"
            assert "已写入" in result.result
            with open(tmp_path, encoding="utf-8") as f:
                assert f.read() == "test content"

    def test_file_list(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            Path(tmp_dir, "file1.txt").write_text("a", encoding="utf-8")
            Path(tmp_dir, "subdir").mkdir()
            adapter = IliyaAdapter()
            task = _make_task(tmp_dir, "file_operation", {"action": "list", "path": tmp_dir})
            result = adapter.run(task)
            assert result.status == "completed"
            assert "file1.txt" in result.result
            assert "subdir/" in result.result

    def test_file_list_not_found(self):
        adapter = IliyaAdapter()
        task = _make_task("/nonexistent/dir", "file_operation", {"action": "list", "path": "/nonexistent/dir"})
        result = adapter.run(task)
        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_file_operation_async(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("async read test")
            tmp_path = f.name
        try:
            adapter = IliyaAdapter()
            task = _make_task(tmp_path, "file_operation", {"action": "read", "path": tmp_path})
            result = await adapter.run_async(task)
            assert result.status == "completed"
            assert "async read test" in result.result
        finally:
            os.unlink(tmp_path)


# ══════════════════════════════════════════════════════════
#  6. IliyaAdapter 技能/路由管理
# ══════════════════════════════════════════════════════════

class TestIliyaAdapterManagement:
    def test_skill_management_without_wechat_agent(self):
        adapter = IliyaAdapter()
        task = _make_task("list skills", "skill_management", {"action": "skill"})
        result = adapter.run(task)
        assert result.status == "failed"
        assert "WeChatAgent" in result.error

    def test_agent_routing_with_target(self):
        adapter = IliyaAdapter()
        task = _make_task("fix bug", "agent_routing", {"action": "dispatch", "target_agent": "openclaw", "task_description": "fix bug"})
        result = adapter.run(task)
        assert result.status == "completed"
        assert "openclaw" in result.result
        assert result.metadata.get("routed") is True

    def test_agent_routing_without_target(self):
        adapter = IliyaAdapter()
        task = _make_task("some task", "agent_routing", {"action": "dispatch"})
        result = adapter.run(task)
        assert result.status == "completed"
        assert result.metadata.get("routed") is False

    def test_execute_interface(self):
        adapter = IliyaAdapter()
        result = asyncio.run(adapter.execute("test goal", {"action": "dispatch", "target_agent": "hermes"}))
        assert result["ok"] is True
        assert "hermes" in result["result"]


# ══════════════════════════════════════════════════════════
#  7. AgentChoice.ILIYA 枚举
# ══════════════════════════════════════════════════════════

class TestAgentChoiceIliya:
    def test_iliya_exists(self):
        assert AgentChoice.ILIYA == "iliya"

    def test_iliya_is_str(self):
        assert isinstance(AgentChoice.ILIYA, str)

    def test_iliya_in_enum(self):
        values = [a.value for a in AgentChoice]
        assert "iliya" in values


# ══════════════════════════════════════════════════════════
#  8. scheduler.py 路由
# ══════════════════════════════════════════════════════════

class TestSchedulerRouting:
    def test_route_to_iliya_dispatch_keyword(self):
        decision = route_task("调度任务到 openclaw", AgentChoice.AUTO)
        assert decision.selected_agent == AgentChoice.ILIYA

    def test_route_to_iliya_orchestrate_keyword(self):
        decision = route_task("orchestrate the pipeline", AgentChoice.AUTO)
        assert decision.selected_agent == AgentChoice.ILIYA

    def test_route_to_iliya_explicit(self):
        decision = route_task("some task", AgentChoice.ILIYA)
        assert decision.selected_agent == AgentChoice.ILIYA
        assert "explicit" in decision.routing_reason.lower()

    def test_route_to_openclaw_still_works(self):
        decision = route_task("fix the bug and implement the API", AgentChoice.AUTO)
        assert decision.selected_agent == AgentChoice.OPENCLAW

    def test_route_to_hermes_still_works(self):
        decision = route_task("research and summarize findings", AgentChoice.AUTO)
        assert decision.selected_agent == AgentChoice.HERMES

    def test_route_to_openhanako_still_works(self):
        decision = route_task("微信消息处理", AgentChoice.AUTO)
        assert decision.selected_agent == AgentChoice.OPENHANAKO

    def test_fallback_to_hermes(self):
        decision = route_task("help me with something", AgentChoice.AUTO)
        assert decision.selected_agent == AgentChoice.HERMES


# ══════════════════════════════════════════════════════════
#  9. AgentRouter 集成（含 iliya）
# ══════════════════════════════════════════════════════════

class TestRouterWithIliya:
    def test_register_iliya(self):
        router = AgentRouter()
        adapter = IliyaAdapter()
        router.register(adapter)
        assert router.get_agent("iliya") is not None

    def test_route_to_iliya_for_dispatch_task(self):
        router = AgentRouter()
        router.register(IliyaAdapter())
        router.register(OpenClawAdapter())
        router.register(OpenHanakoAdapter())
        router.register(HermesAdapter())

        task = _make_task("调度任务分发", "agent_routing")
        result = router.dispatch(task)
        assert result.agent_name == "iliya"
        assert result.status == "completed"

    def test_route_to_openclaw_for_code_task(self):
        router = AgentRouter()
        router.register(IliyaAdapter())
        router.register(OpenClawAdapter())
        router.register(OpenHanakoAdapter())
        router.register(HermesAdapter())

        task = _make_task("fix the bug in the code", "code_repair")
        result = router.dispatch(task)
        assert result.agent_name == "openclaw"

    def test_all_four_agents_registered(self):
        router = AgentRouter()
        router.register(IliyaAdapter())
        router.register(OpenClawAdapter())
        router.register(OpenHanakoAdapter())
        router.register(HermesAdapter())

        agents = router.list_agents()
        names = [a["agent_name"] for a in agents]
        assert "iliya" in names
        assert "openclaw" in names
        assert "hanako" in names
        assert "hermes" in names
        assert len(agents) == 4

    def test_iliya_route_with_decision(self):
        router = AgentRouter()
        router.register(IliyaAdapter())
        router.register(OpenClawAdapter())

        task = _make_task("调度分发任务", "agent_routing")
        decision = router.route_with_decision(task)
        assert decision.selected_agent == "iliya"
        assert decision.score > 0


# ══════════════════════════════════════════════════════════
#  10. Workers 集成（含 ILIYA）
# ══════════════════════════════════════════════════════════

class TestWorkersWithIliya:
    def test_routing_worker_client_handles_unregistered_agent(self):
        client = RoutingWorkerClient({})
        result = asyncio.run(client.run_task(AgentChoice.ILIYA, "task-1", "test"))
        assert result.ok is False
        assert "No worker" in result.error_message

    def test_routing_worker_client_with_iliya_demo(self):
        client = RoutingWorkerClient({
            AgentChoice.ILIYA: DemoWorkerClient(),
        })
        result = asyncio.run(client.run_task(AgentChoice.ILIYA, "task-1", "test goal"))
        assert result.ok is True
        assert "iliya" in result.payload

    def test_build_worker_includes_iliya_in_mixed_mode(self):
        prev_oc = os.environ.get("OPENCLAW_URL")
        prev_hc = os.environ.get("HERMES_CLI_COMMAND")
        os.environ["OPENCLAW_URL"] = "http://openclaw.local/run-task"
        os.environ["HERMES_CLI_COMMAND"] = "python main.py run-task"
        try:
            from backend.workers import build_worker_client_from_env
            client = build_worker_client_from_env()
            assert isinstance(client, RoutingWorkerClient)
            assert AgentChoice.ILIYA in client.clients
            assert isinstance(client.clients[AgentChoice.ILIYA], DemoWorkerClient)
        finally:
            if prev_oc is None:
                os.environ.pop("OPENCLAW_URL", None)
            else:
                os.environ["OPENCLAW_URL"] = prev_oc
            if prev_hc is None:
                os.environ.pop("HERMES_CLI_COMMAND", None)
            else:
                os.environ["HERMES_CLI_COMMAND"] = prev_hc


# ══════════════════════════════════════════════════════════
#  11. 编排器集成（含 iliya）
# ══════════════════════════════════════════════════════════

class TestOrchestratorWithIliya:
    def _make_orchestrator(self):
        router = AgentRouter()
        router.register(IliyaAdapter())
        router.register(OpenClawAdapter())
        router.register(OpenHanakoAdapter())
        router.register(HermesAdapter())
        aggregator = ResultAggregator()
        return MultiAgentOrchestrator(router, aggregator)

    @pytest.mark.asyncio
    async def test_single_execution_via_iliya(self):
        orch = self._make_orchestrator()
        plan = ExecutionPlan.single("test_iliya_single", "iliya", "调度任务")
        result = await orch.execute(plan)
        assert result.status == "completed"
        assert len(result.step_results) == 1

    @pytest.mark.asyncio
    async def test_pipeline_execution_with_iliya(self):
        orch = self._make_orchestrator()
        plan = ExecutionPlan.pipeline("test_iliya_pipe", "调度+编码", [
            ("iliya", "分析任务并路由"),
            ("openclaw", "修复代码"),
        ])
        result = await orch.execute(plan)
        assert result.status == "completed"
        assert len(result.step_results) == 2

    @pytest.mark.asyncio
    async def test_parallel_execution_with_iliya(self):
        orch = self._make_orchestrator()
        plan = ExecutionPlan.parallel("test_iliya_par", "并行调度", [
            ("iliya", "调度分发"),
            ("openclaw", "代码修复"),
            ("hermes", "研究分析"),
        ])
        result = await orch.execute(plan)
        assert result.status == "completed"
        assert len(result.step_results) == 3

    @pytest.mark.asyncio
    async def test_create_plan_routes_to_iliya_for_dispatch(self):
        orch = self._make_orchestrator()
        plan = orch.create_plan_from_task("调度任务到 openclaw", mode=ExecutionMode.SINGLE)
        assert plan.mode == ExecutionMode.SINGLE
        assert plan.steps[0].agent == "iliya"

    @pytest.mark.asyncio
    async def test_create_plan_routes_to_openclaw_for_code(self):
        orch = self._make_orchestrator()
        plan = orch.create_plan_from_task("fix this bug in the code", mode=ExecutionMode.SINGLE)
        assert plan.steps[0].agent == "openclaw"


# ══════════════════════════════════════════════════════════
#  12. 端到端调度流程
# ══════════════════════════════════════════════════════════

class TestEndToEndDispatch:
    def test_full_dispatch_flow_iliya_to_openclaw(self):
        router = AgentRouter()
        router.register(IliyaAdapter())
        router.register(OpenClawAdapter())
        router.register(OpenHanakoAdapter())
        router.register(HermesAdapter())

        task = _make_task("修复代码中的 bug", "code_repair")
        result = router.dispatch(task)
        assert result.status == "completed"
        assert result.agent_name == "openclaw"

    def test_full_dispatch_flow_iliya_direct(self):
        router = AgentRouter()
        router.register(IliyaAdapter())
        router.register(OpenClawAdapter())

        task = _make_task("调度分发任务到各子Agent", "agent_routing")
        result = router.dispatch(task)
        assert result.status == "completed"
        assert result.agent_name == "iliya"

    def test_scheduler_to_router_integration(self):
        decision = route_task("调度任务", AgentChoice.AUTO)
        assert decision.selected_agent == AgentChoice.ILIYA

        router = AgentRouter()
        router.register(IliyaAdapter())
        router.register(OpenClawAdapter())

        task = _make_task("调度任务", decision.selected_agent.value)
        result = router.dispatch(task)
        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_execute_interface_full_flow(self):
        adapter = IliyaAdapter(config={"allow_shell": True})
        result = await adapter.execute("echo hello", {"action": "execute", "command": "echo hello"})
        assert result["ok"] is True
        assert "hello" in result["result"]

    @pytest.mark.asyncio
    async def test_execute_interface_routing(self):
        adapter = IliyaAdapter()
        result = await adapter.execute("route to openclaw", {"action": "dispatch", "target_agent": "openclaw"})
        assert result["ok"] is True
        assert "openclaw" in result["result"]

    @pytest.mark.asyncio
    async def test_execute_interface_file_read(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("execute interface test")
            tmp_path = f.name
        try:
            adapter = IliyaAdapter()
            result = await adapter.execute("read file", {"action": "read", "path": tmp_path})
            assert result["ok"] is True
            assert "execute interface test" in result["result"]
        finally:
            os.unlink(tmp_path)
