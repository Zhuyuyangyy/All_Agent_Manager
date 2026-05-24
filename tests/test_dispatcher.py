from pathlib import Path
from uuid import uuid4

from backend.dispatcher import TaskDispatcher
from backend.models import AgentChoice, TaskCreate, TaskStatus
from backend.storage import TaskRepository
from backend.workers import WorkerClient, WorkerResult


class SuccessfulWorkerClient(WorkerClient):
    async def run_task(self, agent: AgentChoice, task_id: str, goal: str) -> WorkerResult:
        return WorkerResult(
            ok=True,
            payload='{"agent":"%s","goal":"%s"}' % (agent.value, goal),
        )


class FailingWorkerClient(WorkerClient):
    async def run_task(self, agent: AgentChoice, task_id: str, goal: str) -> WorkerResult:
        return WorkerResult(ok=False, error_message="worker unavailable")


class CountingWorkerClient(WorkerClient):
    def __init__(self):
        self.calls = 0

    async def run_task(self, agent: AgentChoice, task_id: str, goal: str) -> WorkerResult:
        self.calls += 1
        return WorkerResult(ok=True, payload='{"ok":true}')


def test_dispatcher_marks_task_success_and_persists_result():
    repository = TaskRepository(_test_database_path("dispatcher-success"))
    repository.initialize()
    task = repository.create_task(
        TaskCreate(goal="Implement the scheduler API", requested_agent=AgentChoice.AUTO),
        selected_agent=AgentChoice.OPENCLAW,
        routing_reason="Auto-routed to openclaw because goal matched keyword 'implement'",
        scheduler_mode="rules",
        plan_summary="Single execution task",
    )

    dispatcher = TaskDispatcher(repository, SuccessfulWorkerClient())

    dispatcher.run_sync(task.id)

    stored = repository.get_task(task.id)

    assert stored is not None
    assert stored.status == TaskStatus.SUCCESS
    assert stored.result_payload is not None
    assert "openclaw" in stored.result_payload


def test_dispatcher_marks_task_failed_when_worker_returns_error():
    repository = TaskRepository(_test_database_path("dispatcher-failure"))
    repository.initialize()
    task = repository.create_task(
        TaskCreate(goal="Research a market summary", requested_agent=AgentChoice.HERMES),
        selected_agent=AgentChoice.HERMES,
        routing_reason="Explicit agent selection: hermes",
        scheduler_mode="rules",
        plan_summary="Single execution task",
    )

    dispatcher = TaskDispatcher(repository, FailingWorkerClient())

    dispatcher.run_sync(task.id)

    stored = repository.get_task(task.id)

    assert stored is not None
    assert stored.status == TaskStatus.FAILED
    assert stored.error_message == "worker unavailable"


def test_dispatcher_marks_hermes_task_waiting_when_probe_reports_busy():
    repository = TaskRepository(_test_database_path("dispatcher-hermes-waiting"))
    repository.initialize()
    task = repository.create_task(
        TaskCreate(goal="Research a market summary", requested_agent=AgentChoice.HERMES),
        selected_agent=AgentChoice.HERMES,
        routing_reason="Explicit agent selection: hermes",
        scheduler_mode="rules",
        plan_summary="Single execution task",
    )
    worker = CountingWorkerClient()
    dispatcher = TaskDispatcher(
        repository,
        worker,
        availability_probe=lambda agent: agent != AgentChoice.HERMES,
    )

    dispatcher.run_sync(task.id)

    stored = repository.get_task(task.id)

    assert stored is not None
    assert stored.status == TaskStatus.WAITING
    assert stored.error_message == "Hermes is busy; task is waiting for availability"
    assert worker.calls == 0


def _test_database_path(prefix: str) -> Path:
    temp_dir = Path("tests/.tmp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir / f"{prefix}-{uuid4().hex}.db"
