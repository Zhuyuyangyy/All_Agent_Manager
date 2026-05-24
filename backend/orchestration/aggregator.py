"""
aggregator.py - 结果聚合器

将多个 Agent 的执行结果聚合为统一的回复。
"""

from dataclasses import dataclass
from typing import List, Optional
import logging

from backend.orchestration.execution_plan import StepResult, PlanResult, ExecutionMode

logger = logging.getLogger(__name__)


@dataclass
class AggregationConfig:
    """聚合配置"""
    include_agent_names: bool = True          # 是否在结果中包含 Agent 名称
    include_durations: bool = True            # 是否包含执行时长
    separate_sections: bool = True            # 是否分节显示
    max_result_length: int = 2000             # 单个结果最大长度
    summary_first: bool = False               # 是否将总结放在最前面


class ResultAggregator:
    """
    多 Agent 结果聚合器

    将多个 Agent 的执行结果聚合为一个统一的、用户友好的回复。
    """

    def __init__(self, config: Optional[AggregationConfig] = None):
        self.config = config or AggregationConfig()

    def aggregate(self, plan_result: PlanResult) -> str:
        """
        聚合多个步骤的结果

        Args:
            plan_result: 执行计划结果

        Returns:
            聚合后的统一回复
        """
        if not plan_result.step_results:
            return "没有执行结果"

        # 根据执行模式选择聚合策略
        if plan_result.mode == ExecutionMode.SINGLE:
            return self._aggregate_single(plan_result)
        elif plan_result.mode == ExecutionMode.PIPELINE:
            return self._aggregate_pipeline(plan_result)
        elif plan_result.mode == ExecutionMode.PARALLEL:
            return self._aggregate_parallel(plan_result)
        else:
            return self._aggregate_default(plan_result)

    def _aggregate_single(self, plan_result: PlanResult) -> str:
        """单一 Agent 结果聚合"""
        step = plan_result.step_results[0]
        
        if step.status == "failed":
            return f"❌ 执行失败：{step.error or '未知错误'}"
        
        return step.result

    def _aggregate_pipeline(self, plan_result: PlanResult) -> str:
        """Pipeline 结果聚合 - 展示执行流程"""
        parts = []
        
        if self.config.separate_sections:
            parts.append("📋 **执行流程**\n")
        else:
            parts.append("执行流程：\n")
        
        for i, step in enumerate(plan_result.step_results):
            agent_emoji = self._get_agent_emoji(step.agent)
            
            if step.status == "failed":
                if self.config.include_agent_names:
                    parts.append(f"{agent_emoji} **{step.agent}**: ❌ 失败 - {step.error or '未知错误'}")
                else:
                    parts.append(f"❌ 步骤 {i+1} 失败 - {step.error or '未知错误'}")
            else:
                if self.config.include_agent_names:
                    parts.append(f"{agent_emoji} **{step.agent}**: {step.result[:self.config.max_result_length]}")
                else:
                    parts.append(f"步骤 {i+1}: {step.result[:self.config.max_result_length]}")
                
                if self.config.include_durations:
                    parts.append(f"   ⏱️ 耗时: {step.duration:.1f}s")
        
        # 最终结果
        if plan_result.final_result:
            parts.append("\n✨ **最终结果**")
            parts.append(plan_result.final_result)
        
        return "\n".join(parts)

    def _aggregate_parallel(self, plan_result: PlanResult) -> str:
        """Parallel 结果聚合 - 分模块展示"""
        parts = []
        
        if self.config.separate_sections:
            parts.append("🔍 **并行检查结果**\n")
        else:
            parts.append("并行检查结果：\n")
        
        # 按 Agent 分组展示
        for step in plan_result.step_results:
            agent_emoji = self._get_agent_emoji(step.agent)
            
            if self.config.include_agent_names:
                header = f"{agent_emoji} **{step.agent.upper()}**"
            else:
                header = f"检查项 {step.step_index + 1}"
            
            if step.status == "failed":
                parts.append(f"{header}: ❌ 失败 - {step.error or '未知错误'}")
            else:
                result_text = step.result[:self.config.max_result_length]
                if len(step.result) > self.config.max_result_length:
                    result_text += "..."
                parts.append(f"{header}:\n{result_text}")
            
            if self.config.include_durations:
                parts.append(f"   ⏱️ 耗时: {step.duration:.1f}s")
        
        # 汇总
        if plan_result.final_result:
            parts.append("\n📊 **汇总**")
            parts.append(plan_result.final_result)
        else:
            # 自动生成汇总
            summary = self._generate_summary(plan_result)
            if summary:
                parts.append("\n📊 **汇总**")
                parts.append(summary)
        
        return "\n".join(parts)

    def _aggregate_default(self, plan_result: PlanResult) -> str:
        """默认聚合策略"""
        parts = []
        
        for step in plan_result.step_results:
            if step.status == "failed":
                parts.append(f"❌ {step.agent}: {step.error or '失败'}")
            else:
                parts.append(f"✅ {step.agent}: {step.result[:self.config.max_result_length]}")
        
        return "\n".join(parts)

    def _generate_summary(self, plan_result: PlanResult) -> str:
        """自动生成汇总"""
        success_count = sum(1 for s in plan_result.step_results if s.status == "completed")
        total_count = len(plan_result.step_results)
        
        if success_count == total_count:
            summary = f"全部 {total_count} 项检查完成 ✅"
        elif success_count > 0:
            summary = f"{success_count}/{total_count} 项检查完成 ⚠️"
        else:
            summary = "所有检查失败 ❌"
        
        # 包含总耗时
        if self.config.include_durations and plan_result.total_duration > 0:
            summary += f"，总耗时 {plan_result.total_duration:.1f}s"
        
        return summary

    def _get_agent_emoji(self, agent_name: str) -> str:
        """获取 Agent 对应的表情符号"""
        emoji_map = {
            "openclaw": "🔧",
            "openhanako": "💬",
            "hermes": "🧠",
            "router": "🎯",
        }
        return emoji_map.get(agent_name.lower(), "📌")

    def aggregate_raw(self, results: List[StepResult]) -> str:
        """
        直接聚合原始结果列表（不依赖 PlanResult）

        Args:
            results: 步骤结果列表

        Returns:
            聚合后的回复
        """
        plan_result = PlanResult(
            plan_id="raw",
            mode=ExecutionMode.PARALLEL if len(results) > 1 else ExecutionMode.SINGLE,
            status="completed" if all(r.status == "completed" for r in results) else "partial",
            step_results=results,
        )
        return self.aggregate(plan_result)
