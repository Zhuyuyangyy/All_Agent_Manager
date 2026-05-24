"""
registry.py — MCP Bus 注册中心

内存存储，初期够用。
后续可替换为 Redis 持久化。
"""

import logging
from typing import Dict, List, Optional
from .models import AgentInfo

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Agent 注册中心 — 支持注册、发现、健康状态"""

    def __init__(self):
        self._agents: Dict[str, AgentInfo] = {}
        self._capability_index: Dict[str, List[str]] = {}  # capability → [agent_id, ...]

    def register(self, agent: AgentInfo) -> dict:
        """注册一个 Agent"""
        self._agents[agent.agent_id] = agent
        # 更新能力索引
        for cap in agent.capabilities:
            if cap not in self._capability_index:
                self._capability_index[cap] = []
            if agent.agent_id not in self._capability_index[cap]:
                self._capability_index[cap].append(agent.agent_id)
        logger.info(f"[Registry] Agent registered: {agent.name} ({agent.agent_id}), capabilities: {agent.capabilities}")
        return {"status": "ok", "agent_id": agent.agent_id}

    def unregister(self, agent_id: str) -> dict:
        """注销一个 Agent"""
        if agent_id not in self._agents:
            return {"status": "error", "message": "Agent not found"}
        agent = self._agents.pop(agent_id)
        # 清理能力索引
        for cap in agent.capabilities:
            if cap in self._capability_index:
                self._capability_index[cap] = [aid for aid in self._capability_index[cap] if aid != agent_id]
        logger.info(f"[Registry] Agent unregistered: {agent.name} ({agent_id})")
        return {"status": "ok"}

    def get_agent(self, agent_id: str) -> Optional[AgentInfo]:
        return self._agents.get(agent_id)

    def find_by_capability(self, capability: str) -> List[AgentInfo]:
        """根据能力发现可用的 Agent"""
        agent_ids = self._capability_index.get(capability, [])
        return [self._agents[aid] for aid in agent_ids if aid in self._agents]

    def find_all(self) -> List[AgentInfo]:
        """列出所有已注册 Agent"""
        return list(self._agents.values())

    def list_capabilities(self) -> List[str]:
        """列出所有已知能力"""
        return list(self._capability_index.keys())

    def update_status(self, agent_id: str, status: str) -> dict:
        """更新 Agent 状态"""
        if agent_id not in self._agents:
            return {"status": "error", "message": "Agent not found"}
        self._agents[agent_id].status = status
        return {"status": "ok", "agent_id": agent_id, "status": status}


# 全局单例
_registry = AgentRegistry()


def get_registry() -> AgentRegistry:
    return _registry