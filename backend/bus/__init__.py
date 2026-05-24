"""
message_bus.py - Agent 消息总线

实现 Agent 间的消息传递和共享上下文。
"""

from .message_bus import AgentMessageBus, AgentMessage
from .shared_context import SharedContext

__all__ = [
    "AgentMessageBus",
    "AgentMessage",
    "SharedContext",
]
