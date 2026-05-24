from pathlib import Path
from uuid import uuid4

from backend.dispatcher import TaskDispatcher
from backend.models import AgentChoice, TaskCreate, TaskStatus
from backend.storage import TaskRepository
from backend.waiting_scheduler import WaitingTaskScheduler
from backend.workers import WorkerClient, WorkerResult


class SuccessfulWorkerClient(WorkerClient):
    def __init__(self):
        self.calls = 0

    async def run_task(self, agent: AgentChoice, task_id: str, goal: str) -> WorkerResult:
        self.calls += 1
        return WorkerResult(ok=True, payload='{"ok":true}')


def test_waiting_scheduler_resumes_waiting_hermes_task_when_available():
    repository = TaskRepository(_test_database_path("waiting-scheduler"))
    repository.initialize()
    task = repository.create_task(
        TaskCreate(goal="Research orchestration patterns", requested_agent=AgentChoice.HERMES),
        selected_agent=AgentChoice.HERMES,
        routing_reason="Explicit agent selection: hermes",
        scheduler_mode="rules",
        plan_summary="Single execution task",
    )
    repository.set_waiting(task.id, reason="Hermes is busy; task is waiting for availability")

    worker = SuccessfulWorkerClient()
    dispatcher = TaskDispatcher(repository, worker)
    scheduler = WaitingTaskScheduler(
        repository,
        dispatcher,
        availability_probe=lambda agent: True,
    )

    resumed = scheduler.resume_waiting_tasks_once()
    stored = repository.get_task(task.id)

    assert resumed == 1
    assert worker.calls == 1
    assert stored is not None
    assert stored.status == TaskStatus.SUCCESS


def test_waiting_scheduler_skips_waiting_hermes_task_when_still_busy():
    repository = TaskRepository(_test_database_path("waiting-busy"))
    repository.initialize()
    task = repository.create_task(
        TaskCreate(goal="Research orchestration patterns", requested_agent=AgentChoice.HERMES),
        selected_agent=AgentChoice.HERMES,
        routing_reason="Explicit agent selection: hermes",
        scheduler_mode="rules",
        plan_summary="Single execution task",
    )
    repository.set_waiting(task.id, reason="Hermes is busy; task is waiting for availability")

    worker = SuccessfulWorkerClient()
    dispatcher = TaskDispatcher(repository, worker)
    scheduler = WaitingTaskScheduler(
        repository,
        dispatcher,
        availability_probe=lambda agent: agent != AgentChoice.HERMES,
    )

    resumed = scheduler.resume_waiting_tasks_once()
    stored = repository.get_task(task.id)

    assert resumed == 0
    assert worker.calls == 0
    assert stored is not None
    assert stored.status == TaskStatus.WAITING


def _test_database_path(prefix: str) -> Path:
    temp_dir = Path("tests/.tmp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir / f"{prefix}-{uuid4().hex}.db"
