"""
qq_adapter.py — QQ OneBot v11 WebSocket Adapter

基于 OneBot v11 协议（go-cqhttp / Lagrange / NapCat 等）实现。
通过 WebSocket 接收消息，通过 HTTP API 发送消息。
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Optional

import httpx
import websockets

from backend.wechat_adapter import InboundMessage

logger = logging.getLogger(__name__)

DEFAULT_WS_URL = "ws://127.0.0.1:6700"
DEFAULT_HTTP_URL = "http://127.0.0.1:5700"
BACKOFF_DELAYS = [2, 5, 30]
MSG_CHUNK_LIMIT = 4000


class QQAdapter:

    def __init__(
        self,
        ws_url: str = DEFAULT_WS_URL,
        access_token: Optional[str] = None,
        agent_id: Optional[str] = None,
        data_dir: Optional[Path] = None,
        on_message: Optional[Callable[[InboundMessage], None]] = None,
        on_status: Optional[Callable[[str, Optional[str]], None]] = None,
        http_url: str = DEFAULT_HTTP_URL,
    ):
        self.ws_url = ws_url
        self.http_url = http_url
        self.access_token = access_token
        self.agent_id = agent_id
        self.data_dir = data_dir
        self.on_message = on_message
        self.on_status = on_status

        self._running = False
        self._ws = None
        self._ws_task: Optional[asyncio.Task] = None
        self._generation = 0
        self._bot_qq_id: Optional[str] = None
        self._last_status: Optional[str] = None
        self._last_error: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None

        self._processed_msg_ids: dict[str, float] = {}
        self._processed_msg_cleanup: float = 0
        self._MSG_DEDUP_WINDOW: float = 30.0
        self._msg_processed_count: int = 0
        self._msg_skipped_count: int = 0

        self._load_config()

    def _config_path(self) -> Optional[Path]:
        if not self.data_dir:
            return None
        config_dir = self.data_dir / "bridge" / "qq"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "qq_config.json"

    def _load_config(self):
        path = self._config_path()
        if not path or not path.exists():
            return
        try:
            data = json.loads(path.read_text("utf-8"))
            self.ws_url = data.get("ws_url", self.ws_url)
            self.http_url = data.get("http_url", self.http_url)
            self.access_token = data.get("access_token", self.access_token)
            logger.info(f"[qq] loaded config: ws_url={self.ws_url}, http_url={self.http_url}")
        except Exception as e:
            logger.error(f"[qq] load config failed: {e}")

    def _save_config(self):
        path = self._config_path()
        if not path:
            return
        try:
            path.write_text(
                json.dumps({
                    "ws_url": self.ws_url,
                    "http_url": self.http_url,
                    "access_token": self.access_token,
                }, ensure_ascii=False, indent=2),
                "utf-8",
            )
        except Exception as e:
            logger.error(f"[qq] save config failed: {e}")

    def _report_status(self, status: str, error: Optional[str] = None):
        if self._last_status == status and self._last_error == error:
            return
        self._last_status = status
        self._last_error = error
        if self.on_status:
            if error:
                self.on_status(status, error)
            else:
                self.on_status(status)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {}
            if self.access_token:
                headers["Authorization"] = f"Bearer {self.access_token}"
            self._client = httpx.AsyncClient(
                timeout=15,
                limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
                headers=headers,
            )
        return self._client

    async def _http_api(self, action: str, params: dict) -> dict:
        client = self._get_client()
        url = f"{self.http_url}/{action}"
        try:
            response = await client.post(url, json=params)
            response.raise_for_status()
            data = response.json()
            if data.get("retcode") is not None and data["retcode"] != 0:
                raise Exception(
                    f"OneBot API error: retcode={data['retcode']} "
                    f"msg={data.get('msg', '')} wording={data.get('wording', '')}"
                )
            return data
        except httpx.ConnectError as err:
            logger.error(f"[qq] connect error on {action}: {err}")
            raise
        except httpx.TimeoutException:
            raise

    async def _get_login_info(self) -> Optional[str]:
        try:
            data = await self._http_api("get_login_info", {})
            user_id = str(data.get("data", {}).get("user_id", ""))
            nickname = data.get("data", {}).get("nickname", "")
            if user_id:
                self._bot_qq_id = user_id
                logger.info(f"[qq] bot info: qq={user_id}, nickname={nickname}")
            return user_id
        except Exception as e:
            logger.error(f"[qq] get_login_info failed: {e}")
            return None

    def _extract_text_from_message(self, message: list[dict]) -> str:
        parts = []
        for seg in message:
            if seg.get("type") == "text":
                parts.append(seg.get("data", {}).get("text", ""))
        return "".join(parts).strip()

    def _is_at_bot(self, message: list[dict]) -> bool:
        if not self._bot_qq_id:
            return False
        for seg in message:
            if seg.get("type") == "at":
                qq = str(seg.get("data", {}).get("qq", ""))
                if qq == self._bot_qq_id:
                    return True
        return False

    def _strip_at_prefix(self, message: list[dict]) -> list[dict]:
        result = []
        for seg in message:
            if seg.get("type") == "at" and str(seg.get("data", {}).get("qq", "")) == self._bot_qq_id:
                continue
            result.append(seg)
        return result

    def _handle_event(self, event: dict):
        post_type = event.get("post_type", "")
        if post_type != "message":
            return

        message_type = event.get("message_type", "")
        if message_type not in ("private", "group"):
            return

        user_id = str(event.get("user_id", ""))
        if not user_id:
            return

        message = event.get("message", [])
        if isinstance(message, str):
            message = [{"type": "text", "data": {"text": message}}]

        is_group = message_type == "group"
        group_id = str(event.get("group_id", "")) if is_group else ""

        if is_group:
            if not self._is_at_bot(message):
                return
            message = self._strip_at_prefix(message)

        text = self._extract_text_from_message(message)
        if not text:
            return

        now = time.time()
        raw_msg_id = str(event.get("message_id", ""))
        if not raw_msg_id:
            raw_msg_id = f"{user_id}:{text[:50]}"

        if now - self._processed_msg_cleanup > 60.0:
            expired_keys = [
                k for k, ts in self._processed_msg_ids.items()
                if now - ts > self._MSG_DEDUP_WINDOW
            ]
            for k in expired_keys:
                del self._processed_msg_ids[k]
            self._processed_msg_cleanup = now

        if raw_msg_id in self._processed_msg_ids:
            self._msg_skipped_count += 1
            logger.info(f"[qq] duplicate message skipped: msg_id={raw_msg_id}, skipped_total={self._msg_skipped_count}")
            return

        self._processed_msg_ids[raw_msg_id] = now
        self._msg_processed_count += 1

        if is_group:
            chat_id = f"group_{group_id}"
            sender_name = event.get("sender", {}).get("card") or event.get("sender", {}).get("nickname", "QQ用户")
        else:
            chat_id = f"private_{user_id}"
            sender_name = event.get("sender", {}).get("nickname", "QQ用户")

        logger.info(f"[qq] message: type={message_type}, chat_id={chat_id}, user={sender_name}, text={text[:50]}..., processed_total={self._msg_processed_count}")

        inbound = InboundMessage(
            platform="qq",
            chat_id=chat_id,
            user_id=user_id,
            session_key=f"qq_{message_type}_{chat_id}@{self.agent_id or 'default'}",
            text=text,
            sender_name=sender_name,
            is_group=is_group,
            attachments=[],
            agent_id=self.agent_id,
        )

        if self.on_message:
            self.on_message(inbound)

    async def _ws_loop(self):
        my_gen = self._generation
        consecutive_failures = 0

        while my_gen == self._generation:
            try:
                headers = {}
                if self.access_token:
                    headers["Authorization"] = f"Bearer {self.access_token}"

                async with websockets.connect(
                    self.ws_url,
                    additional_headers=headers,
                    ping_interval=30,
                    ping_timeout=10,
                ) as ws:
                    self._ws = ws
                    consecutive_failures = 0
                    self._report_status("connected")
                    logger.info(f"[qq] websocket connected: {self.ws_url}")

                    await self._get_login_info()

                    async for raw in ws:
                        if my_gen != self._generation:
                            return
                        try:
                            event = json.loads(raw)
                            self._handle_event(event)
                        except json.JSONDecodeError:
                            logger.warning(f"[qq] invalid JSON from websocket")
                        except Exception as err:
                            logger.error(f"[qq] handle event error: {err}")

            except asyncio.CancelledError:
                return
            except websockets.ConnectionClosed as err:
                if my_gen != self._generation:
                    return
                logger.warning(f"[qq] websocket closed: code={err.code} reason={err.reason}")
            except Exception as err:
                if my_gen != self._generation:
                    return
                logger.error(f"[qq] websocket error: {err}")
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    self._report_status("error", str(err))

            self._ws = None

            if my_gen != self._generation:
                return

            delay = BACKOFF_DELAYS[min(consecutive_failures - 1, len(BACKOFF_DELAYS) - 1)]
            logger.info(f"[qq] reconnecting in {delay}s (attempt {consecutive_failures})")
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return

    async def start(self):
        if self._running:
            return
        self._running = True
        self._save_config()
        self._ws_task = asyncio.create_task(self._ws_loop())
        logger.info("[qq] adapter started")

    async def stop(self):
        self._generation += 1
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None
        if self._client and not self._client.is_closed:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None
        self._report_status("disconnected")
        logger.info("[qq] adapter stopped")

    async def send_reply(self, chat_id: str, text: str):
        logger.info(f"[qq] send_reply chat_id={chat_id} text_len={len(text)}")

        for i in range(0, len(text), MSG_CHUNK_LIMIT):
            chunk = text[i:i + MSG_CHUNK_LIMIT]
            if chat_id.startswith("private_"):
                user_id = chat_id[len("private_"):]
                await self._http_api("send_private_msg", {
                    "user_id": int(user_id),
                    "message": chunk,
                })
            elif chat_id.startswith("group_"):
                group_id = chat_id[len("group_"):]
                await self._http_api("send_group_msg", {
                    "group_id": int(group_id),
                    "message": chunk,
                })
            else:
                logger.warning(f"[qq] unknown chat_id format: {chat_id}")
                raise Exception(f"QQ: 无法识别的 chat_id 格式: {chat_id}")

    async def get_me(self) -> dict:
        try:
            user_id = await self._get_login_info()
            if user_id:
                return {"ok": True, "platform": "qq", "user_id": user_id}
            raise Exception("无法获取 QQ 登录信息")
        except Exception as err:
            logger.error(f"[qq] get_me failed: {err}")
            raise Exception(f"QQ 连接验证失败: {err}")

    @property
    def capabilities(self) -> dict:
        return {"proactive": True}

    def can_reply(self, chat_id: str) -> bool:
        return True
