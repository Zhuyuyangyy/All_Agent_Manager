"""
router.py — 任务路由器（增强版）

增强内容：
  1. 连接 UnifiedCapabilityRegistry，根据能力匹配选择 Agent
  2. 支持异步 dispatch_async()
  3. ClusterOrchestrator 集成：注册 Agent 快照
  4. 基于 Registry 的 Skill/MCP 能力路由
  5. 路由回退机制：首选 Agent 失败时自动选择次选
  6. 路由决策透明度：返回详细的路由理由
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional

from backend.core.base_adapter import BaseAgentAdapter
from backend.core.task_schema import AgentTask, AgentResult

logger = logging.getLogger(__name__)


@dataclass
class RoutingDecision:
    """路由决策详情"""
    selected_agent: str
    score: float
    confidence: str  # "high", "medium", "low"
    reasons: List[str] = field(default_factory=list)
    alternatives: List[Dict] = field(default_factory=list)  # 备选 Agent
    task_analysis: Dict[str, Any] = field(default_factory=dict)


class AgentRouter:
    """
    任务路由器

    职责：
      1. 管理已注册的 Agent（通过 BaseAgentAdapter）
      2. 根据任务内容 + 能力需求选择最合适的 Agent
      3. 连接 UnifiedCapabilityRegistry 实现 Plugin/Skill/MCP 能力路由
      4. 分发任务并返回结果
    """

    def __init__(
        self,
        capability_registry: Optional[Any] = None,  # UnifiedCapabilityRegistry
        cluster_orchestrator: Optional[Any] = None,
    ):
        self.agents: Dict[str, BaseAgentAdapter] = {}
        self._capability_registry = capability_registry
        self._orchestrator = cluster_orchestrator
        self._dispatch_history: List[Dict] = []

    # ── Agent 注册 ───────────────────────────────────────

    def register(self, agent: BaseAgentAdapter) -> None:
        """注册一个 Agent"""
        key = str(agent.agent_name)
        self.agents[key] = agent
        logger.info(
            f"[router] Registered agent: {agent.agent_name} ({agent.agent_type})"
            f", capabilities={agent.capabilities}"
        )

        # 同步到 ClusterOrchestrator 的 AgentPool
        if self._orchestrator:
            self._orchestrator._pool.register(
                agent.agent_name,
                agent.agent_name,
                agent.capabilities,
            )

    def unregister(self, agent_name: str) -> bool:
        """注销一个 Agent"""
        if agent_name in self.agents:
            del self.agents[agent_name]
            logger.info(f"[router] Unregistered agent: {agent_name}")
            return True
        return False

    def get_agent(self, agent_name: str) -> Optional[BaseAgentAdapter]:
        if agent_name in self.agents:
            return self.agents[agent_name]
        for key, agent in self.agents.items():
            if key == agent_name or str(key) == agent_name:
                return agent
        return None

    def list_agents(self) -> List[Dict]:
        return [agent.to_dict() for agent in self.agents.values()]

    def set_capability_registry(self, registry: Any) -> None:
        """设置能力注册中心（供运行时注入）"""
        self._capability_registry = registry

    def set_cluster_orchestrator(self, orchestrator: Any) -> None:
        """设置集群编排器（供运行时注入）"""
        self._orchestrator = orchestrator

    # ── 路由选择 ────────────────────────────────────────

    def route(self, task: AgentTask) -> BaseAgentAdapter:
        """
        根据任务内容 + Registry 能力选择最合适的 Agent。

        选择逻辑（优先级从高到低）：
          1. 精确 capability 匹配（Registry 查询）
          2. Agent can_handle() 分数排序
          3. 默认兜底到 hermes
        """
        decision = self._make_routing_decision(task)
        
        # 获取选中的 Agent
        best_agent = self.agents.get(decision.selected_agent)
        if not best_agent:
            raise RuntimeError(f"Selected agent {decision.selected_agent} not found")
        
        return best_agent

    def route_with_decision(self, task: AgentTask) -> RoutingDecision:
        """
        路由选择（返回完整决策详情）
        
        Returns:
            RoutingDecision: 包含路由决策的完整信息
        """
        return self._make_routing_decision(task)

    def _make_routing_decision(self, task: AgentTask) -> RoutingDecision:
        """执行路由决策逻辑"""
        # ── 1. 任务分析 ───────────────────────────────
        task_analysis = {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "project": task.project,
            "content_length": len(task.content),
            "priority": task.priority,
            "has_context": bool(task.context),
        }
        
        # 关键词提取
        keywords = self._extract_keywords(task.content)
        task_analysis["keywords"] = keywords
        
        # ── 2. 获取可用 Agent ─────────────────────────
        available_agents = [
            agent for agent in self.agents.values()
            if agent.enabled and agent.health_check().get("status") == "ok"
        ]

        if not available_agents:
            raise RuntimeError("No available agents")

        # ── 3. Agent 评分 ────────────────────────────
        scored_agents: List[tuple[BaseAgentAdapter, float, List[str]]] = []

        for agent in available_agents:
            score = 0.0
            reasons = []

            # Registry 能力匹配
            if self._capability_registry:
                caps = agent.get_capabilities()
                for cap in caps:
                    entry = self._capability_registry.get_capability(cap)
                    if entry:
                        score += entry.score_boost * 10
                        reasons.append(f"Registry能力匹配: {cap} (+{entry.score_boost*10:.1f})")

            # Agent can_handle 分数
            try:
                can_score = agent.can_handle(task)
                score += can_score * 50
                if can_score > 0.5:
                    reasons.append(f"can_handle分数: {can_score:.2f} (+{can_score*50:.1f})")
            except Exception as err:
                logger.warning(f"[router] {agent.agent_name}.can_handle error: {err}")

            # 任务类型匹配
            if task.task_type in agent.capabilities:
                score += 15
                reasons.append(f"任务类型匹配: {task.task_type} (+15)")

            # 成功率加成
            snapshot = agent.get_snapshot()
            total = snapshot.get("total_runs", 0)
            if total > 0:
                success_rate = snapshot.get("success_rate", 100) / 100
                score += success_rate * 5
                reasons.append(f"历史成功率: {snapshot.get('success_rate', 100):.1f}% (+{success_rate*5:.1f})")

            # 健康状态加成
            health = agent.health_check()
            if health.get("status") == "ok":
                score += 2
                reasons.append("健康状态良好 (+2)")

            scored_agents.append((agent, score, reasons))

        if not scored_agents:
            raise RuntimeError("No agent can handle this task")

        scored_agents.sort(key=lambda x: x[1], reverse=True)
        best_agent, best_score, best_reasons = scored_agents[0]
        
        # ── 4. 置信度判断 ─────────────────────────────
        if len(scored_agents) >= 2:
            second_score = scored_agents[1][1]
            score_gap = best_score - second_score
            if score_gap > 20:
                confidence = "high"
            elif score_gap > 10:
                confidence = "medium"
            else:
                confidence = "low"  # 分数接近，可能需要回退
        else:
            confidence = "medium" if best_score > 10 else "low"

        # ── 5. 备选 Agent ────────────────────────────
        alternatives = []
        for agent, score, reasons in scored_agents[1:min(3, len(scored_agents))]:
            alternatives.append({
                "agent": agent.agent_name,
                "score": round(score, 2),
                "reasons": reasons[:3]  # 只保留前3个理由
            })

        # ── 6. 构建决策对象 ──────────────────────────
        decision = RoutingDecision(
            selected_agent=best_agent.agent_name,
            score=round(best_score, 2),
            confidence=confidence,
            reasons=best_reasons,
            alternatives=alternatives,
            task_analysis=task_analysis,
        )

        # ── 7. 日志输出 ─────────────────────────────
        logger.info(
            f"[router] Task {task.task_id[:8]}... → {decision.selected_agent} "
            f"(score={decision.score:.2f}, confidence={confidence}, "
            f"candidates={len(scored_agents)})"
        )
        
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"[router] 路由决策详情: {decision}")

        if best_score < 5.0:
            logger.warning(f"[router] Best score too low ({best_score:.2f}), still proceeding")

        return decision

    # ── 同步分发 ───────────────────────────────────────

    def dispatch(self, task: AgentTask) -> AgentResult:
        start_time = time.time()

        try:
            decision = self._make_routing_decision(task)
        except RuntimeError as err:
            return AgentResult(
                task_id=task.task_id,
                agent_name="router",
                status="failed",
                result="",
                error=str(err),
            )

        best_agent = self.get_agent(decision.selected_agent)
        if not best_agent:
            return AgentResult(
                task_id=task.task_id,
                agent_name="router",
                status="failed",
                result="",
                error=f"Agent {decision.selected_agent} not found",
            )

        try:
            result = best_agent.run(task)
        except Exception as err:
            logger.error(f"[router] Agent {best_agent.agent_name} run error: {err}")
            result = AgentResult(
                task_id=task.task_id,
                agent_name=best_agent.agent_name,
                status="failed",
                result="",
                error=str(err),
            )

        if result.status == "completed":
            duration = time.time() - start_time
            self._record_dispatch(task.task_id, best_agent.agent_name, result.status, duration)
            return result

        for alt_info in decision.alternatives:
            alt_name = alt_info.get("agent", "")
            alt_agent = self.get_agent(alt_name)
            if not alt_agent:
                continue
            logger.warning(f"[router] Fallback: {best_agent.agent_name} failed, trying {alt_name}")
            try:
                alt_result = alt_agent.run(task)
                if alt_result.status == "completed":
                    duration = time.time() - start_time
                    self._record_dispatch(task.task_id, alt_agent.agent_name, alt_result.status, duration)
                    alt_result.metadata = alt_result.metadata or {}
                    alt_result.metadata["fallback_from"] = best_agent.agent_name
                    return alt_result
            except Exception as err:
                logger.warning(f"[router] Fallback agent {alt_name} also failed: {err}")
                continue

        duration = time.time() - start_time
        self._record_dispatch(task.task_id, best_agent.agent_name, result.status, duration)
        return result

    # ── 异步分发 ───────────────────────────────────────

    async def dispatch_async(self, task: AgentTask) -> AgentResult:
        start_time = time.time()

        try:
            decision = self._make_routing_decision(task)
        except RuntimeError as err:
            return AgentResult(
                task_id=task.task_id,
                agent_name="router",
                status="failed",
                result="",
                error=str(err),
            )

        best_agent = self.get_agent(decision.selected_agent)
        if not best_agent:
            return AgentResult(
                task_id=task.task_id,
                agent_name="router",
                status="failed",
                result="",
                error=f"Agent {decision.selected_agent} not found",
            )

        try:
            result = await best_agent.run_async(task)
        except Exception as err:
            logger.error(f"[router] Agent {best_agent.agent_name} run_async error: {err}")
            result = AgentResult(
                task_id=task.task_id,
                agent_name=best_agent.agent_name,
                status="failed",
                result="",
                error=str(err),
            )

        if result.status == "completed":
            duration = time.time() - start_time
            self._record_dispatch(task.task_id, best_agent.agent_name, result.status, duration)
            return result

        for alt_info in decision.alternatives:
            alt_name = alt_info.get("agent", "")
            alt_agent = self.get_agent(alt_name)
            if not alt_agent:
                continue
            logger.warning(f"[router] Fallback: {best_agent.agent_name} failed, trying {alt_name}")
            try:
                alt_result = await alt_agent.run_async(task)
                if alt_result.status == "completed":
                    duration = time.time() - start_time
                    self._record_dispatch(task.task_id, alt_agent.agent_name, alt_result.status, duration)
                    alt_result.metadata = alt_result.metadata or {}
                    alt_result.metadata["fallback_from"] = best_agent.agent_name
                    return alt_result
            except Exception as err:
                logger.warning(f"[router] Fallback agent {alt_name} also failed: {err}")
                continue

        duration = time.time() - start_time
        self._record_dispatch(task.task_id, best_agent.agent_name, result.status, duration)
        return result

    # ── 批量分发 ───────────────────────────────────────

    async def dispatch_batch(
        self,
        tasks: List[AgentTask],
        max_concurrent: int = 5,
    ) -> List[AgentResult]:
        """
        批量分发任务（带并发限制）。

        用于 ClusterOrchestrator 的并行子任务执行。
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def run_one(task: AgentTask) -> AgentResult:
            async with semaphore:
                return await self.dispatch_async(task)

        return await asyncio.gather(*[run_one(t) for t in tasks], return_exceptions=True)

    # ── 内部工具 ───────────────────────────────────────

    def _extract_keywords(self, text: str) -> List[str]:
        """从文本中提取关键词"""
        if not text:
            return []
        
        # 简单关键词提取：基于常见模式
        import re
        text_lower = text.lower()
        
        patterns = [
            r'代码|函数|接口|bug|报错|脚本|文件|调试',
            r'聊天|陪我|心情|解释|日常',
            r'项目|架构|路线|规划|自动化|实验',
            r'搜索|查询|查找|获取',
            r'生成|创建|编写|写',
            r'修复|解决|改正',
        ]
        
        keywords = []
        for pattern in patterns:
            matches = re.findall(pattern, text_lower)
            keywords.extend(matches)
        
        return list(set(keywords))[:10]  # 最多10个关键词

    def _record_dispatch(
        self,
        task_id: str,
        agent_name: str,
        status: str,
        duration: float,
    ) -> None:
        self._dispatch_history.append({
            "task_id": task_id,
            "agent_name": agent_name,
            "status": status,
            "duration": round(duration, 2),
            "timestamp": time.time(),
        })
        if len(self._dispatch_history) > 1000:
            self._dispatch_history = self._dispatch_history[-500:]

    def get_stats(self) -> Dict:
        agent_stats = {}
        for name, agent in self.agents.items():
            snapshot = agent.get_snapshot()
            agent_stats[name] = {
                "enabled": agent.enabled,
                "health": agent.health_check(),
                "total_runs": snapshot.get("total_runs", 0),
                "success_rate": snapshot.get("success_rate", 0),
            }

        return {
            "total_agents": len(self.agents),
            "enabled_agents": sum(1 for a in self.agents.values() if a.enabled),
            "dispatch_count": len(self._dispatch_history),
            "agents": agent_stats,
        }

    def get_history(self, limit: int = 50) -> List[Dict]:
        return self._dispatch_history[-limit:]
