"""Tests for event_bus module"""

import asyncio
import pytest
from backend.event_bus import EventBus, EventTypes, NoHandlerError, BusTimeoutError


class TestEventBus:
    def setup_method(self):
        self.bus = EventBus()

    def test_subscribe_and_publish(self):
        """测试订阅和发布"""
        received = []

        def callback(event):
            received.append(event)

        self.bus.subscribe(callback, filter_types=["test.event"])
        self.bus.publish("test.event", {"key": "value"})

        assert len(received) == 1
        assert received[0].type == "test.event"
        assert received[0].data == {"key": "value"}

    def test_subscribe_with_filter(self):
        """测试带过滤的订阅"""
        received = []

        def callback(event):
            received.append(event)

        self.bus.subscribe(callback, filter_types=["type1", "type2"])

        self.bus.publish("type1", {})
        self.bus.publish("type3", {})  # 不匹配
        self.bus.publish("type2", {})

        assert len(received) == 2

    def test_unsubscribe(self):
        """测试取消订阅"""
        received = []

        def callback(event):
            received.append(event)

        unsub = self.bus.subscribe(callback, filter_types=["test"])
        self.bus.publish("test", {})
        assert len(received) == 1

        unsub()
        self.bus.publish("test", {})
        assert len(received) == 1  # 没有新事件

    def test_handler_register_and_request(self):
        """测试请求处理器"""
        def handler(data):
            return {"result": "ok", "input": data}

        self.bus.handle("test.request", handler)

        result = self.bus.request("test.request", {"key": "value"})
        assert result == {"result": "ok", "input": {"key": "value"}}

    def test_handler_not_found(self):
        """测试处理器未注册"""
        with pytest.raises(NoHandlerError):
            self.bus.request("nonexistent")

    def test_event_log(self):
        """测试事件日志"""
        self.bus = EventBus(persist_log=True)
        self.bus.publish("event1", {"a": 1})
        self.bus.publish("event2", {"b": 2})
        self.bus.publish("event1", {"a": 3})

        log = self.bus.get_event_log()
        assert len(log) == 3

        log_filtered = self.bus.get_event_log(event_type="event1")
        assert len(log_filtered) == 2

    def test_subscriber_count(self):
        """测试订阅者计数"""
        assert self.bus.subscriber_count == 0

        def callback(event):
            pass

        self.bus.subscribe(callback)
        assert self.bus.subscriber_count == 1

        self.bus.subscribe(callback)
        assert self.bus.subscriber_count == 2

    def test_handler_count(self):
        """测试处理器计数"""
        assert self.bus.handler_count == 0

        self.bus.handle("type1", lambda x: x)
        assert self.bus.handler_count == 1

        self.bus.handle("type2", lambda x: x)
        assert self.bus.handler_count == 2


class TestEventBusAsync:
    def setup_method(self):
        self.bus = EventBus()

    @pytest.mark.asyncio
    async def test_publish_async(self):
        """测试异步发布"""
        received = []

        async def callback(event):
            received.append(event)

        self.bus.subscribe(callback, filter_types=["test"])
        await self.bus.publish_async("test", {"key": "value"})

        assert len(received) == 1
        assert received[0].data == {"key": "value"}

    @pytest.mark.asyncio
    async def test_async_handler(self):
        """测试异步处理器"""
        async def handler(data):
            return {"async": True, "input": data}

        self.bus.handle("async.request", handler)

        result = await self.bus.request("async.request", {"test": 1})
        assert result == {"async": True, "input": {"test": 1}}

    @pytest.mark.asyncio
    async def test_request_timeout(self):
        """测试请求超时"""
        async def slow_handler(data):
            await asyncio.sleep(10)
            return {}

        self.bus.handle("slow.request", slow_handler)

        with pytest.raises(BusTimeoutError):
            await self.bus.request("slow.request", timeout_ms=100)


class TestEventTypes:
    def test_event_types_defined(self):
        """测试事件类型常量已定义"""
        assert EventTypes.TASK_STARTED == "task.started"
        assert EventTypes.TASK_COMPLETED == "task.completed"
        assert EventTypes.TASK_FAILED == "task.failed"
        assert EventTypes.AGENT_HEALTH_CHANGED == "agent.health_changed"
        assert EventTypes.SKILL_ACTIVATED == "skill.activated"
        assert EventTypes.REVIEW_APPROVED == "review.approved"
        assert EventTypes.PLUGIN_REGISTERED == "plugin.registered"
        assert EventTypes.SYSTEM_STARTUP == "system.startup"
