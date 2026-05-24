"""
orchestration 模块 - 多 Agent 协作编排

支持三种协作模式：
1. Single: 单一 Agent 执行
2. Pipeline: 多个 Agent 串行执行（上一个的输出作为下一个的输入）
3. Parallel: 多个 Agent 并行执行，最后聚合结果

示例：
{
  "mode": "parallel",
  "steps": [
    {"agent": "openclaw", "task": "检查代码结构"},
    {"agent": "hermes", "task": "分析项目路线"},
  ]
}
"""

from .execution_plan import ExecutionPlan, ExecutionStep, ExecutionMode
from .orchestrator import MultiAgentOrchestrator
from .aggregator import ResultAggregator

__all__ = [
    "ExecutionPlan",
    "ExecutionStep",
    "ExecutionMode",
    "MultiAgentOrchestrator",
    "ResultAggregator",
]
