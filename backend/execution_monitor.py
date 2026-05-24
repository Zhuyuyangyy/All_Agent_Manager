"""
execution_monitor.py — 任务执行监控模块

提供 retry、timeout、异常处理、执行日志等功能。
监控任务执行状态，自动处理失败重试和超时。
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Callable

from backend.models import AgentChoice, TaskStatus


class ExecutionEvent(StrEnum):
    """执行事件类型"""
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class ExecutionRecord:
    """单次执行记录"""
    task_id: str
    agent: AgentChoice
    event: ExecutionEvent
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    duration: float | None = None  # 秒
    error: str | None = None
    retry_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "agent": self.agent.value,
            "event": self.event.value,
            "timestamp": self.timestamp,
            "duration": self.duration,
            "error": self.error,
            "retry_count": self.retry_count,
            "metadata": self.metadata,
        }


@dataclass
class TaskExecutionState:
    """任务执行状态"""
    task_id: str
    agent: AgentChoice
    status: str = "pending"
    retry_count: int = 0
    max_retries: int = 3
    timeout_seconds: float = 300  # 5分钟默认超时
    started_at: str | None = None
    last_heartbeat: str | None = None
    error_history: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "agent": self.agent.value,
            "status": self.status,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "timeout_seconds": self.timeout_seconds,
            "started_at": self.started_at,
            "last_heartbeat": self.last_heartbeat,
            "error_history": self.error_history,
        }


class ExecutionMonitor:
    """
    任务执行监控器。
    跟踪任务执行状态，处理 retry、timeout、异常。
    """

    def __init__(
        self,
        default_timeout: float = 300,
        default_max_retries: int = 3,
        heartbeat_interval: float = 30,
    ):
        self.default_timeout = default_timeout
        self.default_max_retries = default_max_retries
        self.heartbeat_interval = heartbeat_interval

        # 任务执行状态
        self._states: dict[str, TaskExecutionState] = {}

        # 执行历史
        self._history: list[ExecutionRecord] = []
        self._max_history = 500

        # Agent 统计
        self._agent_stats: dict[str, AgentStats] = {}

        # 回调函数
        self._on_retry: Callable[[str, int], None] | None = None
        self._on_timeout: Callable[[str], None] | None = None
        self._on_failure: Callable[[str, str], None] | None = None

    def set_callbacks(
        self,
        on_retry: Callable[[str, int], None] | None = None,
        on_timeout: Callable[[str], None] | None = None,
        on_failure: Callable[[str, str], None] | None = None,
    ) -> None:
        """设置回调函数"""
        self._on_retry = on_retry
        self._on_timeout = on_timeout
        self._on_failure = on_failure

    def start_execution(
        self,
        task_id: str,
        agent: AgentChoice,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> TaskExecutionState:
        """开始执行任务"""
        state = TaskExecutionState(
            task_id=task_id,
            agent=agent,
            status="running",
            timeout_seconds=timeout or self.default_timeout,
            max_retries=max_retries if max_retries is not None else self.default_max_retries,
            started_at=datetime.now().isoformat(),
            last_heartbeat=datetime.now().isoformat(),
        )
        self._states[task_id] = state

        self._record_event(ExecutionRecord(
            task_id=task_id,
            agent=agent,
            event=ExecutionEvent.STARTED,
        ))

        return state

    def complete_execution(self, task_id: str, duration: float | None = None) -> None:
        """完成任务执行"""
        state = self._states.get(task_id)
        if not state:
            return

        state.status = "completed"
        agent_name = state.agent.value

        # 计算实际时长
        if duration is None and state.started_at:
            try:
                start = datetime.fromisoformat(state.started_at)
                duration = (datetime.now() - start).total_seconds()
            except Exception:
                duration = 0

        self._record_event(ExecutionRecord(
            task_id=task_id,
            agent=state.agent,
            event=ExecutionEvent.COMPLETED,
            duration=duration,
            retry_count=state.retry_count,
        ))

        # 更新 Agent 统计
        self._update_agent_stats(agent_name, success=True, duration=duration or 0)

    def fail_execution(self, task_id: str, error: str, duration: float | None = None) -> bool:
        """
        任务执行失败。
        返回 True 表示将进行重试，False 表示已达到最大重试次数。
        """
        state = self._states.get(task_id)
        if not state:
            return False

        state.error_history.append(error)

        # 计算实际时长
        if duration is None and state.started_at:
            try:
                start = datetime.fromisoformat(state.started_at)
                duration = (datetime.now() - start).total_seconds()
            except Exception:
                duration = 0

        # 检查是否可以重试
        if state.retry_count < state.max_retries:
            state.retry_count += 1
            state.status = "retrying"

            self._record_event(ExecutionRecord(
                task_id=task_id,
                agent=state.agent,
                event=ExecutionEvent.RETRYING,
                duration=duration,
                error=error,
                retry_count=state.retry_count,
            ))

            # 触发回调
            if self._on_retry:
                self._on_retry(task_id, state.retry_count)

            return True
        else:
            state.status = "failed"

            self._record_event(ExecutionRecord(
                task_id=task_id,
                agent=state.agent,
                event=ExecutionEvent.FAILED,
                duration=duration,
                error=error,
                retry_count=state.retry_count,
            ))

            # 更新 Agent 统计
            self._update_agent_stats(state.agent.value, success=False, duration=duration or 0)

            # 触发回调
            if self._on_failure:
                self._on_failure(task_id, error)

            return False

    def timeout_execution(self, task_id: str) -> bool:
        """
        任务执行超时。
        返回 True 表示将进行重试，False 表示已达到最大重试次数。
        """
        state = self._states.get(task_id)
        if not state:
            return False

        error = f"Task timed out after {state.timeout_seconds} seconds"

        self._record_event(ExecutionRecord(
            task_id=task_id,
            agent=state.agent,
            event=ExecutionEvent.TIMEOUT,
            error=error,
            retry_count=state.retry_count,
        ))

        # 触发回调
        if self._on_timeout:
            self._on_timeout(task_id)

        return self.fail_execution(task_id, error)

    def cancel_execution(self, task_id: str) -> None:
        """取消任务执行"""
        state = self._states.get(task_id)
        if not state:
            return

        state.status = "cancelled"

        self._record_event(ExecutionRecord(
            task_id=task_id,
            agent=state.agent,
            event=ExecutionEvent.CANCELLED,
            retry_count=state.retry_count,
        ))

    def update_heartbeat(self, task_id: str) -> None:
        """更新任务心跳"""
        state = self._states.get(task_id)
        if state:
            state.last_heartbeat = datetime.now().isoformat()

    def check_timeouts(self) -> list[str]:
        """检查超时任务，返回超时的任务 ID 列表"""
        timeout_tasks = []
        now = datetime.now()

        for task_id, state in self._states.items():
            if state.status != "running":
                continue

            if state.started_at:
                try:
                    start = datetime.fromisoformat(state.started_at)
                    elapsed = (now - start).total_seconds()
                    if elapsed > state.timeout_seconds:
                        timeout_tasks.append(task_id)
                except Exception:
                    pass

        return timeout_tasks

    def check_stale_heartbeats(self) -> list[str]:
        """检查心跳过期的任务"""
        stale_tasks = []
        now = datetime.now()

        for task_id, state in self._states.items():
            if state.status != "running":
                continue

            if state.last_heartbeat:
                try:
                    last = datetime.fromisoformat(state.last_heartbeat)
                    elapsed = (now - last).total_seconds()
                    if elapsed > self.heartbeat_interval * 3:  # 3倍心跳间隔视为过期
                        stale_tasks.append(task_id)
                except Exception:
                    pass

        return stale_tasks

    def get_state(self, task_id: str) -> TaskExecutionState | None:
        """获取任务执行状态"""
        return self._states.get(task_id)

    def get_running_tasks(self) -> list[TaskExecutionState]:
        """获取所有正在执行的任务"""
        return [s for s in self._states.values() if s.status == "running"]

    def get_retrying_tasks(self) -> list[TaskExecutionState]:
        """获取所有等待重试的任务"""
        return [s for s in self._states.values() if s.status == "retrying"]

    def cleanup_completed(self, max_age_seconds: float = 3600) -> int:
        """清理已完成的任务状态"""
        now = datetime.now()
        to_remove = []

        for task_id, state in self._states.items():
            if state.status in ("completed", "failed", "cancelled"):
                if state.started_at:
                    try:
                        start = datetime.fromisoformat(state.started_at)
                        if (now - start).total_seconds() > max_age_seconds:
                            to_remove.append(task_id)
                    except Exception:
                        pass

        for task_id in to_remove:
            del self._states[task_id]

        return len(to_remove)

    def _record_event(self, record: ExecutionRecord) -> None:
        """记录执行事件"""
        self._history.append(record)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    def _update_agent_stats(self, agent_name: str, success: bool, duration: float) -> None:
        """更新 Agent 统计"""
        if agent_name not in self._agent_stats:
            self._agent_stats[agent_name] = AgentStats()

        stats = self._agent_stats[agent_name]
        stats.total_tasks += 1
        if success:
            stats.completed_tasks += 1
            stats.total_duration += duration
            stats.avg_duration = stats.total_duration / stats.completed_tasks
        else:
            stats.failed_tasks += 1
        stats.last_updated = datetime.now().isoformat()

    def get_history(self, limit: int = 50) -> list[dict]:
        """获取执行历史"""
        return [r.to_dict() for r in self._history[-limit:]]

    def get_agent_stats(self) -> dict[str, dict]:
        """获取 Agent 统计"""
        return {name: stats.to_dict() for name, stats in self._agent_stats.items()}

    def get_stats_summary(self) -> dict:
        """获取统计摘要"""
        running = len([s for s in self._states.values() if s.status == "running"])
        retrying = len([s for s in self._states.values() if s.status == "retrying"])
        completed = len([s for s in self._states.values() if s.status == "completed"])
        failed = len([s for s in self._states.values() if s.status == "failed"])

        return {
            "running": running,
            "retrying": retrying,
            "completed": completed,
            "failed": failed,
            "total_tracked": len(self._states),
            "history_size": len(self._history),
        }


@dataclass
class AgentStats:
    """Agent 执行统计"""
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    total_duration: float = 0
    avg_duration: float = 0
    last_updated: str = ""

    def to_dict(self) -> dict:
        return {
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "total_duration": round(self.total_duration, 2),
            "avg_duration": round(self.avg_duration, 2),
            "success_rate": round(
                self.completed_tasks / self.total_tasks * 100, 1
            ) if self.total_tasks > 0 else 0,
            "last_updated": self.last_updated,
        }


class TimeoutChecker:
    """
    后台超时检查器。
    定期检查执行中的任务是否超时。
    """

    def __init__(
        self,
        monitor: ExecutionMonitor,
        check_interval: float = 10,
        on_timeout: Callable[[str], None] | None = None,
    ):
        self.monitor = monitor
        self.check_interval = check_interval
        self._on_timeout = on_timeout
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """启动超时检查"""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._check_loop())

    async def stop(self) -> None:
        """停止超时检查"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _check_loop(self) -> None:
        """检查循环"""
        while self._running:
            try:
                await asyncio.sleep(self.check_interval)

                # 检查超时
                timeout_tasks = self.monitor.check_timeouts()
                for task_id in timeout_tasks:
                    self.monitor.timeout_execution(task_id)
                    if self._on_timeout:
                        self._on_timeout(task_id)

                # 检查心跳过期
                stale_tasks = self.monitor.check_stale_heartbeats()
                for task_id in stale_tasks:
                    self.monitor.timeout_execution(task_id)
                    if self._on_timeout:
                        self._on_timeout(task_id)

            except asyncio.CancelledError:
                break
            except Exception:
                pass
