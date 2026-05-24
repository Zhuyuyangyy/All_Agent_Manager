"""
replay_engine.py — 复刻引擎模块

从成功任务中提炼执行流程，生成可复用的技能模板。
让系统"越用越聪明"。
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from backend.models import AgentChoice, TaskStatus
from backend.storage import TaskRepository
from backend.skill_memory import SkillMemory, SkillTemplate, SkillStep, SkillStatus, SkillSource
from backend.plugin_manager import PluginManager


@dataclass
class TaskPattern:
    """从任务中提取的模式"""
    task_id: str
    goal: str
    agent: str
    success: bool
    duration: float | None = None
    plugins_used: list[str] = field(default_factory=list)
    steps_extracted: list[dict] = field(default_factory=list)
    error_pattern: str | None = None
    # 多 Agent 协作信息
    collaborating_agents: list[str] = field(default_factory=list)
    task_type: str | None = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "agent": self.agent,
            "success": self.success,
            "duration": self.duration,
            "plugins_used": self.plugins_used,
            "steps_extracted": self.steps_extracted,
            "error_pattern": self.error_pattern,
            "collaborating_agents": self.collaborating_agents,
            "task_type": self.task_type,
        }


@dataclass
class SkillProposal:
    """技能提案（待审查）"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    skill: SkillTemplate = field(default_factory=SkillTemplate)
    confidence: float = 0.0  # 匹配置信度
    evidence_tasks: list[str] = field(default_factory=list)  # 支撑证据的任务 ID
    proposed_at: str = field(default_factory=lambda: datetime.now().isoformat())
    reviewed: bool = False
    approved: bool = False
    reviewer_notes: str = ""
    # 多 Agent 协作信息
    collaboration_agents: list[str] = field(default_factory=list)
    avg_duration: float | None = None  # 平均执行时长

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "skill": self.skill.to_dict(),
            "confidence": round(self.confidence, 2),
            "evidence_tasks": self.evidence_tasks,
            "proposed_at": self.proposed_at,
            "reviewed": self.reviewed,
            "approved": self.approved,
            "reviewer_notes": self.reviewer_notes,
            "collaboration_agents": self.collaboration_agents,
            "avg_duration": self.avg_duration,
        }


# ── 任务类型关键词映射 ──

TASK_TYPE_KEYWORDS = {
    "web_scrape": ["网页", "网站", "抓取", "爬取", "scrape", "crawl", "fetch"],
    "code_gen": ["代码", "编程", "脚本", "code", "script", "implement"],
    "research": ["调研", "分析", "研究", "research", "analyze", "survey"],
    "document": ["文档", "报告", "总结", "document", "report", "summary"],
    "data_process": ["数据", "处理", "转换", "data", "process", "convert"],
    "file_op": ["文件", "批量", "重命名", "file", "batch", "rename"],
}

# ── 动作关键词映射 ──

ACTION_KEYWORDS = {
    "fetch_webpage": ["打开网页", "访问", "抓取页面", "open", "fetch", "access"],
    "extract_text": ["提取文本", "抽取内容", "extract", "scrape text"],
    "extract_table": ["提取表格", "抽取表格", "export csv", "table"],
    "screenshot": ["截图", "截屏", "screenshot", "capture"],
    "generate_report": ["生成报告", "写报告", "generate report", "create report"],
    "save_file": ["保存", "导出", "save", "export"],
    "parse_html": ["解析HTML", "解析页面", "parse html"],
    "api_call": ["调用API", "请求接口", "api call", "request"],
}


class ReplayEngine:
    """
    复刻引擎。
    从成功任务中提炼模式，生成可复用技能。
    支持置信度阈值控制和多 Agent 协作检测。
    """

    def __init__(
        self,
        task_repository: TaskRepository,
        skill_memory: SkillMemory,
        plugin_manager: PluginManager,
        confidence_threshold: float = 0.3,
        min_occurrences: int = 2,
    ):
        self.repository = task_repository
        self.skill_memory = skill_memory
        self.plugin_manager = plugin_manager
        self.confidence_threshold = confidence_threshold
        self.min_occurrences = min_occurrences

    def extract_pattern(self, task_id: str) -> TaskPattern | None:
        """从单个任务中提取模式"""
        task = self.repository.get_task(task_id)
        if not task:
            return None

        success = task.status == TaskStatus.SUCCESS

        # 提取可能使用的插件（从任务元数据或结果中推断）
        plugins_used = self._infer_plugins_used(task.goal, task.result_payload)

        # 提取执行步骤
        steps = self._extract_steps(task.goal, task.selected_agent.value, success)

        # 提取错误模式
        error_pattern = None
        if not success and task.error_message:
            error_pattern = self._extract_error_pattern(task.error_message)

        # 检测任务类型
        task_type = self._detect_task_type(task.goal)

        # 检测多 Agent 协作（如果任务结果包含协作信息）
        collaborating_agents = self._detect_collaboration(task.goal, task.result_payload)

        # 计算执行时长（从元数据中提取）
        duration = None
        if hasattr(task, 'metadata') and task.metadata:
            duration = task.metadata.get('duration')

        return TaskPattern(
            task_id=task_id,
            goal=task.goal,
            agent=task.selected_agent.value,
            success=success,
            duration=duration,
            plugins_used=plugins_used,
            steps_extracted=steps,
            error_pattern=error_pattern,
            task_type=task_type,
            collaborating_agents=collaborating_agents,
        )

    def _infer_plugins_used(self, goal: str, result: str | None) -> list[str]:
        """推断任务可能使用的插件"""
        plugins = []
        goal_lower = goal.lower()

        # 检查所有活跃插件的能力
        for plugin in self.plugin_manager.list_plugins():
            for cap in plugin.capabilities:
                # 检查能力关键词是否出现在目标中
                cap_keywords = cap.name.lower().replace("_", " ").split()
                if any(kw in goal_lower for kw in cap_keywords):
                    if plugin.name not in plugins:
                        plugins.append(plugin.name)

        return plugins

    def _detect_task_type(self, goal: str) -> str | None:
        """检测任务类型"""
        for task_type, keywords in TASK_TYPE_KEYWORDS.items():
            if any(kw in goal.lower() for kw in keywords):
                return task_type
        return None

    def _detect_collaboration(self, goal: str, result: str | None) -> list[str]:
        """检测多 Agent 协作"""
        collaborating = []
        goal_lower = goal.lower()

        # 检查目标中是否提到多个 Agent
        agent_names = ["openclaw", "hermes", "openhanako"]
        for agent in agent_names:
            if agent in goal_lower:
                collaborating.append(agent)

        # 检查结果中是否提到协作
        if result:
            result_lower = result.lower()
            for agent in agent_names:
                if agent in result_lower and agent not in collaborating:
                    collaborating.append(agent)

        return collaborating

    def _extract_steps(self, goal: str, agent: str, success: bool) -> list[dict]:
        """从目标描述中提取可能的执行步骤"""
        steps = []
        step_id = 1

        # 分析目标中的动作关键词
        for action, keywords in ACTION_KEYWORDS.items():
            for keyword in keywords:
                if keyword in goal.lower():
                    # 查找能执行此动作的插件
                    plugins = self.plugin_manager.find_plugins_for_capability(action)
                    plugin_name = plugins[0].name if plugins else None

                    steps.append({
                        "step_id": step_id,
                        "action": action,
                        "agent": agent,
                        "plugin": plugin_name,
                    })
                    step_id += 1
                    break

        # 如果没有提取到具体步骤，创建一个通用步骤
        if not steps:
            steps.append({
                "step_id": 1,
                "action": f"execute: {goal[:50]}",
                "agent": agent,
                "plugin": None,
            })

        return steps

    def _extract_error_pattern(self, error: str) -> str | None:
        """提取错误模式"""
        # 常见错误模式
        patterns = [
            (r"timeout|超时", "timeout"),
            (r"connection.*refused|连接.*拒绝", "connection_refused"),
            (r"permission.*denied|权限.*不足", "permission_denied"),
            (r"not.*found|找不到|未找到", "not_found"),
            (r"plugin.*error|插件.*错误", "plugin_error"),
            (r"rate.*limit|频率.*限制", "rate_limit"),
        ]

        for pattern, name in patterns:
            if re.search(pattern, error, re.IGNORECASE):
                return name

        return "unknown"

    def analyze_task_history(
        self,
        min_tasks: int = 3,
        lookback_days: int = 30,
    ) -> list[TaskPattern]:
        """分析任务历史，提取模式"""
        tasks = self.repository.list_tasks()

        patterns = []
        for task in tasks:
            pattern = self.extract_pattern(task.id)
            if pattern:
                patterns.append(pattern)

        return patterns

    def find_repeated_patterns(
        self,
        patterns: list[TaskPattern],
        min_occurrences: int | None = None,
    ) -> list[dict]:
        """查找重复出现的模式"""
        if min_occurrences is None:
            min_occurrences = self.min_occurrences

        # 按目标关键词分组
        goal_groups: dict[str, list[TaskPattern]] = {}

        for pattern in patterns:
            # 提取目标的关键词签名
            signature = self._compute_goal_signature(pattern.goal)
            if signature not in goal_groups:
                goal_groups[signature] = []
            goal_groups[signature].append(pattern)

        # 找出重复的模式
        repeated = []
        for signature, group in goal_groups.items():
            if len(group) >= min_occurrences:
                successful = [p for p in group if p.success]
                if len(successful) >= 1:  # 至少有一次成功
                    # 计算平均时长
                    durations = [p.duration for p in group if p.duration is not None]
                    avg_duration = sum(durations) / len(durations) if durations else None

                    # 收集所有涉及的 Agent（包括协作 Agent）
                    all_agents = set()
                    for p in group:
                        all_agents.add(p.agent)
                        all_agents.update(p.collaborating_agents)

                    repeated.append({
                        "signature": signature,
                        "count": len(group),
                        "success_count": len(successful),
                        "success_rate": len(successful) / len(group) * 100,
                        "sample_goals": [p.goal for p in group[:3]],
                        "common_agent": self._most_common([p.agent for p in group]),
                        "common_plugins": self._most_common(
                            [plug for p in group for plug in p.plugins_used]
                        ),
                        "avg_duration": avg_duration,
                        "all_agents": list(all_agents),
                        "task_type": self._most_common(
                            [p.task_type for p in group if p.task_type]
                        ),
                    })

        # 按出现次数排序
        repeated.sort(key=lambda x: x["count"], reverse=True)

        return repeated

    def _compute_goal_signature(self, goal: str) -> str:
        """计算目标的关键词签名"""
        # 移除数字和特殊字符
        cleaned = re.sub(r'[0-9\W_]+', ' ', goal.lower())

        # 提取关键词
        words = cleaned.split()

        # 识别任务类型
        for task_type, keywords in TASK_TYPE_KEYWORDS.items():
            if any(kw in goal.lower() for kw in keywords):
                return task_type

        # 如果无法识别类型，使用前几个关键词
        return ' '.join(words[:3]) if words else "unknown"

    def _most_common(self, items: list[str]) -> str | None:
        """获取最常见的元素"""
        if not items:
            return None

        from collections import Counter
        counter = Counter(items)
        return counter.most_common(1)[0][0] if counter else None

    def propose_skill_from_pattern(
        self,
        pattern: dict,
        evidence_tasks: list[str],
    ) -> SkillProposal:
        """从重复模式中提出新技能"""
        # 构建技能模板
        skill = SkillTemplate(
            name=f"auto_{pattern['signature']}",
            description=f"自动提取的技能：{', '.join(pattern['sample_goals'][:2])}",
            status=SkillStatus.DRAFT,
            source=SkillSource.AUTO_EXTRACT,
            trigger_keywords=pattern['signature'].split(),
            preferred_agents=[pattern['common_agent']] if pattern['common_agent'] else [],
            tags=["auto_extracted"],
        )

        # 支持多 Agent 协作
        if len(pattern.get('all_agents', [])) > 1:
            skill.preferred_agents = pattern['all_agents']
            skill.tags.append("multi_agent")

        # 添加步骤
        if pattern['common_plugins']:
            skill.steps.append(SkillStep(
                step_id=1,
                action=f"使用 {pattern['common_plugins']} 执行任务",
                agent=pattern['common_agent'] or "auto",
                plugin=pattern['common_plugins'],
            ))
            skill.required_plugins = [pattern['common_plugins']]
        else:
            skill.steps.append(SkillStep(
                step_id=1,
                action="执行任务",
                agent=pattern['common_agent'] or "auto",
            ))

        # 计算置信度（考虑多因素）
        confidence = min(pattern['count'] / 10, 0.5) + min(pattern['success_rate'] / 100, 0.5)

        # 多 Agent 协作奖励
        if len(pattern.get('all_agents', [])) > 1:
            confidence += 0.1

        return SkillProposal(
            skill=skill,
            confidence=confidence,
            evidence_tasks=evidence_tasks,
            collaboration_agents=pattern.get('all_agents', []),
            avg_duration=pattern.get('avg_duration'),
        )

    def auto_generate_skills(
        self,
        min_occurrences: int | None = None,
        min_confidence: float | None = None,
    ) -> list[SkillProposal]:
        """自动从历史任务生成技能提案"""
        if min_occurrences is None:
            min_occurrences = self.min_occurrences
        if min_confidence is None:
            min_confidence = self.confidence_threshold

        patterns = self.analyze_task_history()
        repeated = self.find_repeated_patterns(patterns, min_occurrences)

        proposals = []
        for rep in repeated:
            # 获取证据任务 ID
            evidence = [
                p.task_id for p in patterns
                if self._compute_goal_signature(p.goal) == rep['signature']
            ]

            proposal = self.propose_skill_from_pattern(rep, evidence)

            if proposal.confidence >= min_confidence:
                proposals.append(proposal)

        return proposals

    def record_task_outcome(
        self,
        task_id: str,
        success: bool,
        duration: float | None = None,
    ) -> None:
        """记录任务结果，更新相关技能"""
        pattern = self.extract_pattern(task_id)
        if not pattern:
            return

        # 查找匹配的技能
        skill = self.skill_memory.match_skill(pattern.goal)
        if skill:
            if success:
                skill.record_success(duration or 0)
            else:
                skill.record_failure(pattern.error_pattern or "unknown")
            self.skill_memory.update_skill(skill)


def build_replay_engine_from_env(
    task_repository: TaskRepository,
    skill_memory: SkillMemory,
    plugin_manager: PluginManager,
) -> ReplayEngine:
    """从环境变量构建复刻引擎"""
    import os
    confidence_threshold = float(os.getenv("REPLAY_CONFIDENCE_THRESHOLD", "0.3"))
    min_occurrences = int(os.getenv("REPLAY_MIN_OCCURRENCES", "2"))

    return ReplayEngine(
        task_repository=task_repository,
        skill_memory=skill_memory,
        plugin_manager=plugin_manager,
        confidence_threshold=confidence_threshold,
        min_occurrences=min_occurrences,
    )
