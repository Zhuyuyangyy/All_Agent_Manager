"""Task and submission routes."""
from uuid import uuid4
from typing import Optional
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.models import (
    AgentChoice,
    SubmitTaskRequest,
    SubmitTaskResponse,
    TaskCreate,
    TaskStatus,
)
from backend.repository import TaskRepository
from backend.dispatcher import TaskDispatcher
from backend.scheduler import route_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tasks", tags=["tasks"])


class SubmitTaskRequestModel(BaseModel):
    goal: str
    requested_agent: str = "auto"


@router.post("/submit-task", response_model=SubmitTaskResponse)
def submit_task(
    payload: SubmitTaskRequest,
    background_tasks: BackgroundTasks,
    repository: TaskRepository,
    dispatcher: TaskDispatcher,
) -> SubmitTaskResponse:
    """Submit a new task for processing."""
    try:
        routing = route_task(payload.goal, payload.requested_agent)
        task = repository.create_task(
            task=TaskCreate(
                goal=payload.goal,
                requested_agent=payload.requested_agent,
            ),
            selected_agent=routing.selected_agent,
            routing_reason=routing.routing_reason,
            scheduler_mode=routing.scheduler_mode,
            plan_summary="",
        )
        background_tasks.add_task(dispatcher.run_sync, task.id)
        return SubmitTaskResponse(
            task_id=task.id,
            status=task.status.value,
            selected_agent=task.selected_agent,
            routing_reason=task.routing_reason,
        )
    except Exception as e:
        logger.error(f"[tasks] submit error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/")
def list_tasks(
    repository: TaskRepository,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """List all tasks, optionally filtered by status."""
    try:
        if status:
            task_status = TaskStatus(status)
            tasks = repository.list_tasks_by_status(task_status)
        else:
            tasks = repository.list_tasks()
        return [t.to_dict() for t in tasks[:limit]]
    except Exception as e:
        logger.error(f"[tasks] list error: {e}")
        return []


@router.get("/{task_id}")
def get_task(task_id: str, repository: TaskRepository) -> dict:
    """Get details of a specific task."""
    task = repository.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str, repository: TaskRepository) -> dict:
    """Cancel a pending or running task."""
    task = repository.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    repository.fail_task(task_id, error="用户取消")
    return {"ok": True, "message": "任务已取消"}


@router.post("/{task_id}/retry")
def retry_task(task_id: str, repository: TaskRepository) -> dict:
    """Retry a failed task."""
    task = repository.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    repository.update_task_state(task_id, TaskStatus.PENDING)
    return {"ok": True, "message": "任务已重试"}