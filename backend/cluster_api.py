"""
cluster_api.py — 集群管理 REST API

提供 /api/cluster/* 端点：
  POST   /api/cluster/submit      — 提交集群任务
  GET    /api/cluster/status/{id} — 查询任务状态
  GET    /api/cluster/result/{id} — 获取任务结果（阻塞）
  POST   /api/cluster/cancel/{id} — 取消任务
  GET    /api/cluster/health      — 集群健康状态
  GET    /api/cluster/agents      — Agent 资源池状态
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cluster", tags=["cluster"])


# ── 请求/响应模型 ─────────────────────────────────────────

class ClusterSubmitRequest(BaseModel):
    goal: str
    max_parallelism: int = 3


class ClusterSubmitResponse(BaseModel):
    task_id: str
    message: str


class ClusterStatusResponse(BaseModel):
    task_id: str
    status: str
    done_ratio: float
    total_subtasks: int
    sub_tasks: list
    completed_at: Optional[str] = None


class ClusterResultResponse(BaseModel):
    task_id: str
    status: str
    result: str
    error: Optional[str] = None
    total_duration_ms: float
    sub_tasks: list


class ClusterHealthResponse(BaseModel):
    status: str
    total_agents: int
    idle_agents: int
    active_tasks: int
    total_tasks_submitted: int


# ── 全局 orchestrator 引用（由 app.py 注入） ───────────────

_orchestrator_ref: Optional[Any] = None


def set_orchestrator(orchestrator):
    global _orchestrator_ref
    _orchestrator_ref = orchestrator


def get_orchestrator():
    if _orchestrator_ref is None:
        raise RuntimeError("Cluster orchestrator not initialized")
    return _orchestrator_ref


# ── 路由处理 ──────────────────────────────────────────────

@router.post("/submit", response_model=ClusterSubmitResponse)
async def cluster_submit(req: ClusterSubmitRequest, background_tasks: BackgroundTasks):
    """
    提交一个集群任务。

    任务会自动拆分并行执行，结果通过 task_id 查询。
    """
    try:
        orchestrator = get_orchestrator()
        task_id = await orchestrator.submit(req.goal, max_parallelism=req.max_parallelism)

        logger.info(f"[cluster-api] Task submitted: {task_id}")
        return ClusterSubmitResponse(
            task_id=task_id,
            message=f"任务已提交，等待执行（最多 {req.max_parallelism} 个子任务并行）",
        )
    except Exception as e:
        logger.error(f"[cluster-api] submit error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{task_id}", response_model=ClusterStatusResponse)
async def cluster_status(task_id: str):
    """查询任务执行状态"""
    try:
        orchestrator = get_orchestrator()
        status = await orchestrator.get_task_status(task_id)
        if "error" in status:
            raise HTTPException(status_code=404, detail=status["error"])
        return ClusterStatusResponse(**status)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[cluster-api] status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/result/{task_id}", response_model=ClusterResultResponse)
async def cluster_result(task_id: str, timeout: float = 60.0):
    """
    获取任务最终结果。

    如果任务未完成，会等待完成（最长 timeout 秒）。
    """
    try:
        orchestrator = get_orchestrator()
        # 使用 asyncio.wait_for 防止永久阻塞
        result = await asyncio.wait_for(
            orchestrator.get_task_result(task_id),
            timeout=timeout,
        )
        if "error" in result and result.get("status") == "Task not found":
            raise HTTPException(status_code=404, detail=result["error"])
        return ClusterResultResponse(**result)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=f"Timeout after {timeout}s — task still running")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[cluster-api] result error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel/{task_id}")
async def cluster_cancel(task_id: str):
    """取消任务"""
    try:
        orchestrator = get_orchestrator()
        result = await orchestrator.cancel_task(task_id)
        return result
    except Exception as e:
        logger.error(f"[cluster-api] cancel error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health", response_model=ClusterHealthResponse)
async def cluster_health():
    """集群整体健康状态"""
    try:
        orchestrator = get_orchestrator()
        status = orchestrator.get_cluster_status()
        return ClusterHealthResponse(
            status="ok",
            total_agents=status["total_agents"],
            idle_agents=status["idle_agents"],
            active_tasks=status["active_tasks"],
            total_tasks_submitted=status["total_tasks_submitted"],
        )
    except Exception as e:
        logger.error(f"[cluster-api] health error: {e}")
        return ClusterHealthResponse(
            status=f"error: {e}",
            total_agents=0,
            idle_agents=0,
            active_tasks=0,
            total_tasks_submitted=0,
        )


@router.get("/agents")
async def cluster_agents():
    """Agent 资源池状态"""
    try:
        orchestrator = get_orchestrator()
        status = orchestrator.get_cluster_status()
        return {
            "agents": status["agents"],
            "idle_count": status["idle_agents"],
            "running_subtasks": status["running_subtasks"],
        }
    except Exception as e:
        logger.error(f"[cluster-api] agents error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/capabilities")
async def cluster_capabilities():
    """查询所有注册的能力（来自 Registry）"""
    try:
        from backend.app import app as fastapi_app
        registry = getattr(fastapi_app.state, "_capability_registry", None)
        if not registry:
            return {"capabilities": [], "mcp_tools": []}

        caps = registry.get_all_capabilities()
        mcp_tools = registry.list_mcp_tools()

        return {
            "capabilities": [c.to_dict() for c in caps],
            "mcp_tools": [t.to_dict() for t in mcp_tools],
        }
    except Exception as e:
        logger.error(f"[cluster-api] capabilities error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/slash-commands")
async def cluster_slash_commands():
    """获取所有可用的斜杠命令（来自 Skill）"""
    try:
        from backend.app import app as fastapi_app
        slash_registry = getattr(fastapi_app.state, "_slash_registry", None)
        if not slash_registry:
            return {"commands": [], "by_category": {}}

        cmds = slash_registry.get_all_commands()
        by_cat = slash_registry.get_commands_by_category()

        return {
            "commands": [
                {
                    "name": c.name,
                    "description": c.description,
                    "args_hint": c.args_hint,
                    "category": c.category,
                    "examples": c.examples,
                }
                for c in cmds
            ],
            "by_category": {
                cat: [
                    {"name": c.name, "description": c.description, "args_hint": c.args_hint}
                    for c in cmds
                ]
                for cat, cmds in by_cat.items()
            },
        }
    except Exception as e:
        logger.error(f"[cluster-api] slash-commands error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
