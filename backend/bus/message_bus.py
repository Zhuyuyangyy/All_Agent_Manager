"""
message_bus.py - Agent 消息总线

Provides:
1. Direct messaging between agents
2. Broadcast messages
3. Topic-based subscriptions
4. Message persistence
"""

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4

logger = logging.getLogger(__name__)


class MessageType(str, Enum):
    """Message types"""
    DIRECT = "direct"
    BROADCAST = "broadcast"
    TOPIC = "topic"
    REQUEST = "request"
    RESPONSE = "response"


@dataclass
class AgentMessage:
    """Agent message"""
    message_id: str
    task_id: str
    from_agent: str
    to_agent: Optional[str]  # None means broadcast
    topic: Optional[str]
    content: str
    message_type: MessageType
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    reply_to: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "task_id": self.task_id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "topic": self.topic,
            "content": self.content,
            "message_type": self.message_type.value,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
            "reply_to": self.reply_to,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentMessage":
        return cls(
            message_id=data["message_id"],
            task_id=data["task_id"],
            from_agent=data["from_agent"],
            to_agent=data.get("to_agent"),
            topic=data.get("topic"),
            content=data["content"],
            message_type=MessageType(data["message_type"]),
            timestamp=data["timestamp"],
            metadata=data.get("metadata", {}),
            reply_to=data.get("reply_to"),
        )


class AgentMessageBus:
    """
    Agent message bus for inter-agent communication.

    Features:
    - Direct messaging between agents
    - Broadcast messages
    - Topic subscriptions
    - Message persistence
    - Async support
    """

    def __init__(self, persistence_path: Optional[Path] = None):
        self.persistence_path = persistence_path
        self._messages: List[AgentMessage] = []
        self._subscriptions: Dict[str, Set[str]] = defaultdict(set)
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)
        self._lock = asyncio.Lock()

        if persistence_path:
            self._load_messages()

    def _load_messages(self) -> None:
        """Load persisted messages"""
        if not self.persistence_path or not self.persistence_path.exists():
            return

        try:
            with open(self.persistence_path, "r") as f:
                data = json.load(f)
                self._messages = [
                    AgentMessage.from_dict(m) for m in data.get("messages", [])
                ]
            logger.info(f"[message-bus] Loaded {len(self._messages)} messages")
        except Exception as e:
            logger.warning(f"[message-bus] Failed to load messages: {e}")

    def _save_messages(self) -> None:
        """Persist messages"""
        if not self.persistence_path:
            return

        try:
            self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.persistence_path, "w") as f:
                json.dump({
                    "messages": [m.to_dict() for m in self._messages[-1000:]]
                }, f)
        except Exception as e:
            logger.warning(f"[message-bus] Failed to save messages: {e}")

    async def send_to_agent(
        self,
        from_agent: str,
        to_agent: str,
        content: str,
        task_id: str,
        metadata: Optional[Dict] = None,
    ) -> AgentMessage:
        """
        Send a direct message to a specific agent.

        Args:
            from_agent: Sender agent name
            to_agent: Receiver agent name
            content: Message content
            task_id: Associated task ID
            metadata: Optional metadata

        Returns:
            AgentMessage: The sent message
        """
        message = AgentMessage(
            message_id=str(uuid4()),
            task_id=task_id,
            from_agent=from_agent,
            to_agent=to_agent,
            topic=None,
            content=content,
            message_type=MessageType.DIRECT,
            timestamp=time.time(),
            metadata=metadata or {},
        )

        async with self._lock:
            self._messages.append(message)
            self._save_messages()

        logger.debug(f"[message-bus] {from_agent} -> {to_agent}: {content[:50]}...")
        await self._deliver_message(message)

        return message

    async def broadcast(
        self,
        from_agent: str,
        content: str,
        task_id: str,
        metadata: Optional[Dict] = None,
    ) -> AgentMessage:
        """
        Broadcast a message to all agents.

        Args:
            from_agent: Sender agent name
            content: Message content
            task_id: Associated task ID
            metadata: Optional metadata

        Returns:
            AgentMessage: The broadcast message
        """
        message = AgentMessage(
            message_id=str(uuid4()),
            task_id=task_id,
            from_agent=from_agent,
            to_agent=None,
            topic=None,
            content=content,
            message_type=MessageType.BROADCAST,
            timestamp=time.time(),
            metadata=metadata or {},
        )

        async with self._lock:
            self._messages.append(message)
            self._save_messages()

        logger.debug(f"[message-bus] {from_agent} broadcast: {content[:50]}...")
        await self._deliver_message(message)

        return message

    async def publish_topic(
        self,
        from_agent: str,
        topic: str,
        content: str,
        task_id: str,
        metadata: Optional[Dict] = None,
    ) -> AgentMessage:
        """
        Publish a message to a topic.

        Args:
            from_agent: Sender agent name
            topic: Topic name
            content: Message content
            task_id: Associated task ID
            metadata: Optional metadata

        Returns:
            AgentMessage: The published message
        """
        message = AgentMessage(
            message_id=str(uuid4()),
            task_id=task_id,
            from_agent=from_agent,
            to_agent=None,
            topic=topic,
            content=content,
            message_type=MessageType.TOPIC,
            timestamp=time.time(),
            metadata=metadata or {},
        )

        async with self._lock:
            self._messages.append(message)
            self._save_messages()

        logger.debug(f"[message-bus] {from_agent} published to {topic}: {content[:50]}...")
        await self._deliver_message(message)

        return message

    async def subscribe(self, agent: str, topic: str) -> None:
        """Subscribe an agent to a topic."""
        async with self._lock:
            self._subscriptions[topic].add(agent)
        logger.info(f"[message-bus] {agent} subscribed to {topic}")

    async def unsubscribe(self, agent: str, topic: str) -> None:
        """Unsubscribe an agent from a topic."""
        async with self._lock:
            self._subscriptions[topic].discard(agent)
        logger.info(f"[message-bus] {agent} unsubscribed from {topic}")

    def register_handler(
        self,
        agent: str,
        handler: Callable[[AgentMessage], Any],
    ) -> None:
        """Register a message handler for an agent."""
        self._handlers[agent].append(handler)

    async def _deliver_message(self, message: AgentMessage) -> None:
        """Deliver a message to appropriate handlers."""
        handlers_to_call = []

        async with self._lock:
            if message.message_type == MessageType.DIRECT and message.to_agent:
                handlers_to_call.extend(self._handlers.get(message.to_agent, []))
            elif message.message_type == MessageType.BROADCAST:
                for handlers in self._handlers.values():
                    handlers_to_call.extend(handlers)
            elif message.message_type == MessageType.TOPIC and message.topic:
                subscribers = self._subscriptions.get(message.topic, set())
                for subscriber in subscribers:
                    handlers_to_call.extend(self._handlers.get(subscriber, []))

        for handler in handlers_to_call:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(message)
                else:
                    handler(message)
            except Exception as e:
                logger.error(f"[message-bus] Handler error: {e}")

    def get_messages_by_task(self, task_id: str) -> List[AgentMessage]:
        """Get all messages for a specific task."""
        return [m for m in self._messages if m.task_id == task_id]

    def get_messages_by_agent(
        self,
        agent: str,
        limit: int = 50,
    ) -> List[AgentMessage]:
        """Get messages sent to or received by an agent."""
        result = [
            m for m in self._messages
            if m.to_agent == agent or m.from_agent == agent
        ]
        return result[-limit:]

    def get_messages_by_topic(
        self,
        topic: str,
        limit: int = 50,
    ) -> List[AgentMessage]:
        """Get messages for a specific topic."""
        result = [m for m in self._messages if m.topic == topic]
        return result[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Get message bus statistics."""
        return {
            "total_messages": len(self._messages),
            "topics": list(self._subscriptions.keys()),
            "subscriptions": {
                topic: len(agents) for topic, agents in self._subscriptions.items()
            },
            "message_types": {
                mt.value: sum(1 for m in self._messages if m.message_type == mt)
                for mt in MessageType
            },
        }
