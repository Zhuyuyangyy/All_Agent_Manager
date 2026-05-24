"""Tests for agent_health module"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock

from backend.models import AgentChoice
from backend.agent_health import (
    HealthCheckResult,
    HealthChecker,
    HealthMonitor,
    HealthStatus,
    RecoveryAction,
    AgentHealthState,
    AgentRecoveryManager,
)


class TestHealthChecker:
    def setup_method(self):
        self.checker = HealthChecker()

    def test_register_and_check(self):
        def healthy_check():
            return True

        self.checker.register_check(AgentChoice.OPENCLAW, healthy_check)

        result = asyncio.get_event_loop().run_until_complete(
            self.checker.check(AgentChoice.OPENCLAW)
        )

        assert result.status == HealthStatus.HEALTHY
        assert result.agent == AgentChoice.OPENCLAW

    def test_check_unregistered_agent(self):
        result = asyncio.get_event_loop().run_until_complete(
            self.checker.check(AgentChoice.HERMES)
        )

        assert result.status == HealthStatus.UNKNOWN
        assert "No health check" in result.message

    def test_check_failure(self):
        def failing_check():
            raise ConnectionError("Connection refused")

        self.checker.register_check(AgentChoice.OPENCLAW, failing_check)

        result = asyncio.get_event_loop().run_until_complete(
            self.checker.check(AgentChoice.OPENCLAW)
        )

        assert result.status == HealthStatus.UNHEALTHY
        assert "Connection refused" in result.message

    def test_check_dict_result_ok(self):
        def dict_check():
            return {"ok": True}

        self.checker.register_check(AgentChoice.OPENCLAW, dict_check)

        result = asyncio.get_event_loop().run_until_complete(
            self.checker.check(AgentChoice.OPENCLAW)
        )

        assert result.status == HealthStatus.HEALTHY

    def test_check_dict_result_degraded(self):
        def dict_check():
            return {"ok": False, "error": "High latency"}

        self.checker.register_check(AgentChoice.OPENCLAW, dict_check)

        result = asyncio.get_event_loop().run_until_complete(
            self.checker.check(AgentChoice.OPENCLAW)
        )

        assert result.status == HealthStatus.DEGRADED
        assert result.message == "High latency"

    @pytest.mark.asyncio
    async def test_async_check(self):
        async def async_check():
            return True

        self.checker.register_check(AgentChoice.OPENCLAW, async_check)

        result = await self.checker.check(AgentChoice.OPENCLAW)
        assert result.status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_check_all(self):
        self.checker.register_check(AgentChoice.OPENCLAW, lambda: True)
        self.checker.register_check(AgentChoice.HERMES, lambda: False)

        results = await self.checker.check_all()
        assert len(results) == 2


class TestHealthMonitor:
    def setup_method(self):
        self.monitor = HealthMonitor(
            check_interval=60,
            failure_threshold=3,
            recovery_enabled=True,
        )

    def test_register_agent(self):
        self.monitor.register_agent(AgentChoice.OPENCLAW, lambda: True)
        state = self.monitor.get_state(AgentChoice.OPENCLAW)

        assert state is not None
        assert state.agent == AgentChoice.OPENCLAW
        assert state.status == HealthStatus.UNKNOWN

    @pytest.mark.asyncio
    async def test_check_all_healthy(self):
        self.monitor.register_agent(AgentChoice.OPENCLAW, lambda: True)
        self.monitor.register_agent(AgentChoice.HERMES, lambda: True)

        results = await self.monitor.check_all()

        assert len(results) == 2
        for agent, result in results.items():
            assert result.status == HealthStatus.HEALTHY

        # Check state updates
        hana_state = self.monitor.get_state(AgentChoice.OPENCLAW)
        assert hana_state.status == HealthStatus.HEALTHY
        assert hana_state.consecutive_failures == 0
        assert hana_state.total_checks == 1

    @pytest.mark.asyncio
    async def test_check_all_with_failure(self):
        self.monitor.register_agent(AgentChoice.OPENCLAW, lambda: True)
        self.monitor.register_agent(AgentChoice.HERMES, lambda: (_ for _ in ()).throw(ConnectionError("Down")))

        results = await self.monitor.check_all()

        hermes_state = self.monitor.get_state(AgentChoice.HERMES)
        assert hermes_state.status == HealthStatus.UNHEALTHY
        assert hermes_state.consecutive_failures == 1
        assert hermes_state.total_failures == 1

    @pytest.mark.asyncio
    async def test_consecutive_failures_trigger_recovery(self):
        failing_check = MagicMock(side_effect=ConnectionError("Down"))
        self.monitor.register_agent(AgentChoice.OPENCLAW, failing_check)

        # Check 3 times to reach threshold
        for _ in range(3):
            await self.monitor.check_all()

        state = self.monitor.get_state(AgentChoice.OPENCLAW)
        assert state.consecutive_failures == 3
        assert state.recovery_action == RecoveryAction.RESTART

    @pytest.mark.asyncio
    async def test_status_change_callback(self):
        callback = MagicMock()
        self.monitor.set_callbacks(on_status_change=callback)
        self.monitor.register_agent(AgentChoice.OPENCLAW, lambda: True)

        await self.monitor.check_all()

        # First check: UNKNOWN -> HEALTHY
        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == AgentChoice.OPENCLAW
        assert args[1] == HealthStatus.UNKNOWN
        assert args[2] == HealthStatus.HEALTHY

    def test_get_unhealthy_agents(self):
        self.monitor.register_agent(AgentChoice.OPENCLAW, lambda: True)
        self.monitor.register_agent(AgentChoice.HERMES, lambda: True)

        # Manually set unhealthy state
        state = self.monitor.get_state(AgentChoice.HERMES)
        state.status = HealthStatus.UNHEALTHY

        unhealthy = self.monitor.get_unhealthy_agents()
        assert AgentChoice.HERMES in unhealthy
        assert AgentChoice.OPENCLAW not in unhealthy

    def test_get_stats_summary(self):
        self.monitor.register_agent(AgentChoice.OPENCLAW, lambda: True)
        self.monitor.register_agent(AgentChoice.HERMES, lambda: True)

        # Set different states
        self.monitor.get_state(AgentChoice.OPENCLAW).status = HealthStatus.HEALTHY
        self.monitor.get_state(AgentChoice.HERMES).status = HealthStatus.DEGRADED

        summary = self.monitor.get_stats_summary()
        assert summary["total_agents"] == 2
        assert summary["healthy"] == 1
        assert summary["degraded"] == 1

    @pytest.mark.asyncio
    async def test_start_stop(self):
        await self.monitor.start()
        assert self.monitor._running is True

        await self.monitor.stop()
        assert self.monitor._running is False


class TestAgentRecoveryManager:
    def setup_method(self):
        self.manager = AgentRecoveryManager()

    def test_execute_recovery(self):
        strategy = MagicMock(return_value=True)
        self.manager.register_strategy(RecoveryAction.RESTART, strategy)

        result = asyncio.get_event_loop().run_until_complete(
            self.manager.execute_recovery(AgentChoice.OPENCLAW, RecoveryAction.RESTART)
        )

        assert result is True
        strategy.assert_called_once_with(AgentChoice.OPENCLAW)

        history = self.manager.get_recovery_history()
        assert len(history) == 1
        assert history[0]["success"] is True

    def test_execute_recovery_no_strategy(self):
        result = asyncio.get_event_loop().run_until_complete(
            self.manager.execute_recovery(AgentChoice.OPENCLAW, RecoveryAction.RESTART)
        )

        assert result is False

    def test_execute_recovery_failure(self):
        strategy = MagicMock(side_effect=Exception("Recovery failed"))
        self.manager.register_strategy(RecoveryAction.RESTART, strategy)

        result = asyncio.get_event_loop().run_until_complete(
            self.manager.execute_recovery(AgentChoice.OPENCLAW, RecoveryAction.RESTART)
        )

        assert result is False

        history = self.manager.get_recovery_history()
        assert len(history) == 1
        assert history[0]["success"] is False
        assert "Recovery failed" in history[0]["error"]


class TestHealthCheckResult:
    def test_to_dict(self):
        result = HealthCheckResult(
            agent=AgentChoice.OPENCLAW,
            status=HealthStatus.HEALTHY,
            message="All good",
            latency_ms=42.5,
        )

        d = result.to_dict()
        assert d["agent"] == "openclaw"
        assert d["status"] == "healthy"
        assert d["message"] == "All good"
        assert d["latency_ms"] == 42.5


class TestAgentHealthState:
    def test_to_dict(self):
        state = AgentHealthState(
            agent=AgentChoice.OPENCLAW,
            status=HealthStatus.UNHEALTHY,
            consecutive_failures=5,
            total_checks=10,
            total_failures=5,
            avg_latency_ms=123.45,
        )

        d = state.to_dict()
        assert d["agent"] == "openclaw"
        assert d["status"] == "unhealthy"
        assert d["consecutive_failures"] == 5
        assert d["total_checks"] == 10
        assert d["total_failures"] == 5
        assert d["avg_latency_ms"] == 123.45
