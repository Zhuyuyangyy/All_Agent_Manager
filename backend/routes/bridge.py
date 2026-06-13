"""Bridge routes for WeChat and QQ integration."""
from typing import Optional
import logging
import json
import os
import re
import zipfile
import tempfile
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel

from backend.models import SkillCreateRequest
from backend.storage import TaskRepository
from backend.skill_memory import SkillMemory, SkillStatus, SkillSource, SkillTemplate
from backend.plugin_manager import PluginManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/bridge", tags=["bridge"])


@router.get("/status")
def bridge_status(bridge_manager=None):
    """Get bridge connection status."""
    try:
        return bridge_manager.get_status()
    except Exception as e:
        logger.error(f"[bridge] status error: {e}")
        return {"connected": False, "error": str(e)}


@router.get("/iliya-status")
def iliya_status(wechat_agent=None, bridge_manager=None):
    """Get iliya status summary for frontend display."""
    try:
        return {
            "ok": True,
            "chats": wechat_agent.get_status_summary(),
            "platform": bridge_manager.get_status(),
        }
    except Exception as e:
        logger.error(f"[bridge] iliya-status error: {e}")
        return {"ok": False, "error": str(e)}


@router.get("/intimacy/{user_id}")
def get_intimacy(user_id: str, wechat_agent=None):
    """Get user intimacy status."""
    try:
        text = wechat_agent.intimacy.get_status_text(user_id)
        profile = wechat_agent.intimacy.get_profile(user_id)
        return {
            "ok": True,
            "level": profile.level,
            "xp": profile.xp,
            "total_xp": profile.total_xp,
            "message_count": profile.message_count,
            "task_count": profile.task_count,
            "rewards": profile.unlocked_rewards,
            "text": text,
        }
    except Exception as e:
        logger.error(f"[intimacy] get error: {e}")
        return {"ok": False, "error": str(e)}


@router.post("/connect")
async def bridge_connect(
    payload: dict,
    bridge_manager=None,
):
    """Connect bridge (WeChat/QQ)."""
    bot_token = payload.get("bot_token", "")
    agent_id = payload.get("agent_id")
    return await bridge_manager.start_wechat(bot_token=bot_token, agent_id=agent_id)


@router.post("/disconnect")
async def bridge_disconnect(
    payload: Optional[dict] = None,
    bridge_manager=None,
):
    """Disconnect bridge."""
    agent_id = payload.get("agent_id") if payload else None
    await bridge_manager.stop_platform("wechat", agent_id=agent_id)
    return {"ok": True, "message": "Bridge disconnected"}


@router.get("/messages")
def bridge_messages(
    bridge_manager=None,
    limit: int = 50,
    offset: int = 0,
    agent_id: Optional[str] = None,
):
    """Get bridge messages."""
    try:
        return bridge_manager.get_messages(limit=limit, offset=offset, agent_id=agent_id)
    except Exception as e:
        logger.error(f"[bridge] messages error: {e}")
        return []


# WeChat-specific routes
wechat_router = APIRouter(prefix="/wechat", tags=["wechat"])


@wechat_router.post("/connect")
async def bridge_wechat_connect(payload: dict, bridge_manager=None):
    """Connect WeChat bridge."""
    bot_token = payload.get("bot_token", "")
    agent_id = payload.get("agent_id")
    result = await bridge_manager.start_wechat(bot_token=bot_token, agent_id=agent_id)
    return {"ok": True, "status": result.status, "agent_id": result.agent_id}


@wechat_router.post("/disconnect")
async def bridge_wechat_disconnect(payload: Optional[dict] = None, bridge_manager=None):
    """Disconnect WeChat bridge."""
    agent_id = payload.get("agent_id") if payload else None
    await bridge_manager.stop_platform("wechat", agent_id=agent_id)
    return {"ok": True, "message": "WeChat disconnected"}


# QQ-specific routes
qq_router = APIRouter(prefix="/qq", tags=["qq"])


@qq_router.post("/connect")
async def bridge_qq_connect(payload: dict, bridge_manager=None):
    """Connect QQ bridge."""
    ws_url = payload.get("ws_url", "ws://127.0.0.1:6700")
    http_url = payload.get("http_url", "http://127.0.0.1:5700")
    access_token = payload.get("access_token") or None
    agent_id = payload.get("agent_id")
    result = await bridge_manager.start_qq(
        ws_url=ws_url,
        http_url=http_url,
        access_token=access_token,
        agent_id=agent_id,
    )
    return {"ok": True, "status": result.status, "agent_id": result.agent_id}


@qq_router.post("/disconnect")
async def bridge_qq_disconnect(payload: Optional[dict] = None, bridge_manager=None):
    """Disconnect QQ bridge."""
    agent_id = payload.get("agent_id") if payload else None
    await bridge_manager.stop_platform("qq", agent_id=agent_id)
    return {"ok": True, "message": "QQ disconnected"}