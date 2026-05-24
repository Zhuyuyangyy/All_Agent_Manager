"""
execution_plan.py - 执行计划数据结构

定义多 Agent 协作的执行计划格式。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ExecutionMode(str, Enum):
    """执行模式"""
    SINGLE = "single"      # 单一 Agent
    PIPELINE = "pipeline"  # 串行 Pipeline
    PARALLEL = "parallel"  # 并行执行


@dataclass
class ExecutionStep:
    """
    执行步骤定义

    Attributes:
        agent: Agent 名称 (openclaw, openhanako, hermes)
        task: 任务描述
        input_from_previous: 是否使用上一步的输出作为输入
        timeout: 超时时间（秒），None 表示使用默认值
        retry: 重试次数
        required: 是否必须成功，False 表示失败后继续
    """
    agent: str
    task: str
    input_from_previous: bool = True  # Pipeline 模式下，默认使用上一步输出
    timeout: Optional[int] = None    # 秒，None 表示默认
    retry: int = 1
    required: bool = True            # True 表示必须成功

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "task": self.task,
            "input_from_previous": self.input_from_previous,
            "timeout": self.timeout,
            "retry": self.retry,
            "required": self.required,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionStep":
        return cls(
            agent=data["agent"],
            task=data["task"],
            input_from_previous=data.get("input_from_previous", True),
            timeout=data.get("timeout"),
            retry=data.get("retry", 1),
            required=data.get("required", True),
        )


@dataclass
class ExecutionPlan:
    """
    执行计划

    定义一个多 Agent 协作任务的完整执行计划。

    Attributes:
        plan_id: 计划唯一 ID
        mode: 执行模式
        steps: 执行步骤列表
        original_task: 用户原始任务
        context: 额外上下文
        metadata: 元数据
    """

    plan_id: str
    mode: ExecutionMode
    steps: List[ExecutionStep] = field(default_factory=list)
    original_task: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_step(self, agent: str, task: str, **kwargs) -> "ExecutionPlan":
        """链式添加步骤"""
        self.steps.append(ExecutionStep(agent=agent, task=task, **kwargs))
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "mode": self.mode.value,
            "steps": [s.to_dict() for s in self.steps],
            "original_task": self.original_task,
            "context": self.context,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionPlan":
        return cls(
            plan_id=data["plan_id"],
            mode=ExecutionMode(data.get("mode", "single")),
            steps=[ExecutionStep.from_dict(s) for s in data.get("steps", [])],
            original_task=data.get("original_task", ""),
            context=data.get("context", {}),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def single(cls, plan_id: str, agent: str, task: str) -> "ExecutionPlan":
        """创建单一 Agent 执行计划"""
        return cls(
            plan_id=plan_id,
            mode=ExecutionMode.SINGLE,
            steps=[ExecutionStep(agent=agent, task=task)],
            original_task=task,
        )

    @classmethod
    def pipeline(cls, plan_id: str, task: str, steps: List[tuple[str, str]]) -> "ExecutionPlan":
        """
        创建 Pipeline 执行计划

        Args:
            plan_id: 计划 ID
            task: 原始任务
            steps: [(agent, task_desc), ...] 元组列表

        Example:
            plan = ExecutionPlan.pipeline(
                "plan_001",
                "帮我分析项目并整理成用户友好的总结",
                [
                    ("hermes", "分析项目的整体结构和当前进度"),
                    ("openhanako", "将分析结果改写成用户友好的表达"),
                ]
            )
        """
        execution_steps = [
            ExecutionStep(agent=agent, task=task_desc)
            for agent, task_desc in steps
        ]
        return cls(
            plan_id=plan_id,
            mode=ExecutionMode.PIPELINE,
            steps=execution_steps,
            original_task=task,
        )

    @classmethod
    def parallel(cls, plan_id: str, task: str, steps: List[tuple[str, str]]) -> "ExecutionPlan":
        """
        创建 Parallel 执行计划

        Args:
            plan_id: 计划 ID
            task: 原始任务
            steps: [(agent, task_desc), ...] 元组列表

        Example:
            plan = ExecutionPlan.parallel(
                "plan_002",
                "全面检查项目当前状态",
                [
                    ("openclaw", "检查代码结构和接口问题"),
                    ("hermes", "分析项目路线和长期缺口"),
                    ("openhanako", "整理成用户容易理解的表达"),
                ]
            )
        """
        execution_steps = [
            ExecutionStep(agent=agent, task=task_desc, input_from_previous=False)
            for agent, task_desc in steps
        ]
        return cls(
            plan_id=plan_id,
            mode=ExecutionMode.PARALLEL,
            steps=execution_steps,
            original_task=task,
        )


@dataclass
class StepResult:
    """步骤执行结果"""
    step_index: int
    agent: str
    status: str  # completed, failed, skipped
    result: str
    error: Optional[str] = None
    duration: float = 0.0  # 秒
    retry_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_index": self.step_index,
            "agent": self.agent,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "duration": self.duration,
            "retry_count": self.retry_count,
        }


@dataclass
class PlanResult:
    """执行计划结果"""
    plan_id: str
    mode: ExecutionMode
    status: str  # completed, failed, partial
    step_results: List[StepResult] = field(default_factory=list)
    final_result: str = ""
    error: Optional[str] = None
    total_duration: float = 0.0  # 秒

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "mode": self.mode.value,
            "status": self.status,
            "step_results": [s.to_dict() for s in self.step_results],
            "final_result": self.final_result,
            "error": self.error,
            "total_duration": self.total_duration,
        }

    @property
    def success(self) -> bool:
        return self.status == "completed"

    @property
    def failed_steps(self) -> List[StepResult]:
        return [s for s in self.step_results if s.status == "failed"]
