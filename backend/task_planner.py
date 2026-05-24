"""
task_planner.py — 智能任务拆解与分配模块

分析复杂目标，拆解为可执行的子任务，并决定由哪个 Agent 执行。
支持规则引擎和 LLM 两种模式。
"""

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from backend.models import AgentChoice
from backend.project_discovery import DiscoveredTask, TaskType, TaskPriority
from backend.scheduler import route_task


class PlanMode(StrEnum):
    """规划模式"""
    RULES = "rules"        # 纯规则引擎
    LLM = "llm"            # LLM 辅助规划
    HYBRID = "hybrid"      # 规则 + LLM 混合


@dataclass
class SubTask:
    """拆解后的子任务"""
    id: str
    goal: str
    agent: AgentChoice
    priority: TaskPriority = TaskPriority.NORMAL
    dependencies: list[str] = field(default_factory=list)  # 依赖的子任务 ID
    estimated_effort: str = "medium"  # low, medium, high
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "goal": self.goal,
            "agent": self.agent.value,
            "priority": self.priority.value,
            "dependencies": self.dependencies,
            "estimated_effort": self.estimated_effort,
            "context": self.context,
        }


@dataclass
class ExecutionPlan:
    """执行计划"""
    id: str
    original_goal: str
    sub_tasks: list[SubTask]
    mode: PlanMode = PlanMode.RULES
    reasoning: str = ""  # 规划理由
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "original_goal": self.original_goal,
            "sub_tasks": [st.to_dict() for st in self.sub_tasks],
            "mode": self.mode.value,
            "reasoning": self.reasoning,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


# ── 任务复杂度分析 ──

COMPLEXITY_INDICATORS = {
    "high": [
        "整个项目", "全面", "完整", "所有模块", "系统级",
        "project", "entire", "complete", "all modules", "system",
        "重构", "refactor", "迁移", "migrate",
    ],
    "medium": [
        "部分", "几个", "多个", "some", "multiple", "several",
        "功能", "feature", "模块", "module",
        "优化", "optimize", "改进", "improve",
    ],
    "low": [
        "一个", "单个", "简单", "one", "single", "simple",
        "修复", "fix", "调整", "adjust", "更新", "update",
    ],
}

MULTI_ACTION_KEYWORDS = [
    "并且", "然后", "接着", "同时", "之后",
    "and then", "also", "plus", "additionally",
    "、", "；",
]

AGENT_CAPABILITY_MAP = {
    AgentChoice.OPENCLAW: {
        "keywords": [
            "code", "代码", "program", "编程", "debug", "调试",
            "implement", "实现", "api", "接口", "function", "函数",
            "class", "类", "module", "模块", "script", "脚本",
            "test", "测试", "refactor", "重构", "bug", "fix",
        ],
        "task_types": [TaskType.BUG_FIX, TaskType.FEATURE, TaskType.CODE_REVIEW],
    },
    AgentChoice.HERMES: {
        "keywords": [
            "research", "研究", "analyze", "分析", "summary", "总结",
            "survey", "调研", "report", "报告", "compare", "对比",
            "evaluate", "评估", "review", "审查", "document", "文档",
        ],
        "task_types": [TaskType.RESEARCH, TaskType.DOCUMENTATION],
    },
    AgentChoice.OPENHANAKO: {
        "keywords": [
            "wechat", "微信", "bridge", "桥接", "desktop", "桌面",
            "chat", "聊天", "file", "文件", "folder", "文件夹",
            "send", "发送", "receive", "接收",
        ],
        "task_types": [TaskType.MAINTENANCE],
    },
}


class TaskPlanner:
    """
    智能任务规划器。
    分析任务目标，拆解为子任务，分配给合适的 Agent。
    """

    def __init__(self, mode: PlanMode = PlanMode.RULES):
        self.mode = mode
        self._plan_history: list[ExecutionPlan] = []
        self._agent_stats: dict[str, dict] = {
            "openclaw": {"completed": 0, "failed": 0, "avg_time": 0},
            "hermes": {"completed": 0, "failed": 0, "avg_time": 0},
            "openhanako": {"completed": 0, "failed": 0, "avg_time": 0},
        }

    def plan(self, goal: str, context: dict | None = None) -> ExecutionPlan:
        """
        为给定目标生成执行计划。
        """
        plan_id = f"plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        context = context or {}

        # 分析复杂度
        complexity = self._analyze_complexity(goal)

        # 检测是否需要拆分
        needs_split = self._needs_splitting(goal, complexity)

        if needs_split:
            sub_tasks = self._decompose(goal, context)
        else:
            sub_tasks = [self._create_single_task(goal, plan_id, context)]

        plan = ExecutionPlan(
            id=plan_id,
            original_goal=goal,
            sub_tasks=sub_tasks,
            mode=self.mode,
            reasoning=self._generate_reasoning(goal, complexity, needs_split, sub_tasks),
            metadata={
                "complexity": complexity,
                "needs_split": needs_split,
                "sub_task_count": len(sub_tasks),
            },
        )

        self._plan_history.append(plan)
        # 保留最近 50 条计划
        if len(self._plan_history) > 50:
            self._plan_history = self._plan_history[-50:]

        return plan

    def plan_from_discovered(self, task: DiscoveredTask) -> ExecutionPlan:
        """从发现的任务生成计划"""
        return self.plan(
            goal=task.goal,
            context={
                "source": task.source,
                "task_type": task.task_type.value,
                "priority": task.priority.value,
                "original_context": task.context,
            },
        )

    def _analyze_complexity(self, goal: str) -> str:
        """分析任务复杂度"""
        goal_lower = goal.lower()
        scores = {"high": 0, "medium": 0, "low": 0}

        for level, indicators in COMPLEXITY_INDICATORS.items():
            for indicator in indicators:
                if indicator.lower() in goal_lower:
                    scores[level] += 1

        # 长度也影响复杂度
        if len(goal) > 200:
            scores["high"] += 2
        elif len(goal) > 100:
            scores["medium"] += 1

        # 检测多动作关键词
        for keyword in MULTI_ACTION_KEYWORDS:
            if keyword in goal:
                scores["high"] += 1

        return max(scores, key=scores.get)

    def _needs_splitting(self, goal: str, complexity: str) -> bool:
        """判断是否需要拆分任务"""
        if complexity == "high":
            return True
        if complexity == "medium":
            # 检测多动作
            for keyword in MULTI_ACTION_KEYWORDS:
                if keyword in goal:
                    return True
        return False

    def _decompose(self, goal: str, context: dict) -> list[SubTask]:
        """将复杂任务拆解为子任务"""
        sub_tasks = []

        # 尝试按分隔符拆分
        parts = self._split_by_delimiters(goal)

        if len(parts) > 1:
            for i, part in enumerate(parts):
                part = part.strip()
                if not part:
                    continue
                agent = self._determine_agent(part, context)
                sub_tasks.append(SubTask(
                    id=f"sub_{i}",
                    goal=part,
                    agent=agent,
                    priority=self._determine_priority(part, context),
                    dependencies=["sub_" + str(i - 1)] if i > 0 else [],
                    context={"part_index": i, "total_parts": len(parts)},
                ))
        else:
            # 无法简单拆分，按能力匹配创建单个任务
            sub_tasks.append(self._create_single_task(goal, "", context))

        return sub_tasks

    def _split_by_delimiters(self, goal: str) -> list[str]:
        """按分隔符拆分任务"""
        # 中文分隔符
        delimiters = ["。", "；", "、", "然后", "接着", "并且", "同时", "之后"]
        parts = [goal]

        for delim in delimiters:
            new_parts = []
            for part in parts:
                new_parts.extend(part.split(delim))
            parts = new_parts

        # 英文分隔符
        english_delimiters = [". ", "; ", " and then ", ", and ", " also "]
        for delim in english_delimiters:
            new_parts = []
            for part in parts:
                new_parts.extend(part.split(delim))
            parts = new_parts

        return [p.strip() for p in parts if p.strip()]

    def _create_single_task(self, goal: str, plan_id: str, context: dict) -> SubTask:
        """创建单个子任务"""
        agent = self._determine_agent(goal, context)
        return SubTask(
            id=f"sub_{plan_id}" if plan_id else "sub_0",
            goal=goal,
            agent=agent,
            priority=self._determine_priority(goal, context),
            context=context,
        )

    def _determine_agent(self, goal: str, context: dict) -> AgentChoice:
        """决定由哪个 Agent 执行"""
        # 如果上下文指定了 agent，使用它
        if "suggested_agent" in context:
            suggested = context["suggested_agent"]
            if suggested != "auto":
                return AgentChoice(suggested)

        # 使用关键词匹配
        goal_lower = goal.lower()
        scores = {agent: 0 for agent in AgentChoice if agent != AgentChoice.AUTO}

        for agent, capabilities in AGENT_CAPABILITY_MAP.items():
            for keyword in capabilities["keywords"]:
                if keyword.lower() in goal_lower:
                    scores[agent] += 1

            # 任务类型匹配
            task_type_str = context.get("task_type", "")
            if task_type_str:
                try:
                    task_type = TaskType(task_type_str)
                    if task_type in capabilities["task_types"]:
                        scores[agent] += 2
                except ValueError:
                    pass

        # 历史统计加权
        for agent_name, stats in self._agent_stats.items():
            try:
                agent_enum = AgentChoice(agent_name)
                if agent_enum in scores:
                    total = stats["completed"] + stats["failed"]
                    if total > 0:
                        success_rate = stats["completed"] / total
                        scores[agent_enum] += success_rate * 0.5  # 轻微加权
            except ValueError:
                pass

        # 选择得分最高的
        best_agent = max(scores, key=scores.get)
        if scores[best_agent] > 0:
            return best_agent

        # 默认路由
        return route_task(goal, AgentChoice.AUTO).selected_agent

    def _determine_priority(self, goal: str, context: dict) -> TaskPriority:
        """决定任务优先级"""
        # 如果上下文指定了优先级
        if "priority" in context:
            try:
                return TaskPriority(context["priority"])
            except ValueError:
                pass

        goal_lower = goal.lower()

        # 紧急关键词
        urgent_keywords = ["urgent", "紧急", "critical", "critical", "asap", "马上", "立即"]
        for kw in urgent_keywords:
            if kw in goal_lower:
                return TaskPriority.URGENT

        # 高优先级关键词
        high_keywords = ["important", "重要", "priority", "优先", "high"]
        for kw in high_keywords:
            if kw in goal_lower:
                return TaskPriority.HIGH

        return TaskPriority.NORMAL

    def _generate_reasoning(
        self, goal: str, complexity: str, needs_split: bool, sub_tasks: list[SubTask]
    ) -> str:
        """生成规划理由"""
        parts = [f"任务复杂度：{complexity}"]

        if needs_split:
            parts.append(f"任务已拆分为 {len(sub_tasks)} 个子任务")
        else:
            parts.append("任务简单，无需拆分")

        agent_dist = {}
        for st in sub_tasks:
            agent_name = st.agent.value
            agent_dist[agent_name] = agent_dist.get(agent_name, 0) + 1

        dist_str = ", ".join(f"{k}: {v}" for k, v in agent_dist.items())
        parts.append(f"Agent 分配：{dist_str}")

        return "。".join(parts)

    def update_agent_stats(self, agent: AgentChoice, success: bool, duration: float = 0) -> None:
        """更新 Agent 执行统计"""
        agent_name = agent.value
        if agent_name not in self._agent_stats:
            return

        stats = self._agent_stats[agent_name]
        if success:
            stats["completed"] += 1
            # 更新平均时间
            total = stats["completed"]
            stats["avg_time"] = (stats["avg_time"] * (total - 1) + duration) / total
        else:
            stats["failed"] += 1

    def get_agent_stats(self) -> dict:
        """获取 Agent 执行统计"""
        return self._agent_stats.copy()

    def get_plan_history(self, limit: int = 10) -> list[dict]:
        """获取计划历史"""
        return [p.to_dict() for p in self._plan_history[-limit:]]


# ── 从环境变量构建 TaskPlanner ──

def build_task_planner_from_env() -> TaskPlanner:
    """根据环境变量构建 TaskPlanner"""
    mode_str = os.getenv("PLANNER_MODE", "rules")
    try:
        mode = PlanMode(mode_str)
    except ValueError:
        mode = PlanMode.RULES
    return TaskPlanner(mode=mode)
