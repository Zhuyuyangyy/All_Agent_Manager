"""Tests for task_registry module"""

import asyncio
import pytest
from backend.event_bus import EventBus
from backend.task_registry import (
    TaskRegistry,
    TaskHandler,
    TaskInstance,
    TaskResult,
    TaskStatus,
)


class MockTaskHandler(TaskHandler):
    """模拟任务处理器"""

    def __init__(self, should_fail: bool = False, duration: float = 0.1):
        self._should_fail = should_fail
        self._duration = duration
        self.executed_tasks = []

    @property
    def task_type(self) -> str:
        return "mock_task"

    async def execute(self, task_id: str, payload: dict) -> TaskResult:
        self.executed_tasks.append(task_id)
        await asyncio.sleep(self._duration)

        if self._should_fail:
            return TaskResult(success=False, error="Mock error")

        return TaskResult(success=True, payload={"result": "ok"})

    async def abort(self, task_id: str) -> bool:
        return True


class TestTaskRegistry:
    def setup_method(self):
        self.event_bus = EventBus()
        self.registry = TaskRegistry(event_bus=self.event_bus)

    def test_register_handler(self):
        """测试注册处理器"""
        handler = MockTaskHandler()
        self.registry.register_handler(handler)

        assert "mock_task" in self.registry.registered_types
        assert self.registry.get_handler("mock_task") is handler

    def test_register_task(self):
        """测试注册任务实例"""
        handler = MockTaskHandler()
        self.registry.register_handler(handler)

        instance = self.registry.register_task("task-1", "mock_task", {"goal": "test"})
        assert instance.task_id == "task-1"
        assert instance.task_type == "mock_task"
        assert instance.status == TaskStatus.REGISTERED

    def test_get_task(self):
        """测试获取任务实例"""
        self.registry.register_task("task-1", "mock_task")

        task = self.registry.get_task("task-1")
        assert task is not None
        assert task.task_id == "task-1"

        task = self.registry.get_task("nonexistent")
        assert task is None

    def test_list_tasks(self):
        """测试列出任务实例"""
        self.registry.register_task("task-1", "mock_task")
        self.registry.register_task("task-2", "mock_task")
        self.registry.register_task("task-3", "other_task")

        all_tasks = self.registry.list_tasks()
        assert len(all_tasks) == 3

        mock_tasks = self.registry.list_tasks(task_type="mock_task")
        assert len(mock_tasks) == 2

    def test_remove_task(self):
        """测试移除任务实例"""
        self.registry.register_task("task-1", "mock_task")

        assert self.registry.remove_task("task-1") is True
        assert self.registry.get_task("task-1") is None

        assert self.registry.remove_task("nonexistent") is False

    @pytest.mark.asyncio
    async def test_dispatch_task(self):
        """测试分发任务"""
        handler = MockTaskHandler()
        self.registry.register_handler(handler)
        self.registry.register_task("task-1", "mock_task", {"goal": "test"})

        result = await self.registry.dispatch("task-1", {"goal": "test"})

        assert result.success is True
        assert "task-1" in handler.executed_tasks

        task = self.registry.get_task("task-1")
        assert task.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_dispatch_task_failure(self):
        """测试任务执行失败"""
        handler = MockTaskHandler(should_fail=True)
        self.registry.register_handler(handler)
        self.registry.register_task("task-1", "mock_task")

        with pytest.raises(Exception):
            await self.registry.dispatch("task-1", {})

        task = self.registry.get_task("task-1")
        assert task.status == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_dispatch_nonexistent_task(self):
        """测试分发不存在的任务"""
        with pytest.raises(ValueError, match="Task not found"):
            await self.registry.dispatch("nonexistent", {})

    @pytest.mark.asyncio
    async def test_dispatch_no_handler(self):
        """测试分发没有处理器的任务类型"""
        self.registry.register_task("task-1", "unknown_type")

        with pytest.raises(ValueError, match="No handler"):
            await self.registry.dispatch("task-1", {})

    @pytest.mark.asyncio
    async def test_abort_task(self):
        """测试中止任务"""
        handler = MockTaskHandler()
        self.registry.register_handler(handler)
        self.registry.register_task("task-1", "mock_task")
        task = self.registry.get_task("task-1")
        task.status = TaskStatus.RUNNING

        result = await self.registry.abort("task-1")
        assert result is True

    def test_abort_nonexistent_task(self):
        """测试中止不存在的任务"""
        result = asyncio.run(self.registry.abort("nonexistent"))
        assert result is False

    @pytest.mark.asyncio
    async def test_dispatch_batch(self):
        """测试批量分发任务"""
        handler = MockTaskHandler()
        self.registry.register_handler(handler)

        self.registry.register_task("task-1", "mock_task")
        self.registry.register_task("task-2", "mock_task")
        self.registry.register_task("task-3", "mock_task")

        results = await self.registry.dispatch_batch([
            ("task-1", {"goal": "test1"}),
            ("task-2", {"goal": "test2"}),
            ("task-3", {"goal": "test3"}),
        ])

        assert len(results) == 3
        assert all(r.success for r in results)

    def test_get_stats(self):
        """测试获取统计"""
        self.registry.register_task("task-1", "mock_task")
        self.registry.register_task("task-2", "mock_task")

        stats = self.registry.get_stats()
        assert stats["total"] == 2
        assert stats["registered"] == 2
        assert "mock_task" in stats["handlers"]

    @pytest.mark.asyncio
    async def test_event_published(self):
        """测试事件发布"""
        received_events = []

        def callback(event):
            received_events.append(event)

        self.event_bus.subscribe(callback, filter_types=["task.started", "task.completed"])

        handler = MockTaskHandler()
        self.registry.register_handler(handler)
        self.registry.register_task("task-1", "mock_task")

        await self.registry.dispatch("task-1", {})

        assert len(received_events) == 2
        assert received_events[0].type == "task.started"
        assert received_events[1].type == "task.completed"


class TestTaskResult:
    def test_to_dict(self):
        """测试 TaskResult 序列化"""
        result = TaskResult(success=True, payload={"key": "value"}, duration=1.5)
        d = result.to_dict()

        assert d["success"] is True
        assert d["payload"] == {"key": "value"}
        assert d["duration"] == 1.5
        assert d["error"] is None

    def test_error_result(self):
        """测试错误结果"""
        result = TaskResult(success=False, error="Something went wrong")
        d = result.to_dict()

        assert d["success"] is False
        assert d["error"] == "Something went wrong"


class TestTaskInstance:
    def test_to_dict(self):
        """测试 TaskInstance 序列化"""
        instance = TaskInstance(
            task_id="task-1",
            task_type="mock_task",
            meta={"goal": "test"},
            status=TaskStatus.RUNNING,
        )
        d = instance.to_dict()

        assert d["task_id"] == "task-1"
        assert d["task_type"] == "mock_task"
        assert d["meta"] == {"goal": "test"}
        assert d["status"] == "running"
        assert "created_at" in d
