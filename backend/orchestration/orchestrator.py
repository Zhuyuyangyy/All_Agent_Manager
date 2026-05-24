"""
orchestrator.py - 多 Agent 编排器

实际执行 ExecutionPlan，协调多个 Agent 的协作。
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from backend.core.router import AgentRouter
from backend.core.task_schema import AgentTask, AgentResult
from backend.orchestration.execution_plan import (
    ExecutionPlan,
    ExecutionMode,
    PlanResult,
    StepResult,
)
from backend.orchestration.aggregator import ResultAggregator, AggregationConfig

logger = logging.getLogger(__name__)


class MultiAgentOrchestrator:
    """
    多 Agent 编排器

    负责：
    1. 解析和验证 ExecutionPlan
    2. 根据执行模式协调多个 Agent
    3. 处理执行过程中的错误和回退
    4. 聚合最终结果
    """

    def __init__(
        self,
        agent_router: AgentRouter,
        aggregator: Optional[ResultAggregator] = None,
    ):
        self.router = agent_router
        self.aggregator = aggregator or ResultAggregator()
        self._execution_history: List[PlanResult] = []

    async def execute(self, plan: ExecutionPlan) -> PlanResult:
        """
        执行一个 ExecutionPlan

        Args:
            plan: 执行计划

        Returns:
            PlanResult: 执行结果
        """
        start_time = time.time()
        plan_result = PlanResult(
            plan_id=plan.plan_id,
            mode=plan.mode,
            status="running",
        )

        logger.info(
            f"[orchestrator] 开始执行 plan={plan.plan_id}, "
            f"mode={plan.mode.value}, steps={len(plan.steps)}"
        )

        try:
            # 根据模式执行
            if plan.mode == ExecutionMode.SINGLE:
                step_result = await self._execute_single(plan, 0)
                plan_result.step_results = [step_result]
            elif plan.mode == ExecutionMode.PIPELINE:
                plan_result.step_results = await self._execute_pipeline(plan)
            elif plan.mode == ExecutionMode.PARALLEL:
                plan_result.step_results = await self._execute_parallel(plan)
            else:
                raise ValueError(f"Unknown execution mode: {plan.mode}")

            # 确定最终状态
            failed_steps = plan_result.failed_steps
            if not failed_steps:
                plan_result.status = "completed"
            elif len(failed_steps) == len(plan.steps):
                plan_result.status = "failed"
            else:
                plan_result.status = "partial"

            # 生成最终结果
            plan_result.final_result = self.aggregator.aggregate(plan_result)

        except Exception as e:
            logger.error(f"[orchestrator] 执行失败: {e}", exc_info=True)
            plan_result.status = "failed"
            plan_result.error = str(e)

        plan_result.total_duration = time.time() - start_time
        
        # 记录历史
        self._execution_history.append(plan_result)
        if len(self._execution_history) > 100:
            self._execution_history = self._execution_history[-50:]

        logger.info(
            f"[orchestrator] 执行完成 plan={plan.plan_id}, "
            f"status={plan_result.status}, duration={plan_result.total_duration:.2f}s"
        )

        return plan_result

    async def _execute_single(
        self,
        plan: ExecutionPlan,
        step_index: int,
    ) -> StepResult:
        """执行单一 Agent"""
        return await self._execute_step(plan, step_index, None)

    async def _execute_pipeline(self, plan: ExecutionPlan) -> List[StepResult]:
        """执行 Pipeline（串行）"""
        results: List[StepResult] = []
        previous_output: Optional[str] = None

        for i, step in enumerate(plan.steps):
            # 如果需要，使用上一步的输出
            if step.input_from_previous and previous_output:
                # 将上一步的输出追加到当前任务
                enhanced_task = f"{step.task}\n\n上一步结果：\n{previous_output}"
                step_result = await self._execute_step_with_task(plan, i, enhanced_task)
            else:
                step_result = await self._execute_step(plan, i, previous_output)
            
            results.append(step_result)
            previous_output = step_result.result if step_result.status == "completed" else None

            # 如果必须成功但失败了，停止执行
            if step.required and step_result.status == "failed":
                logger.warning(f"[orchestrator] Pipeline 步骤 {i} 必须成功但失败了，停止执行")
                break

        return results

    async def _execute_parallel(self, plan: ExecutionPlan) -> List[StepResult]:
        """执行 Parallel（并行）"""
        tasks = [
            self._execute_step(plan, i, None)
            for i in range(len(plan.steps))
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        step_results: List[StepResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                # 并行任务异常
                step_results.append(StepResult(
                    step_index=i,
                    agent=plan.steps[i].agent,
                    status="failed",
                    result="",
                    error=str(result),
                ))
            else:
                step_results.append(result)
        
        return step_results

    async def _execute_step(
        self,
        plan: ExecutionPlan,
        step_index: int,
        context: Optional[str],
    ) -> StepResult:
        """执行单个步骤"""
        step = plan.steps[step_index]
        task_content = step.task if context is None else f"{context}\n\n任务：{step.task}"
        
        return await self._execute_step_with_task(plan, step_index, task_content)

    async def _execute_step_with_task(
        self,
        plan: ExecutionPlan,
        step_index: int,
        task_content: str,
    ) -> StepResult:
        """使用指定任务内容执行步骤"""
        step = plan.steps[step_index]
        start_time = time.time()
        retry_count = 0

        logger.info(
            f"[orchestrator] 执行步骤 {step_index}: agent={step.agent}, "
            f"task={task_content[:50]}..."
        )

        # 创建任务
        task = AgentTask(
            task_id=f"{plan.plan_id}_step_{step_index}",
            user_id=plan.context.get("user_id", "system"),
            source="orchestrator",
            content=task_content,
            task_type="orchestrated",
            project=plan.context.get("project"),
        )

        # 获取 Agent
        agent = self.router.get_agent(step.agent)
        if not agent:
            return StepResult(
                step_index=step_index,
                agent=step.agent,
                status="failed",
                result="",
                error=f"Agent {step.agent} not found",
                duration=time.time() - start_time,
            )

        # 执行（带重试）
        last_error = None
        for attempt in range(step.retry):
            try:
                result = await agent.run_async(task)
                retry_count = attempt
                
                if result.status == "completed":
                    return StepResult(
                        step_index=step_index,
                        agent=step.agent,
                        status="completed",
                        result=result.result,
                        duration=time.time() - start_time,
                        retry_count=retry_count,
                    )
                else:
                    last_error = result.error or "Agent returned non-success status"
                    
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"[orchestrator] 步骤 {step_index} 第 {attempt+1} 次尝试失败: {e}"
                )

        # 所有重试都失败
        return StepResult(
            step_index=step_index,
            agent=step.agent,
            status="failed",
            result="",
            error=last_error or "Max retries exceeded",
            duration=time.time() - start_time,
            retry_count=retry_count,
        )

    def create_plan_from_task(self, task: str, mode: ExecutionMode) -> ExecutionPlan:
        """
        根据任务内容自动创建执行计划

        Args:
            task: 用户任务
            mode: 执行模式

        Returns:
            ExecutionPlan
        """
        plan_id = f"auto_{uuid4().hex[:8]}"
        
        # 简单的关键词分析
        task_lower = task.lower()
        
        if "分析" in task and ("项目" in task or "路线" in task):
            # Pipeline: 分析 + 整理
            return ExecutionPlan.pipeline(
                plan_id,
                task,
                [
                    ("hermes", "分析项目或任务的关键点"),
                    ("hanako", "将分析结果整理成简洁易懂的用户回复"),
                ]
            )
        elif any(k in task_lower for k in ["检查", "缺什么", "有哪些问题"]):
            # Parallel: 多维度检查
            return ExecutionPlan.parallel(
                plan_id,
                task,
                [
                    ("openclaw", "检查代码结构、接口和技术实现"),
                    ("hermes", "分析项目架构和长期规划"),
                    ("hanako", "整理成用户容易理解的表达"),
                ]
            )
        elif any(k in task_lower for k in ["代码", "函数", "bug", "报错", "修复"]):
            # Single: 代码任务
            return ExecutionPlan.single(plan_id, "openclaw", task)
        elif any(k in task_lower for k in ["聊", "陪我", "心情", "解释"]):
            # Single: 聊天任务
            return ExecutionPlan.single(plan_id, "hanako", task)
        elif any(k in task_lower for k in ["调度", "分发", "编排", "协调", "指挥", "iliya", "伊利亚", "dispatch", "orchestrate"]):
            # Single: 调度任务
            return ExecutionPlan.single(plan_id, "iliya", task)
        else:
            # Default: Hermes
            return ExecutionPlan.single(plan_id, "hermes", task)

    def get_history(self, limit: int = 20) -> List[Dict]:
        """获取执行历史"""
        return [r.to_dict() for r in self._execution_history[-limit:]]

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        total = len(self._execution_history)
        if total == 0:
            return {"total": 0}

        completed = sum(1 for r in self._execution_history if r.status == "completed")
        failed = sum(1 for r in self._execution_history if r.status == "failed")
        partial = sum(1 for r in self._execution_history if r.status == "partial")

        avg_duration = sum(r.total_duration for r in self._execution_history) / total

        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "partial": partial,
            "success_rate": round(completed / total * 100, 1),
            "avg_duration": round(avg_duration, 2),
        }
