import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from backend.models import AgentChoice, TaskCreate, TaskRecord, TaskStatus


class TaskRepository:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    requested_agent TEXT NOT NULL,
                    selected_agent TEXT NOT NULL,
                    routing_reason TEXT NOT NULL,
                    scheduler_mode TEXT NOT NULL,
                    plan_summary TEXT NOT NULL,
                    result_payload TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_dispatch_attempt_at TEXT
                )
                """
            )
            # 迁移：给旧表补上缺失的列
            cursor = connection.execute("PRAGMA table_info(tasks)")
            columns = {row[1] for row in cursor.fetchall()}
            if "retry_count" not in columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0")
            if "last_dispatch_attempt_at" not in columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN last_dispatch_attempt_at TEXT")

    def create_task(
        self,
        task: TaskCreate,
        *,
        selected_agent: AgentChoice,
        routing_reason: str,
        scheduler_mode: str,
        plan_summary: str,
    ) -> TaskRecord:
        task_id = str(uuid4())
        timestamp = _utc_now()

        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    id, goal, status, requested_agent, selected_agent,
                    routing_reason, scheduler_mode, plan_summary,
                    result_payload, error_message, created_at, updated_at,
                    retry_count, last_dispatch_attempt_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    task.goal,
                    TaskStatus.PENDING.value,
                    task.requested_agent.value,
                    selected_agent.value,
                    routing_reason,
                    scheduler_mode,
                    plan_summary,
                    None,
                    None,
                    timestamp,
                    timestamp,
                    0,
                    None,
                ),
            )

        return self.get_task(task_id)  # type: ignore[return-value]

    def get_task(self, task_id: str) -> TaskRecord | None:
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()

        return _row_to_task(row) if row else None

    def list_tasks(self) -> list[TaskRecord]:
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC"
            ).fetchall()

        return [_row_to_task(row) for row in rows]

    def list_tasks_by_status(self, status: TaskStatus) -> list[TaskRecord]:
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at ASC",
                (status.value,),
            ).fetchall()

        return [_row_to_task(row) for row in rows]

    def update_task_state(self, task_id: str, status: TaskStatus) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, _utc_now(), task_id),
            )

    def set_waiting(self, task_id: str, *, reason: str) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = ?, error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (TaskStatus.WAITING.value, reason, _utc_now(), task_id),
            )

    def claim_waiting_task(self, task_id: str) -> TaskRecord | None:
        with sqlite3.connect(self.database_path) as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                SET status = ?, error_message = NULL, updated_at = ?, last_dispatch_attempt_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    TaskStatus.PENDING.value,
                    _utc_now(),
                    _utc_now(),
                    task_id,
                    TaskStatus.WAITING.value,
                ),
            )
            if cursor.rowcount != 1:
                return None

        return self.get_task(task_id)

    def complete_task(self, task_id: str, *, result_payload: str) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = ?, result_payload = ?, updated_at = ?
                WHERE id = ?
                """,
                (TaskStatus.SUCCESS.value, result_payload, _utc_now(), task_id),
            )

    def fail_task(self, task_id: str, *, error_message: str) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = ?, error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (TaskStatus.FAILED.value, error_message, _utc_now(), task_id),
            )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_task(row: tuple) -> TaskRecord:
    return TaskRecord(
        id=row[0],
        goal=row[1],
        status=TaskStatus(row[2]),
        requested_agent=AgentChoice(row[3]),
        selected_agent=AgentChoice(row[4]),
        routing_reason=row[5],
        scheduler_mode=row[6],
        plan_summary=row[7],
        result_payload=row[8],
        error_message=row[9],
        created_at=row[10],
        updated_at=row[11],
        retry_count=row[12] if len(row) > 12 else 0,
        last_dispatch_attempt_at=row[13] if len(row) > 13 else None,
    )
