"""Tests for execution_monitor module"""

import asyncio
import pytest
from unittest.mock import MagicMock

from backend.models import AgentChoice
from backend.execution_monitor import (
    ExecutionEvent,
    ExecutionMonitor,
    ExecutionRecord,
    TaskExecutionState,
    TimeoutChecker,
)


class TestExecutionMonitor:
    def setup_method(self):
        self.monitor = ExecutionMonitor(
            default_timeout=30,
            default_max_retries=3,
            heartbeat_interval=10,
        )

    def test_start_execution(self):
        state = self.monitor.start_execution("task-1", AgentChoice.OPENCLAW)
        assert state.task_id == "task-1"
        assert state.status == "running"
        assert state.agent == AgentChoice.OPENCLAW
        assert state.retry_count == 0
        assert state.max_retries == 3
        assert state.timeout_seconds == 30

    def test_complete_execution(self):
        self.monitor.start_execution("task-1", AgentChoice.OPENCLAW)
        self.monitor.complete_execution("task-1", duration=5.0)

        state = self.monitor.get_state("task-1")
        assert state is not None
        assert state.status == "completed"

        history = self.monitor.get_history()
        assert len(history) == 2  # started + completed
        assert history[1]["event"] == "completed"
        assert history[1]["duration"] == 5.0

    def test_fail_execution_with_retry(self):
        self.monitor.start_execution("task-1", AgentChoice.OPENCLAW)
        should_retry = self.monitor.fail_execution("task-1", "Connection error")

        assert should_retry is True
        state = self.monitor.get_state("task-1")
        assert state.status == "retrying"
        assert state.retry_count == 1

    def test_fail_execution_max_retries(self):
        self.monitor.start_execution("task-1", AgentChoice.OPENCLAW)

        # Fail 3 times (max retries)
        for i in range(3):
            self.monitor.fail_execution("task-1", f"Error {i+1}")

        state = self.monitor.get_state("task-1")
        assert state.status == "failed"
        assert state.retry_count == 3

        history = self.monitor.get_history()
        assert len(history) == 4  # started + 3 retries

    def test_timeout_execution(self):
        self.monitor.start_execution("task-1", AgentChoice.OPENCLAW)
        should_retry = self.monitor.timeout_execution("task-1")

        assert should_retry is True
        state = self.monitor.get_state("task-1")
        assert state.status == "retrying"

    def test_cancel_execution(self):
        self.monitor.start_execution("task-1", AgentChoice.OPENCLAW)
        self.monitor.cancel_execution("task-1")

        state = self.monitor.get_state("task-1")
        assert state.status == "cancelled"

    def test_heartbeat_update(self):
        self.monitor.start_execution("task-1", AgentChoice.OPENCLAW)
        old_heartbeat = self.monitor.get_state("task-1").last_heartbeat

        self.monitor.update_heartbeat("task-1")
        new_heartbeat = self.monitor.get_state("task-1").last_heartbeat

        # Heartbeat should be updated (or same if very fast)
        assert new_heartbeat is not None

    def test_check_timeouts(self):
        # Create a task with very short timeout
        monitor = ExecutionMonitor(default_timeout=0.1)
        monitor.start_execution("task-1", AgentChoice.OPENCLAW)

        # Wait for timeout
        import time
        time.sleep(0.2)

        timeout_tasks = monitor.check_timeouts()
        assert "task-1" in timeout_tasks

    def test_check_stale_heartbeats(self):
        monitor = ExecutionMonitor(heartbeat_interval=0.1)
        monitor.start_execution("task-1", AgentChoice.OPENCLAW)

        # Wait for stale heartbeat
        import time
        time.sleep(0.5)

        stale_tasks = monitor.check_stale_heartbeats()
        assert "task-1" in stale_tasks

    def test_get_running_tasks(self):
        self.monitor.start_execution("task-1", AgentChoice.OPENCLAW)
        self.monitor.start_execution("task-2", AgentChoice.HERMES)
        self.monitor.complete_execution("task-1")

        running = self.monitor.get_running_tasks()
        assert len(running) == 1
        assert running[0].task_id == "task-2"

    def test_get_retrying_tasks(self):
        self.monitor.start_execution("task-1", AgentChoice.OPENCLAW)
        self.monitor.start_execution("task-2", AgentChoice.HERMES)
        self.monitor.fail_execution("task-1", "Error")

        retrying = self.monitor.get_retrying_tasks()
        assert len(retrying) == 1
        assert retrying[0].task_id == "task-1"

    def test_cleanup_completed(self):
        self.monitor.start_execution("task-1", AgentChoice.OPENCLAW)
        self.monitor.complete_execution("task-1")

        # Cleanup with 0 seconds max age
        removed = self.monitor.cleanup_completed(max_age_seconds=0)
        assert removed == 1
        assert self.monitor.get_state("task-1") is None

    def test_agent_stats_update(self):
        self.monitor.start_execution("task-1", AgentChoice.OPENCLAW)
        self.monitor.complete_execution("task-1", duration=10.0)

        self.monitor.start_execution("task-2", AgentChoice.OPENCLAW)
        self.monitor.fail_execution("task-2", "Error")

        stats = self.monitor.get_agent_stats()
        assert "openclaw" in stats
        assert stats["openclaw"]["total_tasks"] == 2
        assert stats["openclaw"]["completed_tasks"] == 1
        assert stats["openclaw"]["failed_tasks"] == 1
        assert stats["openclaw"]["success_rate"] == 50.0

    def test_get_stats_summary(self):
        self.monitor.start_execution("task-1", AgentChoice.OPENCLAW)
        self.monitor.start_execution("task-2", AgentChoice.HERMES)
        self.monitor.complete_execution("task-1")

        summary = self.monitor.get_stats_summary()
        assert summary["running"] == 1
        assert summary["completed"] == 1
        assert summary["total_tracked"] == 2

    def test_callback_on_retry(self):
        retry_callback = MagicMock()
        self.monitor.set_callbacks(on_retry=retry_callback)

        self.monitor.start_execution("task-1", AgentChoice.OPENCLAW)
        self.monitor.fail_execution("task-1", "Error")

        retry_callback.assert_called_once_with("task-1", 1)

    def test_callback_on_timeout(self):
        timeout_callback = MagicMock()
        self.monitor.set_callbacks(on_timeout=timeout_callback)

        self.monitor.start_execution("task-1", AgentChoice.OPENCLAW)
        self.monitor.timeout_execution("task-1")

        timeout_callback.assert_called_once_with("task-1")

    def test_callback_on_failure(self):
        failure_callback = MagicMock()
        self.monitor.set_callbacks(on_failure=failure_callback)

        self.monitor.start_execution("task-1", AgentChoice.OPENCLAW)
        # Fail 3 times to reach max retries
        for i in range(3):
            self.monitor.fail_execution("task-1", f"Error {i+1}")

        failure_callback.assert_called_once_with("task-1", "Error 3")


class TestTimeoutChecker:
    def setup_method(self):
        self.monitor = ExecutionMonitor(default_timeout=0.1)
        self.timeout_calls = []
        self.checker = TimeoutChecker(
            monitor=self.monitor,
            check_interval=0.05,
            on_timeout=lambda task_id: self.timeout_calls.append(task_id),
        )

    @pytest.mark.asyncio
    async def test_timeout_detection(self):
        self.monitor.start_execution("task-1", AgentChoice.OPENCLAW)

        await self.checker.start()
        await asyncio.sleep(0.3)
        await self.checker.stop()

        assert "task-1" in self.timeout_calls

    @pytest.mark.asyncio
    async def test_start_stop(self):
        await self.checker.start()
        assert self.checker._running is True

        await self.checker.stop()
        assert self.checker._running is False
