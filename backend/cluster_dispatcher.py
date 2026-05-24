"""
cluster_dispatcher.py — 集群调度器（重构版）

重构 TaskDispatcher 为 ClusterDispatcher：
  1. 保留原有同步任务处理（/submit-task）
  2. 新增集群任务入口（submit_cluster_task）
  3. 连接 ClusterOrchestrator + UnifiedCapabilityRegistry
  4. WorkerFactory：把 agent_id 路由到真实 Worker 执行器
"""

import asyncio
import json
import logging
import time
from typing import Any, Callable, Optional

from backend.models import AgentChoice, TaskStatus
from backend.storage import TaskRepository
from backend.workers import WorkerClient, WorkerResult

logger = logging.getLogger(__name__)


class ClusterDispatcher:
    """
    集群调度器。

    整合原有 TaskDispatcher 的同步任务处理能力
    和 ClusterOrchestrator 的并行多 Agent 调度能力。

    两种工作模式：
      1. 同步模式（legacy）：单个 Agent 执行，保存到 task.db
      2. 集群模式：新任务提交到 orchestrator，全并行执行
    """

    def __init__(
        self,
        repository: TaskRepository,
        worker_client: WorkerClient,
        availability_probe: Callable[[AgentChoice], bool] | None = None,
        execution_monitor: Any | None = None,
        cluster_orchestrator: Any | None = None,
        capability_registry: Any | None = None,
    ):
        self.repository = repository
        self.worker_client = worker_client
        self.availability_probe = availability_probe or (lambda agent: True)
        self.execution_monitor = execution_monitor
        self.cluster_orchestrator = cluster_orchestrator
        self.capability_registry = capability_registry

    # ── 同步模式（兼容旧 API）──────────────────────────────

    def run_sync(self, task_id: str) -> None:
        """同步执行单个任务（兼容原有 /submit-task）"""
        asyncio.run(self.run_task(task_id))

    async def run_task(self, task_id: str) -> None:
        """执行单个同步任务"""
        task = self.repository.get_task(task_id)
        if task is None:
            raise ValueError(f"Task '{task_id}' not found")

        if not self.availability_probe(task.selected_agent):
            self.repository.set_waiting(
                task_id,
                reason="Agent busy; task is waiting for availability",
            )
            return

        self.repository.update_task_state(task_id, TaskStatus.RUNNING)

        if self.execution_monitor:
            self.execution_monitor.start_execution(task_id, task.selected_agent)

        start_time = time.time()
        result = await self.worker_client.run_task(
            task.selected_agent, task_id, task.goal
        )
        duration = time.time() - start_time

        if result.ok:
            self.repository.complete_task(task_id, result_payload=result.payload or "")
            if self.execution_monitor:
                self.execution_monitor.complete_execution(task_id, duration)
            return

        error_msg = result.error_message or "Unknown worker failure"
        self.repository.fail_task(task_id, error_message=error_msg)
        if self.execution_monitor:
            self.execution_monitor.fail_execution(task_id, error_msg, duration)

    # ── 集群模式 ────────────────────────────────────────

    async def submit_cluster_task(
        self,
        goal: str,
        max_parallelism: int = 3,
        requested_agent: AgentChoice = AgentChoice.AUTO,
    ) -> str:
        """
        提交集群任务。

        任务会被 ClusterOrchestrator 自动拆分并行执行。

        Returns:
            task_id: 可通过 /api/cluster/status/{task_id} 查询
        """
        if not self.cluster_orchestrator:
            raise RuntimeError("ClusterOrchestrator not initialized")

        # 同时在 task.db 中记录（保持审计一致性）
        from backend.models import TaskCreate, RoutingDecision
        if requested_agent == AgentChoice.AUTO:
            from backend.scheduler import route_task
            routing = route_task(goal, requested_agent)
            selected = routing.selected_agent
        else:
            selected = requested_agent

        task = self.repository.create_task(
            task=TaskCreate(goal=goal, requested_agent=requested_agent),
            selected_agent=selected,
            routing_reason="cluster_mode",
            scheduler_mode="cluster",
            plan_summary="",
        )

        # 提交到集群编排器
        cluster_task_id = await self.cluster_orchestrator.submit(
            goal, max_parallelism=max_parallelism
        )

        # 记录 cluster_task_id 映射
        self.repository.update_task_state(task.id, TaskStatus.RUNNING)

        logger.info(f"[cluster-dispatcher] Submitted {task.id} → cluster task {cluster_task_id}")
        return task.id

    async def run_cluster_task_sync(self, task_id: str) -> None:
        """
        执行集群任务（带结果回写）。
        由 background_tasks 调用，将集群结果写回 task.db。
        """
        task = self.repository.get_task(task_id)
        if not task:
            return

        try:
            if not self.cluster_orchestrator:
                self.repository.fail_task(task_id, error_message="ClusterOrchestrator not initialized")
                return

            result = await self.cluster_orchestrator.get_task_result(
                task.result_payload or task_id  # result_payload 存的是 cluster_task_id
            )

            if result.get("ok") or result.get("status") == "success":
                self.repository.complete_task(
                    task_id,
                    result_payload=json.dumps(result, ensure_ascii=False),
                )
            else:
                self.repository.fail_task(
                    task_id,
                    error_message=result.get("error", "Cluster task failed"),
                )
        except asyncio.TimeoutError:
            self.repository.fail_task(task_id, error_message="Cluster task timeout")
        except Exception as e:
            logger.error(f"[cluster-dispatcher] run_cluster_task_sync error: {e}")
            self.repository.fail_task(task_id, error_message=str(e))


# ── WorkerFactory ────────────────────────────────────────

class AgentWorkerFactory:
    """
    ClusterOrchestrator 的 Worker 工厂。

    给定 (agent_id, task_id, goal)，返回对应的 AgentWorker。
    AgentWorker 实际调用 Router → Adapter → 真实 Agent。
    """

    def __init__(
        self,
        router: Any,          # AgentRouter
        worker_client: WorkerClient,
        cluster_orchestrator: Any = None,
    ):
        self.router = router
        self.worker_client = worker_client
        self.cluster_orchestrator = cluster_orchestrator

    def __call__(self, agent_id: str, task_id: str, goal: str) -> "ClusterAgentWorker":
        return ClusterAgentWorker(
            agent_id=agent_id,
            task_id=task_id,
            goal=goal,
            router=self.router,
            worker_client=self.worker_client,
            cluster_orchestrator=self.cluster_orchestrator,
        )


class ClusterAgentWorker:
    """
    ClusterOrchestrator 调用的 Agent 执行器。

    将 ClusterOrchestrator 的 (agent_id, task_id, goal)
    转换为 AgentRouter.dispatch() 调用。
    """

    def __init__(
        self,
        agent_id: str,
        task_id: str,
        goal: str,
        router: Any,           # AgentRouter
        worker_client: WorkerClient,
        cluster_orchestrator: Any = None,
    ):
        self.agent_id = agent_id
        self.task_id = task_id
        self.goal = goal
        self.router = router
        self.worker_client = worker_client
        self.cluster_orchestrator = cluster_orchestrator

    async def run(self) -> str:
        """执行任务，返回结果文本"""
        from backend.core.task_schema import AgentTask

        task = AgentTask(
            task_id=self.task_id,
            content=self.goal,
            task_type="cluster_subtask",
            context={"agent_id": self.agent_id},
        )

        # 尝试路由到 Agent
        try:
            adapter = self.router.get_agent(self.agent_id)
            if adapter:
                result = await self.router.dispatch_async(task)
                return result.result or str(result.error or "empty result")

            # Adapter 未注册，降级到 WorkerClient
            result = await self.worker_client.run_task(
                AgentChoice.HERMES, self.task_id, self.goal
            )
            if result.ok:
                return result.payload or ""
            else:
                raise RuntimeError(result.error_message or "Worker failed")

        except Exception as e:
            logger.error(f"[cluster-worker] {self.agent_id} failed: {e}")
            raise RuntimeError(f"{self.agent_id} error: {e}") from e
