import asyncio
from collections.abc import Callable

from backend.dispatcher import TaskDispatcher
from backend.models import AgentChoice, TaskStatus
from backend.storage import TaskRepository


class WaitingTaskScheduler:
    def __init__(
        self,
        repository: TaskRepository,
        dispatcher: TaskDispatcher,
        *,
        availability_probe: Callable[[AgentChoice], bool],
        interval_seconds: float = 3.0,
    ):
        self.repository = repository
        self.dispatcher = dispatcher
        self.availability_probe = availability_probe
        self.interval_seconds = interval_seconds
        self._running = True

    async def run_forever(self) -> None:
        while self._running:
            await self.resume_waiting_tasks_once_async()
            await asyncio.sleep(self.interval_seconds)

    def stop(self) -> None:
        self._running = False

    def resume_waiting_tasks_once(self) -> int:
        return asyncio.run(self.resume_waiting_tasks_once_async())

    async def resume_waiting_tasks_once_async(self) -> int:
        resumed = 0
        for task in self.repository.list_tasks_by_status(TaskStatus.WAITING):
            if not self.availability_probe(task.selected_agent):
                continue

            claimed = self.repository.claim_waiting_task(task.id)
            if claimed is None:
                continue

            await self.dispatcher.run_task(task.id)
            resumed += 1

        return resumed
