"""
cluster_orchestrator.py — Agent 集群调度核心

核心能力：
  1. 多 Agent 并行执行：一个大任务拆成多个子任务，同时调度给不同 Agent
  2. Work Stealing：空闲 Agent 主动从队列偷任务
  3. 结果聚合：将多个子 Agent 的结果合并返回
  4. 统一能力路由：根据任务能力需求选择最合适的 Agent

设计原则：
  - 任务(Task) → 子任务拆解 → 并行调度 → 结果聚合
  - Agent 不再是单一调度目标，而是可复用的执行资源池
  - 支持 Skill/MCP/Plugin 能力的统一路由
"""

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ── 任务状态 ────────────────────────────────────────────────

class SubTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ── 数据模型 ────────────────────────────────────────────────

@dataclass
class SubTask:
    """子任务 — 可被单个 Agent 执行的工作单元"""
    id: str
    description: str                      # 子任务描述
    assigned_agent: str                   # 分配到的 Agent ID
    parent_id: str                        # 父任务 ID
    status: SubTaskStatus = SubTaskStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    retries: int = 0
    max_retries: int = 2
    capabilities_required: list[str] = field(default_factory=list)  # 所需能力

    def duration_ms(self) -> float:
        if self.started_at and self.completed_at:
            s = datetime.fromisoformat(self.completed_at)
            e = datetime.fromisoformat(self.started_at)
            return (s - e).total_seconds() * 1000
        return 0


@dataclass
class ClusterTask:
    """顶层任务 — 包含多个子任务的并行执行上下文"""
    id: str
    goal: str                             # 原始任务描述
    sub_tasks: list[SubTask] = field(default_factory=list)
    status: SubTaskStatus = SubTaskStatus.PENDING
    result: Optional[str] = None           # 聚合结果
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    total_duration_ms: float = 0

    @property
    def is_done(self) -> bool:
        return self.status in (SubTaskStatus.SUCCESS, SubTaskStatus.FAILED, SubTaskStatus.CANCELLED)

    @property
    def done_ratio(self) -> float:
        if not self.sub_tasks:
            return 0.0
        done = sum(1 for st in self.sub_tasks if st.status != SubTaskStatus.PENDING)
        return done / len(self.sub_tasks)


@dataclass
class AgentSnapshot:
    """Agent 资源池快照"""
    agent_id: str
    name: str
    status: str                           # idle | busy | offline
    current_task_id: Optional[str] = None
    current_sub_task_id: Optional[str] = None
    capabilities: list[str] = field(default_factory=list)
    avg_response_time_ms: float = 0
    total_tasks_completed: int = 0
    success_rate: float = 1.0
    last_heartbeat: str = field(default_factory=lambda: datetime.now().isoformat())


# ── 任务拆分策略 ─────────────────────────────────────────────

class TaskSplitter:
    """分析任务描述，自动拆分为可并行的子任务"""

    @staticmethod
    def split(task_goal: str, agent_count_hint: int = 3) -> list[dict]:
        """将任务拆分为子任务描述列表

        Returns:
            list of {"description": str, "capabilities": list[str], "agent_hint": str}
        """
        goal_lower = task_goal.lower()
        subtasks = []

        # ── 代码相关：按语言/模块拆分 ──────────────────────────────
        code_indicators = {"python", "js", "javascript", "ts", "typescript", "java",
                           "go", "rust", "c++", "cpp", "写代码", "编程", "实现"}
        if any(ind in goal_lower for ind in code_indicators):
            # 拆分为：分析 → 实现 → 测试
            subtasks.append({
                "description": f"[分析] 分析需求：{task_goal}",
                "capabilities": ["analysis", "research"],
                "agent_hint": "hermes",
            })
            subtasks.append({
                "description": f"[实现] 编写代码：{task_goal}",
                "capabilities": ["code", "implement"],
                "agent_hint": "openclaw",
            })
            subtasks.append({
                "description": f"[测试] 验证代码：{task_goal}",
                "capabilities": ["test", "debug"],
                "agent_hint": "openclaw",
            })
            return subtasks

        # ── 研究/调研：按维度拆分 ──────────────────────────────
        research_indicators = {"研究", "调研", "分析", "对比", "survey", "research",
                               "analyze", "compare", "报告", "report"}
        if any(ind in goal_lower for ind in research_indicators):
            # 拆分为：搜索 → 分析 → 总结
            subtasks.append({
                "description": f"[信息收集] 搜索相关资料：{task_goal}",
                "capabilities": ["web_search", "knowledge_retrieval"],
                "agent_hint": "hermes",
            })
            subtasks.append({
                "description": f"[深度分析] 分析整理资料：{task_goal}",
                "capabilities": ["analysis", "reasoning"],
                "agent_hint": "hermes",
            })
            subtasks.append({
                "description": f"[报告撰写] 整理输出报告：{task_goal}",
                "capabilities": ["documentation", "summary"],
                "agent_hint": "hermes",
            })
            return subtasks

        # ── 文件/数据处理：按阶段拆分 ─────────────────────────
        file_indicators = {"文件", "处理", "整理", "导出", "导入", "批量", "file",
                          "process", "batch", "整理文件"}
        if any(ind in goal_lower for ind in file_indicators):
            subtasks.append({
                "description": f"[文件扫描] 扫描分析文件：{task_goal}",
                "capabilities": ["file_operations", "filesystem"],
                "agent_hint": "openhanako",
            })
            subtasks.append({
                "description": f"[数据处理] 执行处理操作：{task_goal}",
                "capabilities": ["data_processing"],
                "agent_hint": "openclaw",
            })
            return subtasks

        # ── 默认：简单任务不拆分，直接返回单任务 ───────────────
        return [{
            "description": task_goal,
            "capabilities": [],
            "agent_hint": "auto",
        }]

    @staticmethod
    def estimate_parallelism(task_goal: str) -> int:
        """估算该任务最适合的并行度"""
        splitter = TaskSplitter()
        subs = splitter.split(task_goal, agent_count_hint=999)
        return len(subs)


# ── Agent 资源池 ───────────────────────────────────────────

class AgentPool:
    """Agent 资源池 — 追踪所有可用 Agent 的状态"""

    def __init__(self):
        self._agents: dict[str, AgentSnapshot] = {}
        self._lock = asyncio.Lock()

    def register(self, agent_id: str, name: str, capabilities: list[str] = None) -> None:
        self._agents[agent_id] = AgentSnapshot(
            agent_id=agent_id,
            name=name,
            status="idle",
            capabilities=capabilities or [],
        )

    def get_idle_agents(self) -> list[AgentSnapshot]:
        return [a for a in self._agents.values() if a.status == "idle"]

    def get_agent(self, agent_id: str) -> Optional[AgentSnapshot]:
        return self._agents.get(agent_id)

    def get_all(self) -> list[AgentSnapshot]:
        return list(self._agents.values())

    async def assign_task(self, agent_id: str, task_id: str, sub_task_id: str) -> bool:
        async with self._lock:
            agent = self._agents.get(agent_id)
            if not agent or agent.status != "idle":
                return False
            agent.status = "busy"
            agent.current_task_id = task_id
            agent.current_sub_task_id = sub_task_id
            return True

    async def release_task(self, agent_id: str, success: bool) -> None:
        async with self._lock:
            agent = self._agents.get(agent_id)
            if not agent:
                return
            agent.status = "idle"
            agent.current_task_id = None
            agent.current_sub_task_id = None
            agent.total_tasks_completed += 1
            if agent.total_tasks_completed > 0:
                agent.success_rate = (
                    agent.success_rate * (agent.total_tasks_completed - 1) +
                    (1.0 if success else 0.0)
                ) / agent.total_tasks_completed

    def best_agent_for_capabilities(
        self,
        required_capabilities: list[str],
        prefer_idle: bool = True,
    ) -> Optional[AgentSnapshot]:
        """选择最合适的 Agent 来满足所需能力"""
        candidates = list(self._agents.values())
        if not candidates:
            return None

        scored = []
        for agent in candidates:
            if prefer_idle and agent.status != "idle":
                continue
            score = 0
            for cap in required_capabilities:
                if cap in agent.capabilities:
                    score += 10
            if agent.capabilities:
                coverage = len(set(required_capabilities) & set(agent.capabilities))
                score += coverage * 5
            score += agent.success_rate * 10
            if score > 0:
                scored.append((score, agent))

        if not scored:
            # 无匹配能力时返回任意空闲 Agent
            idle = [a for a in candidates if a.status == "idle"]
            return idle[0] if idle else None

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]


# ── 结果聚合器 ──────────────────────────────────────────────

class ResultAggregator:
    """将多个子任务结果聚合成单一响应"""

    @staticmethod
    def aggregate(sub_tasks: list[SubTask]) -> tuple[str, Optional[str]]:
        """聚合结果，返回 (聚合文本, 错误信息)"""
        if not sub_tasks:
            return "", None

        succeeded = [st for st in sub_tasks if st.status == SubTaskStatus.SUCCESS]
        failed = [st for st in sub_tasks if st.status == SubTaskStatus.FAILED]

        if not succeeded and failed:
            errors = "\n".join(f"[{st.id}] {st.error or 'unknown'}" for st in failed)
            return "", f"所有子任务均失败：\n{errors}"

        parts = []
        for st in succeeded:
            if st.result:
                parts.append(f"## [{st.id}] {st.description}\n{st.result}")

        summary = f"✅ 完成 {len(succeeded)}/{len(sub_tasks)} 个子任务"
        if failed:
            summary += f"（{len(failed)} 个失败）"

        return summary + "\n\n" + "\n\n".join(parts), None


# ── 集群调度器核心 ─────────────────────────────────────────

class ClusterOrchestrator:
    """
    Agent 集群调度器。

    核心流程：
      submit(goal) → split → 并行调度 → Work Stealing → 聚合 → 返回

    支持：
      - 自动拆分大任务为并行子任务
      - 子任务分配给最合适的 Agent
      - 空闲 Agent 从队列偷任务（Work Stealing）
      - 失败自动重试
      - 结果聚合
    """

    def __init__(
        self,
        agent_registry: Callable[[], "UnifiedCapabilityRegistry"],
        worker_factory: Callable[[str, str, str], "AgentWorker"],
    ):
        """
        Args:
            agent_registry: 返回能力注册中心的工厂函数（避免循环导入）
            worker_factory: (agent_id, task_id, goal) → AgentWorker
        """
        self._get_registry = agent_registry
        self._worker_factory = worker_factory
        self._pool = AgentPool()
        self._tasks: dict[str, ClusterTask] = {}
        self._sub_tasks: dict[str, SubTask] = {}
        self._running_sub_tasks: dict[str, asyncio.Task] = {}
        self._stealing_queue: asyncio.Queue[str] = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._stealing_enabled = True
        self._stealing_task: Optional[asyncio.Task] = None

        self._init_agent_pool()

    async def start(self) -> None:
        if self._stealing_task is None:
            self._stealing_task = asyncio.create_task(self._work_stealing_loop())

    async def shutdown(self) -> None:
        self._stealing_enabled = False
        if self._stealing_task is not None:
            self._stealing_task.cancel()
            try:
                await self._stealing_task
            except asyncio.CancelledError:
                pass
            self._stealing_task = None

    def _init_agent_pool(self) -> None:
        """初始化预定义的 Agent 资源"""
        self._pool.register("openclaw", "OpenClaw", [
            "code", "implement", "test", "debug", "refactor",
            "api", "script", "docker", "deploy",
        ])
        self._pool.register("openhanako", "OpenHanako", [
            "file_operations", "filesystem", "desktop", "wechat",
            "bridge", "local_execution", "data_processing",
        ])
        self._pool.register("hermes", "Hermes", [
            "analysis", "research", "summary", "documentation",
            "knowledge_retrieval", "long_task", "project_automation",
            "architecture_planning",
        ])
        self._pool.register("iliya", "Iliya（微信人格）", [
            "conversation", "wechat", "personal_assistant",
            "scheduling", "reminders",
        ])

    # ── 公共 API ─────────────────────────────────────────────

    async def submit(self, goal: str, max_parallelism: int = 3) -> str:
        """
        提交一个任务，返回 task_id。
        任务会自动拆分并开始并行执行。
        """
        task_id = f"task_{uuid.uuid4().hex[:8]}"

        # 拆分任务
        split_descs = TaskSplitter.split(goal, agent_count_hint=max_parallelism)
        sub_tasks = []
        for desc in split_descs[:max_parallelism]:
            st_id = f"st_{uuid.uuid4().hex[:6]}"
            st = SubTask(
                id=st_id,
                description=desc["description"],
                assigned_agent="",               # 待分配
                parent_id=task_id,
                capabilities_required=desc.get("capabilities", []),
            )
            sub_tasks.append(st)
            self._sub_tasks[st_id] = st

        cluster_task = ClusterTask(
            id=task_id,
            goal=goal,
            sub_tasks=sub_tasks,
        )
        self._tasks[task_id] = cluster_task

        logger.info(f"[cluster] submit task {task_id} with {len(sub_tasks)} sub-tasks")

        # 并行启动所有子任务
        await self._dispatch_all_subtasks(task_id)

        return task_id

    async def get_task_status(self, task_id: str) -> dict:
        """获取任务状态"""
        task = self._tasks.get(task_id)
        if not task:
            return {"error": "Task not found"}

        return {
            "id": task.id,
            "goal": task.goal,
            "status": task.status.value,
            "done_ratio": round(task.done_ratio, 2),
            "total_subtasks": len(task.sub_tasks),
            "sub_tasks": [
                {
                    "id": st.id,
                    "description": st.description,
                    "assigned_agent": st.assigned_agent,
                    "status": st.status.value,
                    "result": st.result[:200] + "..." if st.result and len(st.result) > 200 else st.result,
                    "error": st.error,
                }
                for st in task.sub_tasks
            ],
            "completed_at": task.completed_at,
            "total_duration_ms": task.total_duration_ms,
        }

    async def get_task_result(self, task_id: str) -> dict:
        """获取任务最终结果（会等待完成）"""
        task = self._tasks.get(task_id)
        if not task:
            return {"error": "Task not found"}

        # 等待完成
        while not task.is_done:
            await asyncio.sleep(0.5)

        return {
            "id": task.id,
            "status": task.status.value,
            "result": task.result,
            "error": task.error,
            "total_duration_ms": task.total_duration_ms,
            "sub_tasks": [
                {
                    "id": st.id,
                    "status": st.status.value,
                    "result": st.result,
                    "error": st.error,
                    "duration_ms": st.duration_ms(),
                }
                for st in task.sub_tasks
            ],
        }

    async def cancel_task(self, task_id: str) -> dict:
        """取消任务"""
        task = self._tasks.get(task_id)
        if not task:
            return {"error": "Task not found"}

        for st in task.sub_tasks:
            if st.status == SubTaskStatus.PENDING:
                st.status = SubTaskStatus.CANCELLED
            elif st.status == SubTaskStatus.RUNNING:
                # 中止运行中的子任务
                running = self._running_sub_tasks.get(st.id)
                if running:
                    running.cancel()

        task.status = SubTaskStatus.CANCELLED
        task.completed_at = datetime.now().isoformat()
        return {"ok": True, "message": f"Task {task_id} cancelled"}

    def get_cluster_status(self) -> dict:
        """获取集群整体状态"""
        agents = self._pool.get_all()
        active_tasks = sum(
            1 for t in self._tasks.values()
            if t.status not in (SubTaskStatus.SUCCESS, SubTaskStatus.FAILED, SubTaskStatus.CANCELLED)
        )

        return {
            "total_agents": len(agents),
            "idle_agents": len(self._pool.get_idle_agents()),
            "active_tasks": active_tasks,
            "total_tasks_submitted": len(self._tasks),
            "running_subtasks": len(self._running_sub_tasks),
            "stealing_enabled": self._stealing_enabled,
            "agents": [
                {
                    "agent_id": a.agent_id,
                    "name": a.name,
                    "status": a.status,
                    "capabilities": a.capabilities,
                    "total_completed": a.total_tasks_completed,
                    "success_rate": round(a.success_rate, 2),
                }
                for a in agents
            ],
        }

    # ── 调度逻辑 ─────────────────────────────────────────────

    async def _dispatch_all_subtasks(self, task_id: str) -> None:
        """并行调度所有子任务"""
        task = self._tasks[task_id]

        async def run_subtask(st: SubTask):
            await self._dispatch_subtask(st)

        # 所有子任务并行执行
        await asyncio.gather(
            *[run_subtask(st) for st in task.sub_tasks],
            return_exceptions=True,
        )

        # 检查整体状态
        await self._finalize_task(task_id)

    async def _dispatch_subtask(self, st: SubTask) -> None:
        """调度单个子任务到合适的 Agent"""
        task = self._tasks.get(st.parent_id)
        if not task or task.is_done:
            return

        # ── 选择最合适的 Agent ──────────────────────────────
        # 1. 尝试能力匹配
        if st.capabilities_required:
            best = self._pool.best_agent_for_capabilities(st.capabilities_required)
            if best:
                st.assigned_agent = best.agent_id

        # 2. 否则按 agent_hint 或循环分配
        if not st.assigned_agent:
            idle = self._pool.get_idle_agents()
            if idle:
                st.assigned_agent = idle[0].agent_id
            else:
                # 所有 Agent 忙，进入等待队列
                await self._stealing_queue.put(st.id)
                return

        # ── 尝试分配任务 ───────────────────────────────────
        assigned = await self._pool.assign_task(
            st.assigned_agent, st.parent_id, st.id
        )

        if not assigned:
            # 分配失败（Agent 不空闲），进入队列
            await self._stealing_queue.put(st.id)
            return

        # ── 执行子任务 ─────────────────────────────────────
        st.status = SubTaskStatus.RUNNING
        st.started_at = datetime.now().isoformat()

        worker = self._worker_factory(st.assigned_agent, st.id, st.description)
        asyncio_task = asyncio.create_task(self._execute_subtask(st, worker))
        self._running_sub_tasks[st.id] = asyncio_task

    async def _execute_subtask(self, st: SubTask, worker: "AgentWorker") -> None:
        """执行子任务（带重试）"""
        task = self._tasks.get(st.parent_id)

        try:
            for attempt in range(st.max_retries + 1):
                try:
                    st.retries = attempt
                    result = await worker.run()

                    st.status = SubTaskStatus.SUCCESS
                    st.result = result
                    st.completed_at = datetime.now().isoformat()

                    if task:
                        task.status = SubTaskStatus.SUCCESS if all(
                            s.status != SubTaskStatus.FAILED
                            for s in task.sub_tasks
                        ) else SubTaskStatus.RUNNING

                    logger.info(f"[cluster] sub-task {st.id} SUCCESS on attempt {attempt + 1}")
                    break

                except Exception as e:
                    if attempt < st.max_retries:
                        logger.warning(f"[cluster] sub-task {st.id} failed attempt {attempt + 1}: {e}")
                        await asyncio.sleep(2 ** attempt)  # 指数退避
                    else:
                        st.status = SubTaskStatus.FAILED
                        st.error = str(e)
                        st.completed_at = datetime.now().isoformat()
                        logger.error(f"[cluster] sub-task {st.id} FAILED after {attempt + 1} attempts: {e}")

        finally:
            await self._pool.release_task(st.assigned_agent, st.status == SubTaskStatus.SUCCESS)
            self._running_sub_tasks.pop(st.id, None)

            # 检查是否可以 stolen 任务
            if not self._stealing_queue.empty():
                stolen_id = await asyncio.wait_for(self._stealing_queue.get(), timeout=0.1)
                stolen_st = self._sub_tasks.get(stolen_id)
                if stolen_st and stolen_st.status == SubTaskStatus.PENDING:
                    await self._dispatch_subtask(stolen_st)

    async def _finalize_task(self, task_id: str) -> None:
        """任务完成时聚合结果"""
        task = self._tasks.get(task_id)
        if not task:
            return

        # 等待所有子任务完成
        pending = [st for st in task.sub_tasks
                   if st.status in (SubTaskStatus.PENDING, SubTaskStatus.RUNNING)]
        while pending:
            await asyncio.sleep(0.2)
            pending = [st for st in task.sub_tasks
                       if st.status in (SubTaskStatus.PENDING, SubTaskStatus.RUNNING)]

        # 聚合
        task.result, task.error = ResultAggregator.aggregate(task.sub_tasks)

        if any(st.status == SubTaskStatus.FAILED for st in task.sub_tasks):
            task.status = SubTaskStatus.FAILED
        else:
            task.status = SubTaskStatus.SUCCESS

        task.completed_at = datetime.now().isoformat()

        if task.created_at and task.completed_at:
            start = datetime.fromisoformat(task.created_at)
            end = datetime.fromisoformat(task.completed_at)
            task.total_duration_ms = (end - start).total_seconds() * 1000

        logger.info(f"[cluster] task {task_id} finalized as {task.status.value}, "
                    f"duration={task.total_duration_ms:.0f}ms")

    # ── Work Stealing ─────────────────────────────────────────

    async def _work_stealing_loop(self) -> None:
        """空闲 Agent 主动从队列偷任务"""
        while self._stealing_enabled:
            try:
                await asyncio.sleep(3)  # 每 3 秒检查一次

                idle = self._pool.get_idle_agents()
                if not idle:
                    continue

                # 尝试从队列取任务
                try:
                    stolen_id = self._stealing_queue.get_nowait()
                except asyncio.QueueEmpty:
                    continue

                stolen_st = self._sub_tasks.get(stolen_id)
                if not stolen_st or stolen_st.status != SubTaskStatus.PENDING:
                    continue

                # 分配给空闲 Agent
                agent = idle[0]
                stolen_st.assigned_agent = agent.agent_id

                assigned = await self._pool.assign_task(
                    agent.agent_id, stolen_st.parent_id, stolen_st.id
                )
                if not assigned:
                    await self._stealing_queue.put(stolen_id)
                    continue

                # 启动执行
                worker = self._worker_factory(agent.agent_id, stolen_st.id, stolen_st.description)
                asyncio_task = asyncio.create_task(self._execute_subtask(stolen_st, worker))
                self._running_sub_tasks[stolen_st.id] = asyncio_task

                logger.info(f"[cluster] Work Stealing: {agent.agent_id} took task {stolen_st.id}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[cluster] Work Stealing loop error: {e}")


# ── Worker 接口 ─────────────────────────────────────────────

class AgentWorker:
    """执行 Agent 任务的 Worker 接口"""

    def __init__(self, agent_id: str, task_id: str, goal: str):
        self.agent_id = agent_id
        self.task_id = task_id
        self.goal = goal

    async def run(self) -> str:
        raise NotImplementedError


# ── 循环引用类型提示（避免 py < 3.10 dataclass 问题）───────────

UnifiedCapabilityRegistry = Any
