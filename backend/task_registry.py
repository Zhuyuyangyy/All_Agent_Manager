"""
task_registry.py — 任务注册表

参考 OpenHanako lib/task-registry.js，实现类型处理器模式。
支持动态注册任务类型、任务实例管理、abort 控制。
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from backend.event_bus import EventBus, EventTypes

logger = logging.getLogger(__name__)


class TaskStatus(StrEnum):
    """任务实例状态"""
    REGISTERED = "registered"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABORTED = "aborted"


@dataclass
class TaskResult:
    """任务执行结果"""
    success: bool
    payload: dict | None = None
    error: str | None = None
    duration: float | None = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "payload": self.payload,
            "error": self.error,
            "duration": self.duration,
        }


@dataclass
class TaskInstance:
    """任务实例"""
    task_id: str
    task_type: str
    meta: dict = field(default_factory=dict)
    status: TaskStatus = TaskStatus.REGISTERED
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: str | None = None
    completed_at: str | None = None
    result: TaskResult | None = None
    abort_controller: asyncio.Event | None = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "meta": self.meta,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": self.result.to_dict() if self.result else None,
        }


class TaskHandler(ABC):
    """任务处理器基类"""

    @property
    @abstractmethod
    def task_type(self) -> str:
        """任务类型标识"""
        pass

    @abstractmethod
    async def execute(self, task_id: str, payload: dict) -> TaskResult:
        """执行任务"""
        pass

    async def abort(self, task_id: str) -> bool:
        """中止任务（可选实现）"""
        return False

    async def query(self, task_id: str) -> dict | None:
        """查询任务状态（可选实现）"""
        return None


class TaskRegistry:
    """
    任务注册表 — 类型处理器 + 动态任务实例。

    参考 OpenHanako 的 TaskRegistry 设计：
    - 启动时按任务类型注册 handler
    - 运行时注册任务实例
    - abort 按 type 分发到对应 handler
    """

    def __init__(self, event_bus: EventBus):
        self._handlers: dict[str, TaskHandler] = {}
        self._tasks: dict[str, TaskInstance] = {}
        self._event_bus = event_bus

    # ── 处理器注册 ──

    def register_handler(self, handler: TaskHandler):
        """注册任务类型处理器"""
        self._handlers[handler.task_type] = handler
        logger.info(f"Registered handler for task type: {handler.task_type}")

    def unregister_handler(self, task_type: str):
        """注销任务类型处理器"""
        self._handlers.pop(task_type, None)
        logger.info(f"Unregistered handler for task type: {task_type}")

    def get_handler(self, task_type: str) -> TaskHandler | None:
        """获取任务类型处理器"""
        return self._handlers.get(task_type)

    @property
    def registered_types(self) -> list[str]:
        """已注册的任务类型"""
        return list(self._handlers.keys())

    # ── 任务实例管理 ──

    def register_task(self, task_id: str, task_type: str, meta: dict | None = None) -> TaskInstance:
        """注册任务实例"""
        if task_type not in self._handlers:
            logger.warning(f"No handler registered for task type: {task_type}")

        instance = TaskInstance(
            task_id=task_id,
            task_type=task_type,
            meta=meta or {},
            status=TaskStatus.REGISTERED,
        )
        self._tasks[task_id] = instance
        logger.debug(f"Registered task instance: {task_id} (type={task_type})")
        return instance

    def get_task(self, task_id: str) -> TaskInstance | None:
        """获取任务实例"""
        return self._tasks.get(task_id)

    def remove_task(self, task_id: str) -> bool:
        """移除任务实例"""
        if task_id in self._tasks:
            del self._tasks[task_id]
            return True
        return False

    def list_tasks(self, task_type: str | None = None, status: TaskStatus | None = None) -> list[TaskInstance]:
        """列出任务实例"""
        tasks = list(self._tasks.values())
        if task_type:
            tasks = [t for t in tasks if t.task_type == task_type]
        if status:
            tasks = [t for t in tasks if t.status == status]
        return tasks

    def list_all(self) -> list[dict]:
        """列出所有任务实例"""
        return [t.to_dict() for t in self._tasks.values()]

    # ── 任务执行 ──

    async def dispatch(self, task_id: str, payload: dict) -> TaskResult:
        """
        分发任务到对应处理器并执行。

        流程：
        1. 查找任务实例和处理器
        2. 更新状态为 RUNNING
        3. 发布 task.started 事件
        4. 执行任务
        5. 根据结果发布 task.completed 或 task.failed
        """
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        handler = self._handlers.get(task.task_type)
        if not handler:
            raise ValueError(f"No handler for task type: {task.task_type}")

        # 更新状态
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now().isoformat()
        task.abort_controller = asyncio.Event()

        # 发布事件
        await self._event_bus.publish_async(
            EventTypes.TASK_STARTED,
            data={"task_id": task_id, "type": task.task_type, "meta": task.meta},
            source="task_registry",
        )

        try:
            # 执行任务
            result = await handler.execute(task_id, payload)

            # 更新状态
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now().isoformat()
            task.result = result

            # 发布事件
            await self._event_bus.publish_async(
                EventTypes.TASK_COMPLETED,
                data={
                    "task_id": task_id,
                    "type": task.task_type,
                    "duration": result.duration,
                    "success": result.success,
                },
                source="task_registry",
            )

            return result

        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now().isoformat()

            await self._event_bus.publish_async(
                EventTypes.TASK_CANCELLED,
                data={"task_id": task_id, "type": task.task_type},
                source="task_registry",
            )

            raise

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.now().isoformat()
            task.result = TaskResult(success=False, error=str(e))

            await self._event_bus.publish_async(
                EventTypes.TASK_FAILED,
                data={"task_id": task_id, "type": task.task_type, "error": str(e)},
                source="task_registry",
            )

            raise

    async def abort(self, task_id: str) -> bool:
        """
        中止任务。

        按任务类型分发到对应 handler 的 abort 方法。
        """
        task = self._tasks.get(task_id)
        if not task:
            return False

        if task.status not in (TaskStatus.RUNNING, TaskStatus.PENDING):
            return False

        handler = self._handlers.get(task.task_type)
        if handler:
            success = await handler.abort(task_id)
            if success:
                task.status = TaskStatus.ABORTED
                task.completed_at = datetime.now().isoformat()

                await self._event_bus.publish_async(
                    EventTypes.TASK_CANCELLED,
                    data={"task_id": task_id, "type": task.task_type, "aborted": True},
                    source="task_registry",
                )
            return success

        return False

    # ── 批量操作 ──

    async def dispatch_batch(self, tasks: list[tuple[str, dict]]) -> list[TaskResult]:
        """
        批量分发任务（并行执行）。

        Args:
            tasks: [(task_id, payload), ...] 列表
        """
        coroutines = [self.dispatch(task_id, payload) for task_id, payload in tasks]
        results = await asyncio.gather(*coroutines, return_exceptions=True)

        final_results = []
        for result in results:
            if isinstance(result, Exception):
                final_results.append(TaskResult(success=False, error=str(result)))
            else:
                final_results.append(result)

        return final_results

    def abort_all(self) -> int:
        """中止所有运行中的任务"""
        count = 0
        for task in self._tasks.values():
            if task.status == TaskStatus.RUNNING:
                task.status = TaskStatus.ABORTED
                task.completed_at = datetime.now().isoformat()
                count += 1
        return count

    # ── 统计 ──

    def get_stats(self) -> dict:
        """获取任务统计"""
        tasks = list(self._tasks.values())
        return {
            "total": len(tasks),
            "registered": len([t for t in tasks if t.status == TaskStatus.REGISTERED]),
            "pending": len([t for t in tasks if t.status == TaskStatus.PENDING]),
            "running": len([t for t in tasks if t.status == TaskStatus.RUNNING]),
            "completed": len([t for t in tasks if t.status == TaskStatus.COMPLETED]),
            "failed": len([t for t in tasks if t.status == TaskStatus.FAILED]),
            "cancelled": len([t for t in tasks if t.status == TaskStatus.CANCELLED]),
            "aborted": len([t for t in tasks if t.status == TaskStatus.ABORTED]),
            "handlers": list(self._handlers.keys()),
        }
