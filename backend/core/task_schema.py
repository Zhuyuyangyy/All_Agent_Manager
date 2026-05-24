"""
task_schema.py — 统一任务格式

所有 Agent 的输入输出都必须符合这个格式。
中控只认识这两个数据类。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentTask:
    """统一任务输入格式"""

    task_id: str
    user_id: str
    source: str  # "wechat", "api", "web", etc.
    content: str  # 任务内容/用户消息
    task_type: str = "general"  # 任务类型
    project: Optional[str] = None  # 关联项目
    priority: str = "normal"  # low, normal, high, urgent
    context: Dict[str, Any] = field(default_factory=dict)  # 额外上下文

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "source": self.source,
            "content": self.content,
            "task_type": self.task_type,
            "project": self.project,
            "priority": self.priority,
            "context": self.context,
        }


@dataclass
class AgentResult:
    """统一任务输出格式"""

    task_id: str
    agent_name: str
    status: str  # "completed", "failed", "pending", "running"
    result: str  # 结果文本
    error: Optional[str] = None
    artifacts: List[str] = field(default_factory=list)  # 产出的文件/链接
    logs: List[str] = field(default_factory=list)  # 执行日志
    metadata: Dict[str, Any] = field(default_factory=dict)  # 额外元数据

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "agent_name": self.agent_name,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "artifacts": self.artifacts,
            "logs": self.logs,
            "metadata": self.metadata,
        }
