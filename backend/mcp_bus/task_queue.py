"""
task_queue.py — MCP Bus 异步任务队列（可选）

初期用内存队列，支持简单的 enqueue/dequeue。
后续可替换为 Celery + Redis 实现真正的分布式队列。

设计：
  - 主控 enqueue(task) → 任务入队
  - 子 Agent 通过 /mcp/queue/poll 主动拉取任务
  - 执行完后通过 /mcp/queue/complete 提交结果
  - 主控通过 /mcp/queue/result 获取结果
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class QueuedTask:
    id: str = field(default_factory=lambda: f"q_{uuid.uuid4().hex[:8]}")
    capability: str = ""           # 所需能力
    payload: Dict[str, Any] = field(default_factory=dict)  # MCP 调用参数
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    worker_id: Optional[str] = None  # 当前执行的 worker


class TaskQueue:
    """内存任务队列"""

    def __init__(self):
        self._queue: Dict[str, QueuedTask] = {}
        self._lock = asyncio.Lock()

    async def enqueue(self, capability: str, payload: Dict[str, Any]) -> str:
        """主控提交任务到队列"""
        task = QueuedTask(capability=capability, payload=payload)
        async with self._lock:
            self._queue[task.id] = task
        logger.info(f"[Queue] Enqueued task {task.id} (capability={capability})")
        return task.id

    async def poll(self, worker_id: str, capability: str) -> Optional[QueuedTask]:
        """子 Agent 主动拉取任务（只能拉取匹配能力的 pending 任务）"""
        async with self._lock:
            for task_id, task in self._queue.items():
                if task.status == TaskStatus.PENDING and capability in task.capability:
                    task.status = TaskStatus.RUNNING
                    task.worker_id = worker_id
                    task.started_at = datetime.now().isoformat()
                    logger.info(f"[Queue] Worker {worker_id} polled task {task_id}")
                    return task
        return None

    async def complete(self, task_id: str, result: Any) -> dict:
        """子 Agent 提交执行结果"""
        async with self._lock:
            if task_id not in self._queue:
                return {"status": "error", "message": "Task not found"}
            task = self._queue[task_id]
            task.status = TaskStatus.SUCCESS
            task.result = result
            task.completed_at = datetime.now().isoformat()
        logger.info(f"[Queue] Task {task_id} completed by {task.worker_id}")
        return {"status": "ok", "task_id": task_id}

    async def fail(self, task_id: str, error: str) -> dict:
        """子 Agent 报告执行失败"""
        async with self._lock:
            if task_id not in self._queue:
                return {"status": "error", "message": "Task not found"}
            task = self._queue[task_id]
            task.status = TaskStatus.FAILED
            task.error = error
            task.completed_at = datetime.now().isoformat()
        logger.warning(f"[Queue] Task {task_id} failed: {error}")
        return {"status": "ok", "task_id": task_id}

    async def cancel(self, task_id: str) -> dict:
        """主控取消任务"""
        async with self._lock:
            if task_id not in self._queue:
                return {"status": "error", "message": "Task not found"}
            task = self._queue[task_id]
            if task.status != TaskStatus.PENDING:
                return {"status": "error", "message": f"Cannot cancel task in {task.status} status"}
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now().isoformat()
        return {"status": "ok", "task_id": task_id}

    async def get_result(self, task_id: str) -> Optional[dict]:
        """主控获取任务结果"""
        async with self._lock:
            if task_id not in self._queue:
                return None
            task = self._queue[task_id]
            return {
                "id": task.id,
                "status": task.status.value,
                "result": task.result,
                "error": task.error,
                "worker_id": task.worker_id,
                "created_at": task.created_at,
                "completed_at": task.completed_at,
            }

    async def list_pending(self) -> list:
        """列出所有 pending 任务（主控查看队列状态）"""
        async with self._lock:
            return [
                {
                    "id": t.id,
                    "capability": t.capability,
                    "status": t.status.value,
                    "created_at": t.created_at,
                }
                for t in self._queue.values()
                if t.status == TaskStatus.PENDING
            ]


# 全局单例
_queue = TaskQueue()


def get_queue() -> TaskQueue:
    return _queue