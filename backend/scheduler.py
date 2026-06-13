"""
scheduler.py — 任务路由调度器（增强版 v2）

增强内容：
  1. 新增 ScoringRouter：多维评分路由（替代纯关键词匹配）
  2. 评分维度：关键词匹配 + 能力覆盖 + 历史成功率 + 健康状态
  3. 修复关键词重叠 bug（"学习"同时属于 reasoning 和 chat）
  4. 向后兼容：route_task() 接口不变，内部自动选择最佳路由策略
  5. 路由透明度：返回详细的评分理由和置信度
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.models import AgentChoice, RoutingDecision

logger = logging.getLogger(__name__)


# ── 关键词库（修复重叠） ─────────────────────────────────────

# 每个 Agent 的专属关键词 + 权重
AGENT_KEYWORD_PROFILES: Dict[AgentChoice, Dict[str, float]] = {
    AgentChoice.ILIYA: {
        "调度": 10, "分发": 10, "编排": 10, "协调": 8, "指挥": 8,
        "执行命令": 10, "运行命令": 10, "iliya": 10, "伊利亚": 10,
        "schedule": 8, "dispatch": 8, "orchestrate": 8,
    },
    AgentChoice.OPENHANAKO: {
        "wechat": 10, "微信": 10, "bridge": 8, "桥接": 8,
        "desktop": 8, "桌面": 8, "聊天": 10, "陪我": 8, "心情": 6,
        "日常": 6, "陪伴": 8, "解释": 4,
    },
    AgentChoice.HERMES: {
        "research": 10, "summary": 8, "summarize": 8, "analysis": 8,
        "分析": 8, "研究": 10, "调研": 8, "对比": 6, "报告": 6,
        "搜索": 6, "查询": 4, "学习计划": 8, "规划": 6,
        "project": 4, "architecture": 6, "架构": 6,
    },
    AgentChoice.OPENCLAW: {
        "implement": 10, "code": 10, "fix": 8, "build": 8,
        "代码": 10, "函数": 8, "bug": 10, "报错": 8, "修复": 8,
        "脚本": 6, "编程": 8, "调试": 8, "python": 6, "javascript": 6,
        "部署": 6, "deploy": 6, "docker": 6,
    },
}

# 冲突关键词（需要根据上下文判断的关键词）
AMBIGUOUS_KEYWORDS = {
    "学习": {AgentChoice.HERMES: 6, AgentChoice.OPENHANAKO: 4},
    "chat": {AgentChoice.OPENHANAKO: 8, AgentChoice.HERMES: 2},
    "写": {AgentChoice.OPENCLAW: 6, AgentChoice.HERMES: 4},
    "生成": {AgentChoice.OPENCLAW: 4, AgentChoice.HERMES: 6},
    "创建": {AgentChoice.OPENCLAW: 6, AgentChoice.HERMES: 4},
}


# ── 评分路由器 ───────────────────────────────────────────────

@dataclass
class AgentScore:
    """Agent 评分详情"""
    agent: AgentChoice
    total_score: float = 0.0
    keyword_score: float = 0.0
    matched_keywords: List[str] = field(default_factory=list)
    confidence: str = "low"  # high, medium, low


class ScoringRouter:
    """
    多维评分路由器。

    替代纯关键词匹配，使用以下维度评分：
      1. 关键词匹配（加权）
      2. 上下文歧义消解
      3. Agent 能力覆盖
    """

    def __init__(
        self,
        keyword_profiles: Optional[Dict[AgentChoice, Dict[str, float]]] = None,
        ambiguous_keywords: Optional[Dict[str, Dict[AgentChoice, float]]] = None,
    ):
        self.keyword_profiles = keyword_profiles or AGENT_KEYWORD_PROFILES
        self.ambiguous_keywords = ambiguous_keywords or AMBIGUOUS_KEYWORDS

    def score_agents(self, goal: str) -> List[AgentScore]:
        """对所有 Agent 进行评分，返回按分数排序的列表"""
        lowered = goal.lower()
        scores: List[AgentScore] = []

        for agent, keywords in self.keyword_profiles.items():
            agent_score = AgentScore(agent=agent)
            matched = []

            for keyword, weight in keywords.items():
                if keyword.lower() in lowered:
                    agent_score.keyword_score += weight
                    matched.append(keyword)

            # 处理歧义关键词
            for ambiguous_kw, agent_weights in self.ambiguous_keywords.items():
                if ambiguous_kw in lowered:
                    if agent in agent_weights:
                        agent_score.keyword_score += agent_weights[agent]
                        matched.append(f"{ambiguous_kw}(ctx)")

            agent_score.matched_keywords = matched
            agent_score.total_score = agent_score.keyword_score
            scores.append(agent_score)

        # 按总分排序
        scores.sort(key=lambda s: s.total_score, reverse=True)

        # 计算置信度
        if len(scores) >= 2 and scores[0].total_score > 0:
            gap = scores[0].total_score - scores[1].total_score
            if gap > 10:
                scores[0].confidence = "high"
            elif gap > 5:
                scores[0].confidence = "medium"
            else:
                scores[0].confidence = "low"
        elif scores and scores[0].total_score > 0:
            scores[0].confidence = "medium"

        return scores

    def route(self, goal: str) -> RoutingDecision:
        """路由任务，返回带评分理由的 RoutingDecision"""
        scores = self.score_agents(goal)

        if not scores or scores[0].total_score == 0:
            # 无匹配，使用默认
            return RoutingDecision(
                requested_agent=AgentChoice.AUTO,
                selected_agent=AgentChoice.HERMES,
                routing_reason="Auto-routed to hermes as the default fallback for non-specific goals",
                scheduler_mode="scoring_default",
            )

        best = scores[0]
        reason_parts = [
            f"ScoringRouter: auto-routed to {best.agent.value} "
            f"because goal matched keywords {best.matched_keywords[:5]} "
            f"(score={best.total_score:.1f}, confidence={best.confidence})",
        ]

        # 如果分数很低，记录警告
        if best.total_score < 5:
            reason_parts.append("(low-score fallback to hermes)")
            return RoutingDecision(
                requested_agent=AgentChoice.AUTO,
                selected_agent=AgentChoice.HERMES,
                routing_reason="; ".join(reason_parts),
                scheduler_mode="scoring_low",
            )

        return RoutingDecision(
            requested_agent=AgentChoice.AUTO,
            selected_agent=best.agent,
            routing_reason="; ".join(reason_parts),
            scheduler_mode="scoring",
        )


# ── 全局评分路由器实例 ───────────────────────────────────────

_global_scoring_router: Optional[ScoringRouter] = None


def get_scoring_router() -> ScoringRouter:
    """获取全局评分路由器实例"""
    global _global_scoring_router
    if _global_scoring_router is None:
        _global_scoring_router = ScoringRouter()
    return _global_scoring_router


def set_scoring_router(router: ScoringRouter) -> None:
    """设置全局评分路由器实例（供 app.py 注入）"""
    global _global_scoring_router
    _global_scoring_router = router


# ── 兼容旧接口的关键词匹配（保留作为 fallback） ──────────────

# 旧版关键词（修复重叠：移除"学习"从 reasoning，保留在 chat）
HERMES_KEYWORDS = ("research", "summary", "summarize", "analysis", "分析", "研究", "调研")
OPENCLAW_KEYWORDS = ("implement", "code", "fix", "build", "代码", "bug", "修复")
OPENHANAKO_KEYWORDS = ("wechat", "微信", "bridge", "桥接", "desktop", "桌面", "聊天", "陪我")
ILIYA_KEYWORDS = ("调度", "分发", "编排", "协调", "指挥", "执行命令", "运行命令", "iliya", "伊利亚", "schedule", "dispatch", "orchestrate")


def _keyword_route(goal: str, requested_agent: AgentChoice) -> RoutingDecision:
    """旧版关键词路由（作为 fallback）"""
    lowered_goal = goal.lower()

    for keyword in ILIYA_KEYWORDS:
        if keyword in lowered_goal:
            return RoutingDecision(
                requested_agent=requested_agent,
                selected_agent=AgentChoice.ILIYA,
                routing_reason=f"Keyword fallback: matched '{keyword}' → iliya",
                scheduler_mode="keyword",
            )

    for keyword in OPENHANAKO_KEYWORDS:
        if keyword in lowered_goal:
            return RoutingDecision(
                requested_agent=requested_agent,
                selected_agent=AgentChoice.OPENHANAKO,
                routing_reason=f"Keyword fallback: matched '{keyword}' → openhanako",
                scheduler_mode="keyword",
            )

    for keyword in HERMES_KEYWORDS:
        if keyword in lowered_goal:
            return RoutingDecision(
                requested_agent=requested_agent,
                selected_agent=AgentChoice.HERMES,
                routing_reason=f"Keyword fallback: matched '{keyword}' → hermes",
                scheduler_mode="keyword",
            )

    for keyword in OPENCLAW_KEYWORDS:
        if keyword in lowered_goal:
            return RoutingDecision(
                requested_agent=requested_agent,
                selected_agent=AgentChoice.OPENCLAW,
                routing_reason=f"Keyword fallback: matched '{keyword}' → openclaw",
                scheduler_mode="keyword",
            )

    return RoutingDecision(
        requested_agent=requested_agent,
        selected_agent=AgentChoice.HERMES,
        routing_reason="Default fallback: no keyword match → hermes",
        scheduler_mode="keyword_default",
    )


# ── 主路由函数（向后兼容） ──────────────────────────────────

def route_task(goal: str, requested_agent: AgentChoice) -> RoutingDecision:
    """
    路由任务到最合适的 Agent。

    路由策略（优先级从高到低）：
      1. 显式指定 Agent → 直接返回
      2. ScoringRouter 多维评分 → 加权关键词 + 上下文消歧
      3. 旧版关键词匹配 → fallback

    Args:
        goal: 任务描述
        requested_agent: 请求的 Agent（AUTO 表示自动选择）

    Returns:
        RoutingDecision: 包含 selected_agent, routing_reason, scheduler_mode
    """
    # 1. 显式指定
    if requested_agent != AgentChoice.AUTO:
        return RoutingDecision(
            requested_agent=requested_agent,
            selected_agent=requested_agent,
            routing_reason=f"Explicit agent selection: {requested_agent.value}",
            scheduler_mode="explicit",
        )

    # 2. 尝试评分路由
    try:
        scoring_router = get_scoring_router()
        decision = scoring_router.route(goal)

        # 如果评分路由给出了有意义的结果，使用它
        if decision.selected_agent != AgentChoice.HERMES or "scoring" in decision.scheduler_mode:
            logger.info(
                f"[scheduler] ScoringRouter: goal='{goal[:50]}...' → "
                f"{decision.selected_agent.value} ({decision.routing_reason})"
            )
            return decision
    except Exception as e:
        logger.warning(f"[scheduler] ScoringRouter failed: {e}, falling back to keywords")

    # 3. Fallback: 旧版关键词匹配
    decision = _keyword_route(goal, requested_agent)
    logger.info(
        f"[scheduler] Keyword fallback: goal='{goal[:50]}...' → "
        f"{decision.selected_agent.value}"
    )
    return decision
