"""
base_adapter.py — Agent 统一包装基类（增强版）

增强内容：
  1. 暴露 capabilities 接口，连接 UnifiedCapabilityRegistry
  2. 异步 run_async 方法（默认同步 run 调用异步版本）
  3. 状态快照方法，用于 AgentPool 追踪
  4. 与 cluster_orchestrator 兼容的 execute 方法
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import time

from backend.core.task_schema import AgentTask, AgentResult


class BaseAgentAdapter(ABC):
    """
    所有 Agent 的统一包装基类。
    微信中控只调用这个类暴露的方法。

    增强：
      - async run_async() 支持异步执行
      - get_capabilities() 连接 UnifiedCapabilityRegistry
      - get_snapshot() 返回状态快照
      - execute() 供 ClusterOrchestrator 调用
    """

    agent_name: str = "base"
    agent_type: str = "general"
    capabilities: List[str] = []   # 该 Agent 支持的能力列表

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.enabled = True
        self.last_heartbeat = time.time()
        self._total_runs = 0
        self._failed_runs = 0

    # ── 核心抽象方法 ───────────────────────────────────────

    @abstractmethod
    def can_handle(self, task: AgentTask) -> float:
        """
        返回 0~1 的匹配分数。
        分数越高，越适合处理该任务。
        """
        pass

    @abstractmethod
    def run(self, task: AgentTask) -> AgentResult:
        """
        同步执行任务并返回标准结果。
        子类应优先重写 run_async()。
        """
        pass

    # ── 异步执行（子类可重写）──────────────────────────────

    async def run_async(self, task: AgentTask) -> AgentResult:
        """
        异步执行任务。默认调用同步 run()。
        重写以提供真正的异步实现（如 httpx 调用）。
        """
        return self.run(task)

    async def execute(self, goal: str, params: Optional[dict] = None) -> dict:
        """
        ClusterOrchestrator 调用的统一执行接口。
        将 (goal, params) 包装成 AgentTask 并执行。

        Returns:
            {"ok": bool, "result": str, "error": str}
        """
        self._total_runs += 1
        from backend.core.task_schema import AgentTask
        import uuid

        task = AgentTask(
            task_id=f"adp_{uuid.uuid4().hex[:8]}",
            user_id="system",
            source="execute",
            content=goal,
            task_type="general",
            context=params or {},
        )

        try:
            result = await self.run_async(task)
            if result.status in ("completed", "success"):
                return {"ok": True, "result": result.result or "", "error": ""}
            else:
                self._failed_runs += 1
                return {"ok": False, "result": "", "error": result.error or "Unknown error"}
        except Exception as e:
            self._failed_runs += 1
            return {"ok": False, "result": "", "error": str(e)}

    # ── 能力查询 ─────────────────────────────────────────

    def get_capabilities(self) -> List[str]:
        """
        返回该 Agent 支持的能力列表。
        用于 UnifiedCapabilityRegistry 索引。
        """
        return self.capabilities.copy()

    def supports_capability(self, capability: str) -> bool:
        """检查是否支持指定能力"""
        return capability in self.capabilities

    # ── 健康检查 ──────────────────────────────────────────

    def health_check(self) -> Dict[str, Any]:
        """
        检查 Agent 是否可用。
        子类可以重写以提供更详细的健康状态。
        """
        return {
            "agent_name": self.agent_name,
            "enabled": self.enabled,
            "last_heartbeat": self.last_heartbeat,
            "status": "ok" if self.enabled else "disabled",
        }

    def heartbeat(self) -> None:
        """更新心跳时间戳"""
        self.last_heartbeat = time.time()

    # ── 状态快照 ──────────────────────────────────────────

    def get_snapshot(self) -> Dict[str, Any]:
        """
        返回 Agent 状态快照，供 ClusterOrchestrator 的 AgentPool 使用。
        """
        return {
            "agent_id": self.agent_name,
            "name": self.name if hasattr(self, "name") else self.agent_name,
            "status": "idle" if self.enabled else "offline",
            "capabilities": self.capabilities,
            "total_runs": self._total_runs,
            "failed_runs": self._failed_runs,
            "success_rate": (
                round((self._total_runs - self._failed_runs) / max(self._total_runs, 1) * 100, 1)
            ),
            "last_heartbeat": self.last_heartbeat,
        }

    # ── 输入输出标准化 ───────────────────────────────────

    def normalize_input(self, task: AgentTask) -> Dict[str, Any]:
        """
        把统一任务格式转成该 Agent 内部格式。
        子类可以重写。
        """
        return {
            "task_id": task.task_id,
            "content": task.content,
            "task_type": task.task_type,
            "context": task.context,
        }

    def normalize_output(self, task: AgentTask, raw_output: Any) -> AgentResult:
        """
        把 Agent 原始输出转成统一格式。
        子类可以重写。
        """
        return AgentResult(
            task_id=task.task_id,
            agent_name=self.agent_name,
            status="completed",
            result=str(raw_output),
        )

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "agent_name": self.agent_name,
            "agent_type": self.agent_type,
            "capabilities": self.capabilities,
            "enabled": self.enabled,
            "health": self.health_check(),
        }
