"""Monitoring and metrics routes."""
import logging
from typing import Optional

from fastapi import APIRouter

from backend.execution_monitor import ExecutionMonitor

logger = logging.getLogger(__name__)
router = APIRouter(tags=["monitoring"])


@router.get("/monitor/status")
def monitor_status(execution_monitor: ExecutionMonitor) -> dict:
    """Get overall execution monitor status."""
    try:
        return execution_monitor.get_stats_summary()
    except Exception as e:
        logger.error(f"[monitor] status error: {e}")
        return {}


@router.get("/monitor/execution-stats")
def execution_stats(execution_monitor: ExecutionMonitor) -> dict:
    """Get execution statistics."""
    try:
        return execution_monitor.get_stats_summary()
    except Exception as e:
        logger.error(f"[monitor] execution-stats error: {e}")
        return {}


@router.get("/monitor/agent-stats")
def agent_stats(execution_monitor: ExecutionMonitor) -> dict:
    """Get per-agent execution statistics."""
    try:
        return execution_monitor.get_agent_stats()
    except Exception as e:
        logger.error(f"[monitor] agent-stats error: {e}")
        return {}


@router.get("/monitor/execution-history")
def execution_history(execution_monitor: ExecutionMonitor, limit: int = 50) -> list:
    """Get execution history."""
    try:
        return execution_monitor.get_history(limit=limit)
    except Exception as e:
        logger.error(f"[monitor] execution-history error: {e}")
        return []


@router.post("/monitor/cleanup")
def cleanup_history(execution_monitor: ExecutionMonitor) -> dict:
    """Cleanup completed executions."""
    count = execution_monitor.cleanup_completed()
    return {"ok": True, "cleaned": count}