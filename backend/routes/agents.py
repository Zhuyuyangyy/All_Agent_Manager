"""Agent routes for agent management and health monitoring."""
import os
import logging
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.models import AgentChoice
from backend.agent_health import HealthMonitor
from backend.openhanako_client import OpenHanakoConfig

logger = logging.getLogger(__name__)
router = APIRouter(tags=["agents"])


@router.get("/agents/status")
def agents_status():
    """Get status of all agents."""
    try:
        result = {}
        # OpenHanako
        try:
            config = OpenHanakoConfig.from_env()
            result["openhanako"] = {
                "name": "OpenHanako",
                "role": "桌面应用专家",
                "status": "configured",
                "url": config.base_url,
                "port": config.port,
            }
        except Exception:
            result["openhanako"] = {
                "name": "OpenHanako",
                "role": "桌面应用专家",
                "status": "unconfigured",
            }
        # OpenClaw
        openclaw_url = os.getenv("OPENCLAW_URL")
        result["openclaw"] = {
            "name": "OpenClaw",
            "role": "代码工程师",
            "status": "configured" if openclaw_url else "unconfigured",
            "url": openclaw_url or "",
        }
        # Hermes
        hermes_url = os.getenv("HERMES_URL")
        result["hermes"] = {
            "name": "Hermes",
            "role": "研究分析师",
            "status": "configured" if hermes_url else "unconfigured",
            "url": hermes_url or "",
        }
        return result
    except Exception as e:
        logger.error(f"[agents] status error: {e}")
        return {
            "openhanako": {"name": "OpenHanako", "status": "error"},
            "openclaw": {"name": "OpenClaw", "status": "error"},
            "hermes": {"name": "Hermes", "status": "error"},
        }


@router.get("/health/summary")
def health_summary(health_monitor: HealthMonitor) -> dict:
    """Get health summary of all agents."""
    try:
        return health_monitor.get_stats_summary()
    except Exception as e:
        logger.error(f"[health] summary error: {e}")
        return {}


@router.get("/health/status")
def health_status(health_monitor: HealthMonitor) -> dict:
    """Get overall health status."""
    try:
        return health_monitor.get_stats_summary()
    except Exception as e:
        logger.error(f"[health] status error: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/health/recovery-history")
def recovery_history(health_monitor: HealthMonitor, limit: int = 20) -> list:
    """Get agent recovery history."""
    try:
        return health_monitor.get_recovery_history(limit=limit)
    except Exception as e:
        logger.error(f"[health] recovery-history error: {e}")
        return []


class DispatchRequest(BaseModel):
    content: str
    user_id: str = "web_user"
    source: str = "web"
    task_type: str = "general"
    project: Optional[str] = None
    priority: str = "normal"
    context: dict = {}


@router.post("/router/dispatch")
async def dispatch_task(
    payload: DispatchRequest,
    agent_router=None,
) -> dict:
    """Dispatch a task through the agent router."""
    from backend.core.task_schema import AgentTask

    task = AgentTask(
        task_id=str(uuid4()),
        user_id=payload.user_id,
        source=payload.source,
        content=payload.content,
        task_type=payload.task_type,
        project=payload.project,
        priority=payload.priority,
        context=payload.context,
    )

    result = agent_router.dispatch(task)
    return result.to_dict()