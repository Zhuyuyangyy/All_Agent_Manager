import asyncio
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from backend.models import AgentChoice, TaskStatus
from backend.storage import TaskRepository
from backend.workers import WorkerClient

if TYPE_CHECKING:
    from backend.execution_monitor import ExecutionMonitor


class TaskDispatcher:
    def __init__(
        self,
        repository: TaskRepository,
        worker_client: WorkerClient,
        availability_probe: Callable[[AgentChoice], bool] | None = None,
        execution_monitor: "ExecutionMonitor | None" = None,
    ):
        self.repository = repository
        self.worker_client = worker_client
        self.availability_probe = availability_probe or (lambda agent: True)
        self.execution_monitor = execution_monitor

    def run_sync(self, task_id: str) -> None:
        asyncio.run(self.run_task(task_id))

    async def run_task(self, task_id: str) -> None:
        task = self.repository.get_task(task_id)
        if task is None:
            raise ValueError(f"Task '{task_id}' was not found")

        if not self.availability_probe(task.selected_agent):
            self.repository.set_waiting(
                task_id,
                reason="Hermes is busy; task is waiting for availability",
            )
            return

        self.repository.update_task_state(task_id, TaskStatus.RUNNING)

        # 开始执行监控
        if self.execution_monitor:
            self.execution_monitor.start_execution(task_id, task.selected_agent)

        start_time = time.time()
        result = await self.worker_client.run_task(task.selected_agent, task_id, task.goal)
        duration = time.time() - start_time

        if result.ok:
            self.repository.complete_task(task_id, result_payload=result.payload or "")
            if self.execution_monitor:
                self.execution_monitor.complete_execution(task_id, duration)
            return

        error_msg = result.error_message or "Unknown worker failure"
        self.repository.fail_task(task_id, error_message=error_msg)
        if self.execution_monitor:
            self.execution_monitor.fail_execution(task_id, error_msg, duration)
