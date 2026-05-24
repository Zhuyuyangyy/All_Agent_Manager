"""
agent_health.py — Agent 健康监控模块

监控各 Agent 的运行状态，检测故障并尝试自动恢复。
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Callable

from backend.models import AgentChoice


class HealthStatus(StrEnum):
    """健康状态"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class RecoveryAction(StrEnum):
    """恢复动作"""
    NONE = "none"
    RESTART = "restart"
    FAILOVER = "failover"
    ALERT = "alert"


@dataclass
class HealthCheckResult:
    """健康检查结果"""
    agent: AgentChoice
    status: HealthStatus
    message: str = ""
    latency_ms: float = 0
    checked_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "agent": self.agent.value,
            "status": self.status.value,
            "message": self.message,
            "latency_ms": round(self.latency_ms, 2),
            "checked_at": self.checked_at,
            "metadata": self.metadata,
        }


@dataclass
class AgentHealthState:
    """Agent 健康状态"""
    agent: AgentChoice
    status: HealthStatus = HealthStatus.UNKNOWN
    last_check: str | None = None
    last_healthy: str | None = None
    consecutive_failures: int = 0
    total_checks: int = 0
    total_failures: int = 0
    avg_latency_ms: float = 0
    recovery_action: RecoveryAction = RecoveryAction.NONE
    error_history: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "agent": self.agent.value,
            "status": self.status.value,
            "last_check": self.last_check,
            "last_healthy": self.last_healthy,
            "consecutive_failures": self.consecutive_failures,
            "total_checks": self.total_checks,
            "total_failures": self.total_failures,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "recovery_action": self.recovery_action.value,
            "error_history": self.error_history[-5:],  # 最近5条错误
        }


class HealthChecker:
    """
    Agent 健康检查器。
    定期检查各 Agent 的可用性。
    """

    def __init__(self):
        self._checks: dict[AgentChoice, Callable[[], Any]] = {}

    def register_check(self, agent: AgentChoice, check_fn: Callable[[], Any]) -> None:
        """注册健康检查函数"""
        self._checks[agent] = check_fn

    async def check(self, agent: AgentChoice) -> HealthCheckResult:
        """执行单个 Agent 的健康检查"""
        check_fn = self._checks.get(agent)
        if not check_fn:
            return HealthCheckResult(
                agent=agent,
                status=HealthStatus.UNKNOWN,
                message="No health check registered",
            )

        start_time = time.time()
        try:
            # 支持同步和异步检查函数
            if asyncio.iscoroutinefunction(check_fn):
                result = await check_fn()
            else:
                result = check_fn()

            latency = (time.time() - start_time) * 1000

            if result is True or (isinstance(result, dict) and result.get("ok", False)):
                return HealthCheckResult(
                    agent=agent,
                    status=HealthStatus.HEALTHY,
                    message="Agent is responding",
                    latency_ms=latency,
                )
            elif isinstance(result, dict):
                return HealthCheckResult(
                    agent=agent,
                    status=HealthStatus.DEGRADED,
                    message=result.get("error", "Partial health"),
                    latency_ms=latency,
                    metadata=result,
                )
            else:
                return HealthCheckResult(
                    agent=agent,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Unexpected check result: {result}",
                    latency_ms=latency,
                )
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            return HealthCheckResult(
                agent=agent,
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                latency_ms=latency,
            )

    async def check_all(self) -> list[HealthCheckResult]:
        """检查所有已注册的 Agent"""
        results = []
        for agent in self._checks:
            result = await self.check(agent)
            results.append(result)
        return results


class HealthMonitor:
    """
    Agent 健康监控器。
    持续监控 Agent 状态，检测故障并触发恢复。
    """

    def __init__(
        self,
        check_interval: float = 60,
        failure_threshold: int = 3,
        recovery_enabled: bool = True,
    ):
        self.check_interval = check_interval
        self.failure_threshold = failure_threshold
        self.recovery_enabled = recovery_enabled

        self._checker = HealthChecker()
        self._states: dict[AgentChoice, AgentHealthState] = {}
        self._running = False
        self._task: asyncio.Task | None = None

        # 回调函数
        self._on_status_change: Callable[[AgentChoice, HealthStatus, HealthStatus], None] | None = None
        self._on_recovery: Callable[[AgentChoice, RecoveryAction], None] | None = None
        self._on_agent_recovered: Callable[[AgentChoice], None] | None = None

    def set_callbacks(
        self,
        on_status_change: Callable[[AgentChoice, HealthStatus, HealthStatus], None] | None = None,
        on_recovery: Callable[[AgentChoice, RecoveryAction], None] | None = None,
        on_agent_recovered: Callable[[AgentChoice], None] | None = None,
    ) -> None:
        """设置回调函数"""
        self._on_status_change = on_status_change
        self._on_recovery = on_recovery
        self._on_agent_recovered = on_agent_recovered

    def register_agent(self, agent: AgentChoice, check_fn: Callable[[], Any]) -> None:
        """注册 Agent 的健康检查函数"""
        self._checker.register_check(agent, check_fn)
        if agent not in self._states:
            self._states[agent] = AgentHealthState(agent=agent)

    async def start(self) -> None:
        """启动健康监控"""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        """停止健康监控"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _monitor_loop(self) -> None:
        """监控循环"""
        while self._running:
            try:
                await asyncio.sleep(self.check_interval)
                await self.check_all()
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def check_all(self) -> dict[AgentChoice, HealthCheckResult]:
        """检查所有 Agent 的健康状态"""
        results = {}
        for agent, state in self._states.items():
            result = await self._checker.check(agent)
            results[agent] = result

            # 更新状态
            old_status = state.status
            state.status = result.status
            state.last_check = result.checked_at
            state.total_checks += 1

            if result.status == HealthStatus.HEALTHY:
                state.last_healthy = result.checked_at
                state.consecutive_failures = 0
                # 更新平均延迟
                total = state.total_checks
                state.avg_latency_ms = (
                    state.avg_latency_ms * (total - 1) + result.latency_ms
                ) / total
            else:
                state.consecutive_failures += 1
                state.total_failures += 1
                state.error_history.append(result.message)
                if len(state.error_history) > 20:
                    state.error_history = state.error_history[-20:]

            # 状态变化通知
            if old_status != result.status and self._on_status_change:
                self._on_status_change(agent, old_status, result.status)
            
            # 检测 Agent 恢复（从非健康状态恢复到健康状态）
            if (old_status in (HealthStatus.UNHEALTHY, HealthStatus.DEGRADED) and 
                result.status == HealthStatus.HEALTHY and 
                self._on_agent_recovered):
                self._on_agent_recovered(agent)

            # 检查是否需要恢复
            if self.recovery_enabled and state.consecutive_failures >= self.failure_threshold:
                action = self._determine_recovery_action(agent, state)
                if action != RecoveryAction.NONE:
                    state.recovery_action = action
                    if self._on_recovery:
                        self._on_recovery(agent, action)

        return results

    def _determine_recovery_action(
        self, agent: AgentChoice, state: AgentHealthState
    ) -> RecoveryAction:
        """决定恢复动作"""
        # 连续失败次数越多，恢复动作越激进
        if state.consecutive_failures >= self.failure_threshold * 2:
            return RecoveryAction.ALERT
        elif state.consecutive_failures >= self.failure_threshold:
            return RecoveryAction.RESTART
        return RecoveryAction.NONE

    def get_state(self, agent: AgentChoice) -> AgentHealthState | None:
        """获取 Agent 健康状态"""
        return self._states.get(agent)

    def get_all_states(self) -> dict[str, dict]:
        """获取所有 Agent 的健康状态"""
        return {agent.value: state.to_dict() for agent, state in self._states.items()}

    def get_unhealthy_agents(self) -> list[AgentChoice]:
        """获取所有不健康的 Agent"""
        return [
            agent for agent, state in self._states.items()
            if state.status in (HealthStatus.UNHEALTHY, HealthStatus.DEGRADED)
        ]

    def get_stats_summary(self) -> dict:
        """获取健康统计摘要"""
        healthy = len([s for s in self._states.values() if s.status == HealthStatus.HEALTHY])
        degraded = len([s for s in self._states.values() if s.status == HealthStatus.DEGRADED])
        unhealthy = len([s for s in self._states.values() if s.status == HealthStatus.UNHEALTHY])
        unknown = len([s for s in self._states.values() if s.status == HealthStatus.UNKNOWN])

        return {
            "total_agents": len(self._states),
            "healthy": healthy,
            "degraded": degraded,
            "unhealthy": unhealthy,
            "unknown": unknown,
        }


class AgentRecoveryManager:
    """
    Agent 恢复管理器。
    根据健康监控的结果执行恢复动作。
    """

    def __init__(self):
        self._recovery_strategies: dict[RecoveryAction, Callable] = {}
        self._recovery_history: list[dict] = []

    def register_strategy(
        self, action: RecoveryAction, strategy: Callable[[AgentChoice], Any]
    ) -> None:
        """注册恢复策略"""
        self._recovery_strategies[action] = strategy

    async def execute_recovery(self, agent: AgentChoice, action: RecoveryAction) -> bool:
        """执行恢复动作"""
        strategy = self._recovery_strategies.get(action)
        if not strategy:
            return False

        try:
            if asyncio.iscoroutinefunction(strategy):
                result = await strategy(agent)
            else:
                result = strategy(agent)

            self._recovery_history.append({
                "agent": agent.value,
                "action": action.value,
                "success": bool(result),
                "timestamp": datetime.now().isoformat(),
            })

            return bool(result)
        except Exception as e:
            self._recovery_history.append({
                "agent": agent.value,
                "action": action.value,
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            })
            return False

    def get_recovery_history(self, limit: int = 20) -> list[dict]:
        """获取恢复历史"""
        return self._recovery_history[-limit:]
