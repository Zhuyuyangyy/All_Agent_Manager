"""
websocket_events.py — WebSocket 事件推送

将 EventBus 事件实时推送到前端 WebSocket 连接。
支持多客户端订阅、事件过滤、心跳检测。
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Callable

from fastapi import WebSocket, WebSocketDisconnect

from backend.event_bus import EventBus, Event, EventTypes

logger = logging.getLogger(__name__)


class WebSocketManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self._connections: dict[str, WebSocket] = {}
        self._subscriptions: dict[str, set[str]] = {}  # event_type -> {connection_ids}
        self._next_id = 0

    def connect(self, websocket: WebSocket) -> str:
        """接受新的 WebSocket 连接"""
        asyncio.create_task(websocket.accept())
        self._next_id += 1
        conn_id = f"conn_{self._next_id}"
        self._connections[conn_id] = websocket
        logger.info(f"WebSocket connected: {conn_id}")
        return conn_id

    def disconnect(self, conn_id: str):
        """断开 WebSocket 连接"""
        self._connections.pop(conn_id, None)
        # 清理订阅
        for event_type, subscribers in self._subscriptions.items():
            subscribers.discard(conn_id)
        logger.info(f"WebSocket disconnected: {conn_id}")

    async def send_to_all(self, message: dict):
        """向所有连接发送消息"""
        disconnected = []
        for conn_id, ws in self._connections.items():
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(conn_id)

        for conn_id in disconnected:
            self.disconnect(conn_id)

    async def send_to_connection(self, conn_id: str, message: dict):
        """向指定连接发送消息"""
        ws = self._connections.get(conn_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(conn_id)

    def subscribe(self, conn_id: str, event_type: str):
        """订阅特定事件类型"""
        if event_type not in self._subscriptions:
            self._subscriptions[event_type] = set()
        self._subscriptions[event_type].add(conn_id)

    def unsubscribe(self, conn_id: str, event_type: str):
        """取消订阅"""
        if event_type in self._subscriptions:
            self._subscriptions[event_type].discard(conn_id)

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    def list_connections(self) -> list[str]:
        return list(self._connections.keys())


class EventBridge:
    """EventBus 到 WebSocket 的桥接器"""

    def __init__(self, event_bus: EventBus, ws_manager: WebSocketManager):
        self._event_bus = event_bus
        self._ws_manager = ws_manager
        self._unsubscribers: list[Callable[[], None]] = []

    def start(self):
        """启动事件桥接"""
        # 订阅所有任务相关事件
        task_events = [
            EventTypes.TASK_STARTED,
            EventTypes.TASK_COMPLETED,
            EventTypes.TASK_FAILED,
            EventTypes.TASK_TIMEOUT,
            EventTypes.TASK_CANCELLED,
            EventTypes.TASK_RETRYING,
            EventTypes.TASK_WAITING,
        ]

        for event_type in task_events:
            unsub = self._event_bus.subscribe(
                callback=lambda event: self._on_event(event),
                filter_types=[event_type],
            )
            self._unsubscribers.append(unsub)

        # 订阅 Agent 事件
        agent_events = [
            EventTypes.AGENT_HEALTH_CHANGED,
            EventTypes.AGENT_RECOVERY_TRIGGERED,
        ]

        for event_type in agent_events:
            unsub = self._event_bus.subscribe(
                callback=lambda event: self._on_event(event),
                filter_types=[event_type],
            )
            self._unsubscribers.append(unsub)

        # 订阅技能和审查事件
        skill_events = [
            EventTypes.SKILL_ACTIVATED,
            EventTypes.SKILL_DISABLED,
            EventTypes.REVIEW_APPROVED,
            EventTypes.REVIEW_REJECTED,
        ]

        for event_type in skill_events:
            unsub = self._event_bus.subscribe(
                callback=lambda event: self._on_event(event),
                filter_types=[event_type],
            )
            self._unsubscribers.append(unsub)

        logger.info("EventBridge started")

    def stop(self):
        """停止事件桥接"""
        for unsub in self._unsubscribers:
            unsub()
        self._unsubscribers.clear()
        logger.info("EventBridge stopped")

    async def _on_event(self, event: Event):
        """处理事件并推送到 WebSocket"""
        message = {
            "type": "event",
            "event_type": event.type,
            "data": event.data,
            "timestamp": event.timestamp,
            "source": event.source,
        }

        await self._ws_manager.send_to_all(message)


# ── FastAPI WebSocket 端点 ──

def create_websocket_routes(app, ws_manager: WebSocketManager, event_bus: EventBus):
    """创建 WebSocket 路由"""

    @app.websocket("/ws/events")
    async def websocket_events(websocket: WebSocket):
        """WebSocket 事件流端点"""
        conn_id = ws_manager.connect(websocket)

        try:
            # 发送连接确认
            await ws_manager.send_to_connection(conn_id, {
                "type": "connected",
                "connection_id": conn_id,
                "timestamp": datetime.now().isoformat(),
            })

            # 监听客户端消息
            while True:
                try:
                    data = await asyncio.wait_for(
                        websocket.receive_json(),
                        timeout=30.0,  # 30 秒心跳超时
                    )

                    # 处理订阅请求
                    if data.get("action") == "subscribe":
                        event_type = data.get("event_type")
                        if event_type:
                            ws_manager.subscribe(conn_id, event_type)
                            await ws_manager.send_to_connection(conn_id, {
                                "type": "subscribed",
                                "event_type": event_type,
                            })

                    # 处理取消订阅
                    elif data.get("action") == "unsubscribe":
                        event_type = data.get("event_type")
                        if event_type:
                            ws_manager.unsubscribe(conn_id, event_type)
                            await ws_manager.send_to_connection(conn_id, {
                                "type": "unsubscribed",
                                "event_type": event_type,
                            })

                    # 处理心跳
                    elif data.get("action") == "ping":
                        await ws_manager.send_to_connection(conn_id, {
                            "type": "pong",
                            "timestamp": datetime.now().isoformat(),
                        })

                except asyncio.TimeoutError:
                    # 发送心跳检测
                    try:
                        await ws_manager.send_to_connection(conn_id, {
                            "type": "heartbeat",
                            "timestamp": datetime.now().isoformat(),
                        })
                    except Exception:
                        break

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            ws_manager.disconnect(conn_id)

    @app.get("/ws/status")
    async def websocket_status():
        """WebSocket 连接状态"""
        return {
            "connections": ws_manager.connection_count,
            "connection_ids": ws_manager.list_connections(),
        }
