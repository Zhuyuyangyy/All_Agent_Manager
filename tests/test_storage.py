from pathlib import Path
from uuid import uuid4

from backend.models import AgentChoice, TaskCreate, TaskRecord, TaskStatus
from backend.storage import TaskRepository


def test_repository_inserts_and_reads_back_a_task():
    database_path = _test_database_path("insert-read")
    repository = TaskRepository(database_path)
    repository.initialize()

    created = repository.create_task(
        TaskCreate(
            goal="Build a local dispatcher UI",
            requested_agent=AgentChoice.AUTO,
        ),
        selected_agent=AgentChoice.OPENCLAW,
        routing_reason="Auto-routed to openclaw because goal matched keyword 'build'",
        scheduler_mode="rules",
        plan_summary="Single execution task",
    )

    fetched = repository.get_task(created.id)

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.goal == "Build a local dispatcher UI"
    assert fetched.status == TaskStatus.PENDING
    assert fetched.selected_agent == AgentChoice.OPENCLAW


def test_repository_updates_task_status_and_result():
    database_path = _test_database_path("status-update")
    repository = TaskRepository(database_path)
    repository.initialize()

    created = repository.create_task(
        TaskCreate(
            goal="Research agent orchestration patterns",
            requested_agent=AgentChoice.HERMES,
        ),
        selected_agent=AgentChoice.HERMES,
        routing_reason="Explicit agent selection: hermes",
        scheduler_mode="rules",
        plan_summary="Single execution task",
    )

    repository.update_task_state(created.id, TaskStatus.RUNNING)
    repository.complete_task(created.id, result_payload='{"summary":"done"}')

    fetched = repository.get_task(created.id)
    tasks = repository.list_tasks()

    assert fetched is not None
    assert fetched.status == TaskStatus.SUCCESS
    assert fetched.result_payload == '{"summary":"done"}'
    assert tasks[0].id == created.id


def _test_database_path(prefix: str) -> Path:
    temp_dir = Path("tests/.tmp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir / f"{prefix}-{uuid4().hex}.db"
