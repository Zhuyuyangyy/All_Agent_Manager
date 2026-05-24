"""
bridge_manager.py — 外部平台接入管理器

统一管理微信等外部消息平台的生命周期。
每个平台一个 adapter，消息到达后路由到 All-Agent 任务系统。

参考 openhanako 的 bridge-manager.js 架构。
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from backend.wechat_adapter import InboundMessage, WechatAdapter

logger = logging.getLogger(__name__)


# ── 微信 Token 持久化 ──

WECHAT_TOKEN_FILE = "wechat_token.json"


def _save_wechat_token(data_dir: Path, bot_token: str, bot_id: str = "", user_id: str = ""):
    """保存微信 token 到配置文件"""
    token_file = data_dir / WECHAT_TOKEN_FILE
    try:
        data = {
            "bot_token": bot_token,
            "bot_id": bot_id,
            "user_id": user_id,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        token_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        logger.info(f"[bridge] wechat token saved to {token_file}")
    except Exception as e:
        logger.error(f"[bridge] failed to save wechat token: {e}")


def _load_wechat_token(data_dir: Path) -> Optional[dict]:
    """从配置文件加载微信 token"""
    token_file = data_dir / WECHAT_TOKEN_FILE
    if not token_file.exists():
        return None
    try:
        data = json.loads(token_file.read_text("utf-8"))
        if data.get("bot_token"):
            logger.info(f"[bridge] wechat token loaded from {token_file}")
            return data
    except Exception as e:
        logger.error(f"[bridge] failed to load wechat token: {e}")
    return None


def _clear_wechat_token(data_dir: Path):
    """清除保存的微信 token"""
    token_file = data_dir / WECHAT_TOKEN_FILE
    if token_file.exists():
        try:
            token_file.unlink()
            logger.info("[bridge] wechat token cleared")
        except Exception as e:
            logger.error(f"[bridge] failed to clear wechat token: {e}")


# ── 消息处理器类型 ──

MessageHandler = Callable[[str, InboundMessage], None]


# ── 平台状态 ──

@dataclass
class PlatformStatus:
    """平台连接状态"""
    platform: str
    status: str  # "disconnected", "connecting", "connected", "error"
    error: Optional[str] = None
    agent_id: Optional[str] = None


@dataclass
class MessageLog:
    """消息日志条目"""
    platform: str
    direction: str  # "in" or "out"
    session_key: str
    agent_id: Optional[str]
    sender: str
    text: str
    is_group: bool
    ts: float


class BridgeManager:
    """
    外部平台接入管理器

    参考 openhanako 的 BridgeManager，但简化为 Python 版本。
    管理多个平台的 adapter 生命周期，并将消息路由到任务系统。
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        on_task_request: Optional[Callable[[InboundMessage], str]] = None,
        on_message_async: Optional[Callable] = None,
    ):
        """
        Args:
            data_dir: 数据目录（用于持久化 cursor 等）
            on_task_request: 收到消息时的回调（同步，创建任务），返回 task_id
            on_message_async: 收到消息时的异步回调（用于微信聊天），签名: async (platform, msg) -> None
        """
        self.data_dir = data_dir
        self.on_task_request = on_task_request
        self.on_message_async = on_message_async

        self._platforms: dict[str, dict] = {}  # key -> {adapter, status, error, agent_id, platform}
        self._message_logs: dict[str, list[MessageLog]] = {}  # agent_id -> [MessageLog]
        self._message_log_max = 200
        self._status_callbacks: list[Callable] = []

    def _get_platform_key(self, platform: str, agent_id: Optional[str] = None) -> str:
        return f"{platform}:{agent_id}" if agent_id else platform

    # ── 状态回调 ──

    def on_status_change(self, callback: Callable):
        """注册状态变化回调"""
        self._status_callbacks.append(callback)

    def _emit_status(self, platform: str, status: str, error: Optional[str] = None, agent_id: Optional[str] = None):
        for cb in self._status_callbacks:
            try:
                cb(platform, status, error, agent_id)
            except Exception as err:
                logger.error(f"Status callback error: {err}")

    # ── 消息日志 ──

    def _push_message(self, entry: MessageLog):
        agent_id = entry.agent_id or "_global"
        if agent_id not in self._message_logs:
            self._message_logs[agent_id] = []
        log = self._message_logs[agent_id]
        log.append(entry)
        if len(log) > self._message_log_max:
            log.pop(0)

    def get_messages(self, limit: int = 50, offset: int = 0, agent_id: Optional[str] = None) -> dict:
        """获取最近消息日志，支持分页"""
        def _msg_dict(m: MessageLog) -> dict:
            return {
                "platform": m.platform,
                "direction": m.direction,
                "session_key": m.session_key,
                "agent_id": m.agent_id,
                "sender": m.sender,
                "text": m.text,
                "is_group": m.is_group,
                "ts": m.ts,
            }

        if agent_id:
            log = self._message_logs.get(agent_id, [])
        else:
            # 合并所有日志
            log = []
            for agent_log in self._message_logs.values():
                log.extend(agent_log)
            log.sort(key=lambda m: m.ts)

        total = len(log)
        # 分页：取最新的 offset+limit 条，然后截取 limit 条
        page_items = log[-(offset + limit): -offset if offset > 0 else None]
        messages = [_msg_dict(m) for m in page_items]

        return {"messages": messages, "total": total, "limit": limit, "offset": offset}

    # ── 微信平台管理 ──

    async def start_wechat(self, bot_token: str, agent_id: Optional[str] = None, save_token: bool = True) -> PlatformStatus:
        """
        启动微信连接（参考 OpenHanako 的 connectsAsync 模式）

        创建 adapter 后立即启动轮询，adapter 通过 onStatus 回调报告连接状态。
        不再在启动前单独验证 token — 轮询本身会验证，失败时报告 error。

        Args:
            bot_token: 微信 bot token
            agent_id: agent ID
            save_token: 是否保存 token 到配置文件（默认 True）
        """
        key = self._get_platform_key("wechat", agent_id)
        await self.stop_platform("wechat", agent_id)

        adapter = WechatAdapter(
            bot_token=bot_token,
            agent_id=agent_id,
            data_dir=self.data_dir,
            on_message=lambda msg: self._handle_message("wechat", msg),
            on_status=lambda status, error=None: self._update_platform_status(
                "wechat", status, error, agent_id
            ),
        )

        self._platforms[key] = {
            "adapter": adapter,
            "status": "connecting",
            "error": None,
            "agent_id": agent_id,
            "platform": "wechat",
        }

        self._emit_status("wechat", "connecting", None, agent_id)

        try:
            # 立即启动轮询 — adapter 会通过 onStatus 报告 connected/error
            await adapter.start()
            logger.info(f"[bridge] wechat adapter started (agent_id={agent_id})")

            # 保存 token 到配置文件
            if save_token and self.data_dir:
                _save_wechat_token(self.data_dir, bot_token)

            # 返回 connecting 状态，实际 connected 由 adapter 回调报告
            return PlatformStatus(platform="wechat", status="connecting", agent_id=agent_id)
        except Exception as err:
            logger.error(f"[bridge] wechat start failed: {err}")
            self._platforms[key]["status"] = "error"
            self._platforms[key]["error"] = str(err)
            self._emit_status("wechat", "error", str(err), agent_id)
            return PlatformStatus(platform="wechat", status="error", error=str(err), agent_id=agent_id)

    async def auto_connect_wechat(self, agent_id: Optional[str] = None) -> bool:
        """
        自动重连微信（从配置文件读取保存的 token）

        参考 OpenHanako 的 autoStart()，在服务器启动时调用。
        如果有保存的 token，自动重连；否则需要用户扫码。

        Returns:
            bool: 是否成功启动重连（注意：不代表连接成功，连接状态由回调报告）
        """
        if not self.data_dir:
            logger.info("[bridge] no data_dir, skip auto-connect")
            return False

        saved = _load_wechat_token(self.data_dir)
        if not saved or not saved.get("bot_token"):
            logger.info("[bridge] no saved wechat token, need QR code scan")
            return False

        bot_token = saved["bot_token"]
        logger.info(f"[bridge] auto-connecting wechat with saved token (bot_id={saved.get('bot_id', 'unknown')})")

        try:
            await self.start_wechat(bot_token=bot_token, agent_id=agent_id, save_token=False)
            return True
        except Exception as e:
            logger.error(f"[bridge] auto-connect wechat failed: {e}")
            return False

    def get_saved_wechat_token(self) -> Optional[dict]:
        """获取保存的微信 token 信息（不返回完整 token，只返回状态）"""
        if not self.data_dir:
            return None
        saved = _load_wechat_token(self.data_dir)
        if not saved:
            return None
        return {
            "has_token": bool(saved.get("bot_token")),
            "bot_id": saved.get("bot_id", ""),
            "user_id": saved.get("user_id", ""),
            "saved_at": saved.get("saved_at", ""),
        }

    def clear_saved_wechat_token(self):
        """清除保存的微信 token"""
        if self.data_dir:
            _clear_wechat_token(self.data_dir)

    def _update_platform_status(self, platform: str, status: str, error: Optional[str], agent_id: Optional[str]):
        key = self._get_platform_key(platform, agent_id)
        entry = self._platforms.get(key)
        if entry:
            entry["status"] = status
            entry["error"] = error
        self._emit_status(platform, status, error, agent_id)

    async def stop_platform(self, platform: str, agent_id: Optional[str] = None):
        """停止指定平台"""
        key = self._get_platform_key(platform, agent_id)
        entry = self._platforms.get(key)
        if not entry:
            return

        adapter = entry.get("adapter")
        if adapter and hasattr(adapter, "stop"):
            try:
                await adapter.stop()
            except Exception:
                pass

        del self._platforms[key]
        logger.info(f"[bridge] {platform} stopped")
        self._emit_status(platform, "disconnected", None, agent_id)

    async def stop_all(self):
        """停止所有平台"""
        keys = list(self._platforms.keys())
        for key in keys:
            entry = self._platforms[key]
            platform = entry.get("platform", "unknown")
            agent_id = entry.get("agent_id")
            adapter = entry.get("adapter")
            if adapter and hasattr(adapter, "stop"):
                try:
                    await adapter.stop()
                except Exception:
                    pass
            self._emit_status(platform, "disconnected", None, agent_id)
        self._platforms.clear()
        logger.info("[bridge] all platforms stopped")

    def get_status(self, agent_id: Optional[str] = None) -> dict:
        """获取平台状态"""
        result = {}
        for key, entry in self._platforms.items():
            if agent_id and entry.get("agent_id") != agent_id:
                continue
            platform = entry.get("platform", "unknown")
            result[platform] = {
                "status": entry.get("status", "disconnected"),
                "error": entry.get("error"),
                "agent_id": entry.get("agent_id"),
            }
        return result

    # ── 消息处理 ──

    def _handle_message(self, platform: str, msg: InboundMessage):
        """收到外部消息"""
        logger.info(f"[bridge] <- {platform} ({len(msg.text)} chars) from={msg.sender_name} chat_id={msg.chat_id}")

        # 记录消息
        self._push_message(MessageLog(
            platform=platform,
            direction="in",
            session_key=msg.session_key,
            agent_id=msg.agent_id,
            sender=msg.sender_name or "用户",
            text=msg.text or (f"[{len(msg.attachments)} 个附件]" if msg.attachments else ""),
            is_group=msg.is_group,
            ts=time.time(),
        ))

        # 优先使用异步消息处理器（微信聊天模式）
        if self.on_message_async:
            logger.info(f"[bridge] 调用 on_message_async...")
            try:
                task = asyncio.create_task(self.on_message_async(platform, msg))
                # 捕获异步任务中的异常（否则会静默丢失）
                def _task_done(t):
                    if t.exception():
                        logger.error(f"[bridge] on_message_async 任务异常: {t.exception()}", exc_info=t.exception())
                task.add_done_callback(_task_done)
            except Exception as err:
                logger.error(f"[bridge] on_message_async 失败: {err}", exc_info=True)
            return

        # 降级到任务系统
        if self.on_task_request:
            logger.info(f"[bridge] 调用 on_task_request...")
            try:
                task_id = self.on_task_request(msg)
                logger.info(f"[bridge] task 已创建: {task_id}")
            except Exception as err:
                logger.error(f"[bridge] task routing 失败: {err}", exc_info=True)
        else:
            logger.warning(f"[bridge] on_task_request 为空，消息未处理!")

    # ── 发送回复 ──

    async def send_reply(self, platform: str, chat_id: str, text: str, agent_id: Optional[str] = None):
        """发送回复到外部平台"""
        key = self._get_platform_key(platform, agent_id)
        entry = self._platforms.get(key)
        if not entry or not entry.get("adapter"):
            raise Exception(f"Platform {platform} not connected")

        adapter = entry["adapter"]
        if not hasattr(adapter, "send_reply"):
            raise Exception(f"Platform {platform} does not support send_reply")

        await adapter.send_reply(chat_id, text)

        # 记录消息
        self._push_message(MessageLog(
            platform=platform,
            direction="out",
            session_key=f"{platform}_dm_{chat_id}@{agent_id or 'default'}",
            agent_id=agent_id,
            sender="All-Agent",
            text=text,
            is_group=False,
            ts=time.time(),
        ))

    async def send_task_result(self, platform: str, chat_id: str, task_id: str, result: str, agent_id: Optional[str] = None):
        """发送任务执行结果到外部平台"""
        text = f"[任务 {task_id[:8]}...]\n{result}"
        await self.send_reply(platform, chat_id, text, agent_id)

    async def send_task_error(self, platform: str, chat_id: str, task_id: str, error: str, agent_id: Optional[str] = None):
        """发送任务执行错误到外部平台"""
        text = f"[任务 {task_id[:8]}... 执行失败]\n{error}"
        await self.send_reply(platform, chat_id, text, agent_id)

    # ── QQ 平台管理 ──

    async def start_qq(
        self,
        ws_url: str = "ws://127.0.0.1:6700",
        http_url: str = "http://127.0.0.1:5700",
        access_token: Optional[str] = None,
        agent_id: Optional[str] = None,
        save_config: bool = True,
    ) -> PlatformStatus:
        key = self._get_platform_key("qq", agent_id)
        await self.stop_platform("qq", agent_id)

        from backend.qq_adapter import QQAdapter

        adapter = QQAdapter(
            ws_url=ws_url,
            http_url=http_url,
            access_token=access_token,
            agent_id=agent_id,
            data_dir=self.data_dir,
            on_message=lambda msg: self._handle_message("qq", msg),
            on_status=lambda status, error=None: self._update_platform_status(
                "qq", status, error, agent_id
            ),
        )

        self._platforms[key] = {
            "adapter": adapter,
            "status": "connecting",
            "error": None,
            "agent_id": agent_id,
            "platform": "qq",
        }

        self._emit_status("qq", "connecting", None, agent_id)

        try:
            await adapter.start()
            logger.info(f"[bridge] qq adapter started (agent_id={agent_id})")

            if save_config and self.data_dir:
                config_dir = self.data_dir / "bridge" / "qq"
                config_dir.mkdir(parents=True, exist_ok=True)
                config_file = config_dir / "config.json"
                config_data = {
                    "ws_url": ws_url,
                    "http_url": http_url,
                    "access_token": access_token or "",
                    "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
                config_file.write_text(
                    json.dumps(config_data, ensure_ascii=False, indent=2), "utf-8"
                )

            return PlatformStatus(platform="qq", status="connecting", agent_id=agent_id)
        except Exception as err:
            logger.error(f"[bridge] qq start failed: {err}")
            self._platforms[key]["status"] = "error"
            self._platforms[key]["error"] = str(err)
            self._emit_status("qq", "error", str(err), agent_id)
            return PlatformStatus(platform="qq", status="error", error=str(err), agent_id=agent_id)

    async def auto_connect_qq(self, agent_id: Optional[str] = None) -> bool:
        if not self.data_dir:
            logger.info("[bridge] no data_dir, skip qq auto-connect")
            return False

        config_file = self.data_dir / "bridge" / "qq" / "config.json"
        if not config_file.exists():
            logger.info("[bridge] no saved qq config, skip auto-connect")
            return False

        try:
            data = json.loads(config_file.read_text("utf-8"))
            ws_url = data.get("ws_url", "ws://127.0.0.1:6700")
            http_url = data.get("http_url", "http://127.0.0.1:5700")
            access_token = data.get("access_token") or None

            logger.info(f"[bridge] auto-connecting qq: ws={ws_url}")
            await self.start_qq(
                ws_url=ws_url,
                http_url=http_url,
                access_token=access_token,
                agent_id=agent_id,
                save_config=False,
            )
            return True
        except Exception as e:
            logger.error(f"[bridge] qq auto-connect failed: {e}")
            return False
