"""
event_bus.py — 统一事件总线

参考 OpenHanako hub/event-bus.js，实现松耦合的模块间通信。
支持订阅/发布和请求/响应两种模式。
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class NoHandlerError(Exception):
    """请求处理器未注册"""
    def __init__(self, request_type: str):
        self.request_type = request_type
        super().__init__(f'No handler registered for "{request_type}"')


class BusTimeoutError(Exception):
    """请求超时"""
    def __init__(self, request_type: str, timeout_ms: int):
        self.request_type = request_type
        self.timeout_ms = timeout_ms
        super().__init__(f'Request "{request_type}" timeout after {timeout_ms}ms')


@dataclass
class Event:
    """事件数据"""
    type: str
    data: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    source: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "data": self.data,
            "timestamp": self.timestamp,
            "source": self.source,
        }


@dataclass
class Subscription:
    """订阅信息"""
    id: int
    callback: Callable[[Event], Coroutine[Any, Any, None] | None]
    filter_types: set[str] | None = None
    filter_source: str | None = None

    def matches(self, event: Event) -> bool:
        """检查事件是否匹配过滤条件"""
        if self.filter_types and event.type not in self.filter_types:
            return False
        if self.filter_source and event.source != self.filter_source:
            return False
        return True


class EventBus:
    """
    统一事件总线。

    支持：
    - 订阅/发布模式
    - 请求/响应模式（供模块间调用）
    - 按事件类型和来源过滤
    - 异步回调
    """

    def __init__(self, max_subscribers: int = 100, persist_log: bool = False):
        self._subscribers: dict[int, Subscription] = {}
        self._handlers: dict[str, Callable] = {}
        self._next_id = 0
        self._max_subscribers = max_subscribers
        self._persist_log = persist_log
        self._event_log: list[Event] = []
        self._max_log_size = 1000

    # ── 订阅/发布模式 ──

    def subscribe(
        self,
        callback: Callable[[Event], Coroutine[Any, Any, None] | None],
        filter_types: list[str] | None = None,
        filter_source: str | None = None,
    ) -> Callable[[], None]:
        """
        订阅事件。

        Args:
            callback: 回调函数，接收 Event 参数
            filter_types: 只接收这些事件类型
            filter_source: 只接收来自特定来源的事件

        Returns:
            取消订阅的函数
        """
        if len(self._subscribers) >= self._max_subscribers:
            logger.warning(f"Subscriber limit reached ({self._max_subscribers})")

        self._next_id += 1
        sub_id = self._next_id

        subscription = Subscription(
            id=sub_id,
            callback=callback,
            filter_types=set(filter_types) if filter_types else None,
            filter_source=filter_source,
        )
        self._subscribers[sub_id] = subscription

        def unsubscribe():
            self._subscribers.pop(sub_id, None)

        return unsubscribe

    def publish(self, event_type: str, data: dict | None = None, source: str = ""):
        """
        发布事件（同步）。

        对于异步回调，使用 publish_async。
        """
        event = Event(type=event_type, data=data or {}, source=source)

        # 记录日志
        if self._persist_log:
            self._event_log.append(event)
            if len(self._event_log) > self._max_log_size:
                self._event_log = self._event_log[-self._max_log_size:]

        # 分发给订阅者
        for sub in list(self._subscribers.values()):
            if sub.matches(event):
                try:
                    result = sub.callback(event)
                    # 如果是协程，记录警告
                    if asyncio.iscoroutine(result):
                        logger.warning(
                            f"Async callback used in sync publish. "
                            f"Use publish_async for: {event_type}"
                        )
                except Exception as e:
                    logger.error(f"Event callback error: {e}")

        logger.debug(f"Published event: {event_type} (source={source})")

    async def publish_async(self, event_type: str, data: dict | None = None, source: str = ""):
        """
        发布事件（异步）。

        支持异步回调。
        """
        event = Event(type=event_type, data=data or {}, source=source)

        # 记录日志
        if self._persist_log:
            self._event_log.append(event)
            if len(self._event_log) > self._max_log_size:
                self._event_log = self._event_log[-self._max_log_size:]

        # 分发给订阅者
        tasks = []
        for sub in list(self._subscribers.values()):
            if sub.matches(event):
                try:
                    result = sub.callback(event)
                    if asyncio.iscoroutine(result):
                        tasks.append(result)
                except Exception as e:
                    logger.error(f"Event callback error: {e}")

        # 并发执行所有异步回调
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.debug(f"Published async event: {event_type} (source={source})")

    # ── 请求/响应模式 ──

    def handle(self, request_type: str, handler: Callable):
        """
        注册请求处理器。

        用于模块间调用，如插件请求 Agent 能力。
        """
        self._handlers[request_type] = handler
        logger.debug(f"Registered handler for: {request_type}")

    def remove_handler(self, request_type: str):
        """移除请求处理器"""
        self._handlers.pop(request_type, None)

    async def request(self, request_type: str, data: dict | None = None, timeout_ms: int = 30000) -> Any:
        """
        发送请求并等待响应。

        Args:
            request_type: 请求类型
            data: 请求数据
            timeout_ms: 超时时间（毫秒）

        Returns:
            响应数据

        Raises:
            NoHandlerError: 处理器未注册
            BusTimeoutError: 请求超时
        """
        handler = self._handlers.get(request_type)
        if not handler:
            raise NoHandlerError(request_type)

        try:
            # 支持同步和异步处理器
            result = handler(data or {})
            if asyncio.iscoroutine(result):
                result = await asyncio.wait_for(result, timeout=timeout_ms / 1000)
            return result
        except asyncio.TimeoutError:
            raise BusTimeoutError(request_type, timeout_ms)

    # ── 查询 ──

    def get_event_log(self, event_type: str | None = None, limit: int = 100) -> list[dict]:
        """获取事件日志"""
        events = self._event_log
        if event_type:
            events = [e for e in events if e.type == event_type]
        return [e.to_dict() for e in events[-limit:]]

    def list_subscriptions(self) -> list[dict]:
        """列出所有订阅"""
        return [
            {
                "id": sub.id,
                "filter_types": list(sub.filter_types) if sub.filter_types else None,
                "filter_source": sub.filter_source,
            }
            for sub in self._subscribers.values()
        ]

    def list_handlers(self) -> list[str]:
        """列出所有请求处理器"""
        return list(self._handlers.keys())

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @property
    def handler_count(self) -> int:
        return len(self._handlers)


# ── 预定义事件类型 ──

class EventTypes:
    """预定义事件类型常量"""

    # 任务生命周期
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_TIMEOUT = "task.timeout"
    TASK_CANCELLED = "task.cancelled"
    TASK_RETRYING = "task.retrying"
    TASK_WAITING = "task.waiting"

    # Agent 状态
    AGENT_HEALTH_CHANGED = "agent.health_changed"
    AGENT_RECOVERY_TRIGGERED = "agent.recovery_triggered"
    AGENT_STATUS_UPDATED = "agent.status_updated"

    # 技能事件
    SKILL_ACTIVATED = "skill.activated"
    SKILL_DISABLED = "skill.disabled"
    SKILL_EXTRACTED = "skill.extracted"
    SKILL_MATCHED = "skill.matched"
    SKILL_REGISTERED = "skill.registered"

    # 审查事件
    REVIEW_APPROVED = "review.approved"
    REVIEW_REJECTED = "review.rejected"
    REVIEW_AUTO_APPROVED = "review.auto_approved"
    REVIEW_SUBMITTED = "review.submitted"

    # 插件事件
    PLUGIN_REGISTERED = "plugin.registered"
    PLUGIN_ENABLED = "plugin.enabled"
    PLUGIN_DISABLED = "plugin.disabled"
    PLUGIN_CAPABILITY_ADDED = "plugin.capability_added"

    # 系统事件
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"
    SYSTEM_CONFIG_CHANGED = "system.config_changed"


# ── 全局事件总线实例 ──

_global_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """获取全局事件总线实例"""
    global _global_bus
    if _global_bus is None:
        _global_bus = EventBus()
    return _global_bus


def create_event_bus(**kwargs) -> EventBus:
    """创建新的事件总线实例"""
    return EventBus(**kwargs)
