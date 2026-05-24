"""
qq_agent.py — QQ 消息处理 Agent

复用 WeChatAgent 的核心逻辑（iliya 人设、子 Agent 调度、亲密度系统）。
QQ 和微信共享同一套处理流程，仅传输层不同。
"""

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from backend.chat import ChatManager
from backend.workers import WorkerClient
from backend.mcp_client import McpClient
from backend.skill_memory import SkillMemory
from backend.plugin_manager import PluginManager
from backend.wechat_agent import WeChatAgent

logger = logging.getLogger(__name__)


class QQAgent:

    def __init__(
        self,
        chat_manager: ChatManager,
        worker_client: WorkerClient,
        mcp_client: McpClient,
        skill_memory: SkillMemory,
        plugin_manager: PluginManager,
        data_dir: Optional[Path] = None,
        agent_router: Optional[Any] = None,
    ):
        self._wechat_agent = WeChatAgent(
            chat_manager=chat_manager,
            worker_client=worker_client,
            mcp_client=mcp_client,
            skill_memory=skill_memory,
            plugin_manager=plugin_manager,
            data_dir=data_dir,
            agent_router=agent_router,
        )
        self._send_callback: Optional[Callable] = None

    @property
    def platform(self) -> str:
        return "qq"

    def set_send_callback(self, callback: Callable):
        self._send_callback = callback
        self._wechat_agent.set_send_callback(callback)

    async def process_message(self, user_text: str, chat_id: str = "", agent_id: Optional[str] = None) -> str:
        logger.info(f"[qq-agent] delegating to wechat_agent: chat_id={chat_id}, text={user_text[:80]}")
        return await self._wechat_agent.process_message(user_text, chat_id, agent_id)

    async def send_proactive(self, chat_id: str, text: str, agent_id: Optional[str] = None):
        if self._send_callback:
            await self._send_callback(chat_id, text, agent_id)

    def get_status_summary(self) -> dict:
        return self._wechat_agent.get_status_summary()

    def start_idle_checker(self):
        self._wechat_agent.start_idle_checker()

    def start_schedule_runner(self):
        self._wechat_agent.start_schedule_runner()

    def add_scheduled_message(self, key: str, hour: int, minute: int, message_key: str):
        self._wechat_agent.add_scheduled_message(key, hour, minute, message_key)

    def remove_scheduled_message(self, key: str):
        self._wechat_agent.remove_scheduled_message(key)


def build_qq_agent(
    chat_manager: ChatManager,
    worker_client: WorkerClient,
    mcp_client: McpClient,
    skill_memory: SkillMemory,
    plugin_manager: PluginManager,
    data_dir: Optional[Path] = None,
    agent_router: Optional[Any] = None,
) -> QQAgent:
    return QQAgent(
        chat_manager=chat_manager,
        worker_client=worker_client,
        mcp_client=mcp_client,
        skill_memory=skill_memory,
        plugin_manager=plugin_manager,
        data_dir=data_dir,
        agent_router=agent_router,
    )
