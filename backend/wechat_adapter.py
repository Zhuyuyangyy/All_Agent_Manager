"""
wechat_adapter.py — 微信 iLink Bridge Adapter (Python)

基于腾讯 iLink 协议（ilinkai.weixin.qq.com）实现。
参考 openhanako 的 wechat-adapter.js（MIT 协议）。
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

logger = logging.getLogger(__name__)

# ── iLink 常量 ──

DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"

LONG_POLL_TIMEOUT_MS = 40_000
MAX_CONSECUTIVE_FAILURES = 3
BACKOFF_DELAYS = [2, 5, 30]
CONTEXT_TOKEN_TTL_MS = 24 * 60 * 60 * 1000
MSG_CHUNK_LIMIT = 4000


# ── iLink 消息类型常量 ──

class MessageItemType:
    TEXT = 1
    IMAGE = 2
    VOICE = 3
    FILE = 4
    VIDEO = 5


class MessageType:
    USER = 1
    BOT = 2


class MessageState:
    FINISH = 2


class UploadMediaType:
    IMAGE = 1
    VIDEO = 2
    FILE = 3


# ── AES-128-ECB 加解密 ──

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend

    def encrypt_aes_ecb(plaintext: bytes, key: bytes) -> bytes:
        cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
        encryptor = cipher.encryptor()
        # PKCS7 padding
        pad_len = 16 - (len(plaintext) % 16)
        padded = plaintext + bytes([pad_len] * pad_len)
        return encryptor.update(padded) + encryptor.finalize()

    def decrypt_aes_ecb(ciphertext: bytes, key: bytes) -> bytes:
        cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(ciphertext) + decryptor.finalize()
        # Remove PKCS7 padding
        pad_len = decrypted[-1]
        return decrypted[:-pad_len]

    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False
    logger.warning("cryptography library not available, AES encryption disabled")


def aes_ecb_padded_size(plaintext_size: int) -> int:
    return ((plaintext_size + 1) // 16 + 1) * 16


def parse_aes_key(aes_key_base64: str) -> bytes:
    """解析 aes_key：base64 -> 16 字节原始 key"""
    decoded = base64.b64decode(aes_key_base64)
    if len(decoded) == 16:
        return decoded
    if len(decoded) == 32 and all(c in "0123456789abcdefABCDEF" for c in decoded.decode("ascii")):
        return bytes.fromhex(decoded.decode("ascii"))
    raise ValueError(f"invalid aes_key length: {len(decoded)}")


# ── 数据类 ──

@dataclass
class InboundMessage:
    """从微信收到的消息"""
    platform: str = "wechat"
    chat_id: str = ""
    user_id: str = ""
    session_key: str = ""
    text: str = ""
    sender_name: str = "微信用户"
    is_group: bool = False
    attachments: list[dict] = field(default_factory=list)
    context_token: Optional[str] = None
    agent_id: Optional[str] = None


@dataclass
class MediaUploadResult:
    """CDN 上传结果"""
    filekey: str
    download_param: str
    aeskey: str
    file_size: int
    file_size_ciphertext: int


# ── 辅助函数 ──

def random_wechat_uin() -> str:
    import random
    uint32 = random.getrandbits(32)
    return base64.b64encode(str(uint32).encode("utf-8")).decode("ascii")


def build_headers(token: Optional[str] = None) -> dict:
    headers = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": random_wechat_uin(),
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def extract_text(item_list: list[dict]) -> str:
    """从 item_list 提取文本"""
    if not item_list:
        return ""
    for item in item_list:
        if item.get("type") == MessageItemType.TEXT and item.get("text_item", {}).get("text") is not None:
            text = str(item["text_item"]["text"])
            ref = item.get("ref_msg")
            if not ref:
                return text
            ref_msg_item = ref.get("message_item")
            if ref_msg_item and ref_msg_item.get("type") in (
                MessageItemType.IMAGE, MessageItemType.VIDEO,
                MessageItemType.FILE, MessageItemType.VOICE
            ):
                return text
            parts = []
            if ref.get("title"):
                parts.append(ref["title"])
            if ref_msg_item:
                ref_body = extract_text([ref_msg_item])
                if ref_body:
                    parts.append(ref_body)
            if not parts:
                return text
            return f"[引用: {' | '.join(parts)}]\n{text}"
        if item.get("type") == MessageItemType.VOICE and item.get("voice_item", {}).get("text"):
            return item["voice_item"]["text"]
    return ""


def is_session_expired_error(err: Exception) -> bool:
    message = str(err)
    import re
    return bool(re.search(r"(?:ret|errcode)=-14\b", message))


# ── 微信扫码登录 ──

LOGIN_HEADERS = {
    "iLink-App-ClientVersion": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

BOT_TYPE = "3"


async def get_wechat_qrcode() -> dict:
    """
    获取微信扫码登录二维码

    通过 iLink API 获取二维码，返回 base64 图片和 qrcode ID。
    前端显示二维码后，用户用微信扫码确认。

    Returns:
        dict: { ok, qrcode_url (base64 or API URL), qrcode_id, error }
    """
    try:
        url = f"{DEFAULT_BASE_URL}/ilink/bot/get_bot_qrcode?bot_type={BOT_TYPE}"
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, headers=LOGIN_HEADERS)
            response.raise_for_status()
            data = response.json()

        logger.info(f"[wechat-login] iLink 响应: {data}")

        if not data.get("qrcode"):
            return {"ok": False, "error": "服务器未返回二维码"}

        # qrcode_img_content 是要被编码成二维码的 URL 文本
        qr_text = data.get("qrcode_img_content") or data.get("qrcode")
        qrcode_id = data.get("qrcode", "")

        # 尝试用 Python 生成二维码 base64
        qrcode_url = None
        try:
            import qrcode
            from io import BytesIO

            qr = qrcode.QRCode(version=1, box_size=10, border=2)
            qr.add_data(qr_text)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            qrcode_url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
            logger.info("[wechat-login] 使用本地 qrcode 库生成图片")
        except ImportError:
            logger.info("[wechat-login] qrcode 库未安装，使用在线 API")
        except Exception as e:
            logger.warning(f"[wechat-login] 本地生成二维码失败: {e}")

        # 如果本地生成失败，使用在线 QR code API
        if not qrcode_url:
            from urllib.parse import quote
            qr_text_encoded = quote(qr_text, safe='')
            qrcode_url = f"https://api.qrserver.com/v1/create-qr-code/?size=280x280&data={qr_text_encoded}"
            logger.info(f"[wechat-login] 使用在线 API: {qrcode_url[:80]}...")

        return {
            "ok": True,
            "qrcode_url": qrcode_url,
            "qrcode_id": qrcode_id,
        }
    except httpx.HTTPStatusError as err:
        logger.error(f"[wechat-login] iLink API HTTP 错误: {err.response.status_code} {err.response.text[:200]}")
        return {"ok": False, "error": f"iLink API 错误: HTTP {err.response.status_code}"}
    except httpx.ConnectError as err:
        logger.error(f"[wechat-login] 无法连接 iLink 服务器: {err}")
        return {"ok": False, "error": "无法连接微信服务器，请检查网络"}
    except Exception as err:
        logger.error(f"[wechat-login] 获取二维码失败: {err}", exc_info=True)
        return {"ok": False, "error": str(err)}


async def poll_wechat_qrcode_status(qrcode_id: str) -> dict:
    """
    轮询微信扫码状态

    iLink 服务器会 hold 连接最多 35 秒（长轮询）。

    Args:
        qrcode_id: 从 get_wechat_qrcode 获取的 qrcode 值

    Returns:
        dict: { status, bot_token?, bot_id?, user_id?, base_url?, error? }
        status: "waiting" | "scanned" | "confirmed" | "expired" | "error"
    """
    if not qrcode_id:
        return {"status": "error", "error": "qrcode_id is required"}

    try:
        url = f"{DEFAULT_BASE_URL}/ilink/bot/get_qrcode_status?qrcode={qrcode_id}"
        logger.debug(f"[wechat-login] 轮询状态: {url[:80]}...")

        async with httpx.AsyncClient(timeout=40) as client:
            response = await client.get(url, headers=LOGIN_HEADERS)
            response.raise_for_status()
            data = response.json()

        logger.debug(f"[wechat-login] 状态响应: {data}")

        status = data.get("status", "wait")

        if status == "wait":
            return {"status": "waiting"}
        elif status == "scaned":
            return {"status": "scanned"}
        elif status == "confirmed":
            if not data.get("bot_token") or not data.get("ilink_bot_id"):
                return {"status": "error", "error": "登录成功但服务器未返回凭证"}
            return {
                "status": "confirmed",
                "bot_token": data.get("bot_token"),
                "bot_id": data.get("ilink_bot_id"),
                "user_id": data.get("ilink_user_id"),
                "base_url": data.get("baseurl"),
            }
        elif status == "expired":
            return {"status": "expired"}
        else:
            return {"status": status or "waiting"}
    except httpx.TimeoutException:
        return {"status": "waiting"}
    except Exception as err:
        logger.error(f"[wechat-login] 轮询状态失败: {err}")
        return {"status": "error", "error": str(err)}


# ── WechatAdapter 主类 ──

class WechatAdapter:
    """
    微信 iLink 适配器

    基于腾讯 iLink 协议实现长轮询消息收发。
    参考 openhanako 的 wechat-adapter.js。
    """

    def __init__(
        self,
        bot_token: str,
        agent_id: Optional[str] = None,
        data_dir: Optional[Path] = None,
        on_message: Optional[Callable[[InboundMessage], None]] = None,
        on_status: Optional[Callable[[str, Optional[str]], None]] = None,
    ):
        self.bot_token = bot_token
        self.agent_id = agent_id
        self.data_dir = data_dir
        self.on_message = on_message
        self.on_status = on_status

        self.base_url = DEFAULT_BASE_URL
        self._generation = 0
        self._context_cache: dict[str, dict] = {}  # chat_id -> {token, ts}
        self._last_status: Optional[str] = None
        self._last_error: Optional[str] = None
        self._running = False
        self._poll_task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None  # 复用 HTTP 客户端
        
        # 消息去重（防止重复处理同一条消息）
        self._processed_msg_ids: dict[str, float] = {}  # msg_id -> timestamp
        self._processed_msg_cleanup: float = 0
        self._MSG_DEDUP_WINDOW: float = 30.0  # 30秒内的消息不重复处理
        self._msg_processed_count: int = 0  # 消息处理计数
        self._msg_skipped_count: int = 0  # 消息跳过计数

        # 加载 cursor
        self._get_updates_buf = ""
        if data_dir:
            self._sync_buf_path = self._resolve_sync_buf_path()
            self._load_sync_buf()
        else:
            self._sync_buf_path = None

    def _resolve_sync_buf_path(self) -> Path:
        token_hash = hashlib.sha256(self.bot_token.encode()).hexdigest()[:8]
        sync_dir = self.data_dir / "bridge" / "wechat"
        sync_dir.mkdir(parents=True, exist_ok=True)
        return sync_dir / f"sync-{token_hash}.json"

    def _load_sync_buf(self):
        if self._sync_buf_path and self._sync_buf_path.exists():
            try:
                data = json.loads(self._sync_buf_path.read_text("utf-8"))
                self._get_updates_buf = data.get("get_updates_buf", "")
            except Exception:
                pass

    def _save_sync_buf(self):
        if self._sync_buf_path:
            try:
                self._sync_buf_path.write_text(
                    json.dumps({"get_updates_buf": self._get_updates_buf}),
                    "utf-8",
                )
            except Exception:
                pass

    # ── context_token 管理 ──

    def _set_context_token(self, chat_id: str, token: str):
        self._context_cache[chat_id] = {"token": token, "ts": time.time() * 1000}

    def _get_context_token(self, chat_id: str) -> Optional[str]:
        entry = self._context_cache.get(chat_id)
        if not entry:
            return None
        if (time.time() * 1000 - entry["ts"]) > CONTEXT_TOKEN_TTL_MS:
            del self._context_cache[chat_id]
            return None
        return entry["token"]

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

    # ── HTTP API ──

    def _get_client(self) -> httpx.AsyncClient:
        """获取或创建默认 HTTP 客户端（复用连接）"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=15,
                limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
            )
        return self._client

    async def _api_post(
        self,
        endpoint: str,
        body: dict,
        timeout_ms: int = 15_000,
    ) -> dict:
        url = endpoint if endpoint.startswith("http") else f"{self.base_url}/{endpoint.lstrip('/')}"
        # 长轮询使用独立客户端（需要更长超时）
        use_default = timeout_ms <= 15_000
        client = self._get_client() if use_default else httpx.AsyncClient(timeout=timeout_ms / 1000)
        try:
            response = await client.post(
                url,
                headers=build_headers(self.bot_token),
                json=body,
            )
            if response.status_code != 200:
                error_body = response.text[:500]
                logger.error(f"[wechat] HTTP {response.status_code} on {endpoint}: {error_body}")
                response.raise_for_status()
            data = response.json()
            if data.get("ret") is not None and data["ret"] != 0:
                raise Exception(
                    f"{endpoint} ret={data['ret']} "
                    f"errcode={data.get('errcode', '')} "
                    f"errmsg={data.get('errmsg', '')}"
                )
            return data
        except httpx.TimeoutException:
            raise
        except httpx.ConnectError as err:
            logger.error(f"[wechat] connect error on {endpoint}: {err}")
            raise
        finally:
            # 关闭临时客户端
            if not use_default:
                try:
                    await client.aclose()
                except Exception:
                    pass

    # ── 发送消息 ──

    async def send_text(self, chat_id: str, text: str, context_token: str):
        if not context_token:
            raise Exception("微信: 需要对方最近发过消息才能回复")
        await self._api_post("ilink/bot/sendmessage", {
            "msg": {
                "from_user_id": "",
                "to_user_id": chat_id,
                "client_id": str(uuid.uuid4()),
                "message_type": MessageType.BOT,
                "message_state": MessageState.FINISH,
                "item_list": [{"type": MessageItemType.TEXT, "text_item": {"text": text}}] if text else None,
                "context_token": context_token,
            },
            "base_info": {"channel_version": "1.0.0"},
        })

    async def send_reply(self, chat_id: str, text: str):
        """发送回复（自动分段）"""
        ctx = self._get_context_token(chat_id)
        if not ctx:
            logger.warning(f"[wechat] send_reply 失败: chat_id={chat_id} 没有 context_token")
            raise Exception("微信: 需要对方最近发过消息才能回复")
        logger.info(f"[wechat] send_reply chat_id={chat_id} text_len={len(text)}")
        for i in range(0, len(text), MSG_CHUNK_LIMIT):
            await self.send_text(chat_id, text[i:i + MSG_CHUNK_LIMIT], ctx)

    # ── CDN 媒体上传 ──

    async def upload_media(self, buffer: bytes, to_user_id: str, media_type: int) -> MediaUploadResult:
        rawsize = len(buffer)
        rawfilemd5 = hashlib.md5(buffer).hexdigest()
        filesize = aes_ecb_padded_size(rawsize)
        filekey = hashlib.md5(os.urandom(16)).hexdigest()
        aeskey = os.urandom(16)

        upload_resp = await self._api_post("ilink/bot/getuploadurl", {
            "filekey": filekey,
            "media_type": media_type,
            "to_user_id": to_user_id,
            "rawsize": rawsize,
            "rawfilemd5": rawfilemd5,
            "filesize": filesize,
            "no_need_thumb": True,
            "aeskey": aeskey.hex(),
            "base_info": {"channel_version": "1.0.0"},
        })

        if not upload_resp.get("upload_param"):
            raise Exception("getUploadUrl 未返回 upload_param")

        if not HAS_CRYPTO:
            raise Exception("cryptography library required for media upload")

        ciphertext = encrypt_aes_ecb(buffer, aeskey)
        cdn_url = f"{CDN_BASE_URL}/upload?encrypted_query_param={upload_resp['upload_param']}&filekey={filekey}"

        async with httpx.AsyncClient(timeout=30) as client:
            cdn_res = await client.post(
                cdn_url,
                headers={"Content-Type": "application/octet-stream"},
                content=ciphertext,
            )
            cdn_res.raise_for_status()

        download_param = cdn_res.headers.get("x-encrypted-param")
        if not download_param:
            raise Exception("CDN 未返回 x-encrypted-param")

        return MediaUploadResult(
            filekey=filekey,
            download_param=download_param,
            aeskey=aeskey.hex(),
            file_size=rawsize,
            file_size_ciphertext=filesize,
        )

    async def send_image_message(self, chat_id: str, uploaded: MediaUploadResult, context_token: str, caption: str = ""):
        items = []
        if caption:
            items.append({"type": MessageItemType.TEXT, "text_item": {"text": caption}})
        items.append({
            "type": MessageItemType.IMAGE,
            "image_item": {
                "media": {
                    "encrypt_query_param": uploaded.download_param,
                    "aes_key": base64.b64encode(bytes.fromhex(uploaded.aeskey)).decode(),
                    "encrypt_type": 1,
                },
                "mid_size": uploaded.file_size_ciphertext,
            },
        })
        for item in items:
            await self._api_post("ilink/bot/sendmessage", {
                "msg": {
                    "from_user_id": "",
                    "to_user_id": chat_id,
                    "client_id": str(uuid.uuid4()),
                    "message_type": MessageType.BOT,
                    "message_state": MessageState.FINISH,
                    "item_list": [item],
                    "context_token": context_token,
                },
                "base_info": {"channel_version": "1.0.0"},
            })

    async def send_file_message(self, chat_id: str, uploaded: MediaUploadResult, context_token: str, filename: str):
        await self._api_post("ilink/bot/sendmessage", {
            "msg": {
                "from_user_id": "",
                "to_user_id": chat_id,
                "client_id": str(uuid.uuid4()),
                "message_type": MessageType.BOT,
                "message_state": MessageState.FINISH,
                "item_list": [{
                    "type": MessageItemType.FILE,
                    "file_item": {
                        "media": {
                            "encrypt_query_param": uploaded.download_param,
                            "aes_key": base64.b64encode(bytes.fromhex(uploaded.aeskey)).decode(),
                            "encrypt_type": 1,
                        },
                        "file_name": filename,
                        "len": str(uploaded.file_size),
                    },
                }],
                "context_token": context_token,
            },
            "base_info": {"channel_version": "1.0.0"},
        })

    # ── CDN 下载 ──

    async def download_encrypted_media(self, platform_ref: str) -> bytes:
        ref = json.loads(platform_ref)
        cdn_url = f"{CDN_BASE_URL}/download?encrypted_query_param={ref['encrypt_query_param']}"
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.get(cdn_url)
            res.raise_for_status()
            encrypted = res.content
        if not ref.get("aes_key") or not HAS_CRYPTO:
            return encrypted
        key = parse_aes_key(ref["aes_key"])
        return decrypt_aes_ecb(encrypted, key)

    # ── 入站消息处理 ──

    def _handle_inbound(self, msg: dict):
        from_user_id = msg.get("from_user_id", "")
        if not from_user_id or from_user_id.endswith("@im.bot"):
            return
            
        now = time.time()
        
        # 生成消息唯一ID并去重检查
        # 使用更可靠的去重策略：内容哈希 + 时间窗口
        msg_text = extract_text(msg.get("item_list", []))
        msg_id_candidate = f"{from_user_id}:{msg_text}"
        msg_id = hashlib.md5(msg_id_candidate.encode()).hexdigest()[:16]
        
        # 定期清理旧的处理记录（使用滑动窗口）
        if now - self._processed_msg_cleanup > 60.0:
            # 清理超过窗口期的记录
            expired_keys = [
                k for k, ts in self._processed_msg_ids.items()
                if now - ts > self._MSG_DEDUP_WINDOW
            ]
            for k in expired_keys:
                del self._processed_msg_ids[k]
            self._processed_msg_cleanup = now
            
        # 检查是否重复
        if msg_id in self._processed_msg_ids:
            last_time = self._processed_msg_ids[msg_id]
            elapsed = now - last_time
            self._msg_skipped_count += 1
            logger.info(f"[wechat] 消息重复跳过: from={from_user_id}, elapsed={elapsed:.2f}s, skipped_total={self._msg_skipped_count}")
            return
            
        self._processed_msg_ids[msg_id] = now
        self._msg_processed_count += 1
        logger.info(f"[wechat] 消息处理: from={from_user_id}, processed_total={self._msg_processed_count}, text={msg_text[:50] if msg_text else '(empty)'}...")

        if msg.get("context_token"):
            self._set_context_token(from_user_id, msg["context_token"])
            logger.debug(f"[wechat] 设置 context_token for {from_user_id}")

        text = msg_text
        attachments = []

        for item in msg.get("item_list", []):
            if item.get("type") == MessageItemType.IMAGE:
                media = item.get("image_item", {}).get("media", {})
                if media.get("encrypt_query_param"):
                    aes_key = item["image_item"].get("aeskey")
                    if aes_key:
                        aes_key = base64.b64encode(bytes.fromhex(aes_key)).decode()
                    else:
                        aes_key = media.get("aes_key")
                    attachments.append({
                        "type": "image",
                        "platformRef": json.dumps({
                            "encrypt_query_param": media["encrypt_query_param"],
                            "aes_key": aes_key,
                        }),
                        "mimeType": "image/jpeg",
                    })
            elif item.get("type") == MessageItemType.FILE:
                media = item.get("file_item", {}).get("media", {})
                if media.get("encrypt_query_param"):
                    attachments.append({
                        "type": "file",
                        "platformRef": json.dumps({
                            "encrypt_query_param": media["encrypt_query_param"],
                            "aes_key": media.get("aes_key"),
                        }),
                        "filename": item["file_item"].get("file_name"),
                        "mimeType": "application/octet-stream",
                    })
            elif item.get("type") == MessageItemType.VIDEO:
                media = item.get("video_item", {}).get("media", {})
                if media.get("encrypt_query_param"):
                    attachments.append({
                        "type": "video",
                        "platformRef": json.dumps({
                            "encrypt_query_param": media["encrypt_query_param"],
                            "aes_key": media.get("aes_key"),
                        }),
                        "mimeType": "video/mp4",
                    })

        # 引用消息里的媒体
        if not attachments:
            for item in msg.get("item_list", []):
                if item.get("type") == MessageItemType.TEXT and item.get("ref_msg", {}).get("message_item"):
                    ref = item["ref_msg"]["message_item"]
                    if ref.get("type") == MessageItemType.IMAGE:
                        media = ref.get("image_item", {}).get("media", {})
                        if media.get("encrypt_query_param"):
                            aes_key = ref["image_item"].get("aeskey")
                            if aes_key:
                                aes_key = base64.b64encode(bytes.fromhex(aes_key)).decode()
                            else:
                                aes_key = media.get("aes_key")
                            attachments.append({
                                "type": "image",
                                "platformRef": json.dumps({
                                    "encrypt_query_param": media["encrypt_query_param"],
                                    "aes_key": aes_key,
                                }),
                                "mimeType": "image/jpeg",
                            })

        if not text and not attachments:
            return

        inbound = InboundMessage(
            chat_id=from_user_id,
            user_id=from_user_id,
            session_key=f"wx_dm_{from_user_id}@{self.agent_id or 'default'}",
            text=text,
            sender_name=from_user_id.split("@")[0] or "微信用户",
            is_group=False,
            attachments=attachments if attachments else [],
            agent_id=self.agent_id,
        )

        if self.on_message:
            self.on_message(inbound)

    # ── 长轮询主循环 ──

    async def _poll_loop(self):
        my_gen = self._generation
        consecutive_failures = 0

        while my_gen == self._generation:
            try:
                resp = await self._api_post(
                    "ilink/bot/getupdates",
                    {
                        "get_updates_buf": self._get_updates_buf,
                        "base_info": {"channel_version": "1.0.0"},
                    },
                    timeout_ms=LONG_POLL_TIMEOUT_MS,
                )

                consecutive_failures = 0
                self._report_status("connected")

                if resp.get("get_updates_buf"):
                    self._get_updates_buf = resp["get_updates_buf"]
                    self._save_sync_buf()

                for msg in resp.get("msgs", []):
                    try:
                        self._handle_inbound(msg)
                    except Exception as err:
                        logger.error(f"[wechat] handleInbound error: {err}")

            except asyncio.CancelledError:
                return
            except Exception as err:
                if my_gen != self._generation:
                    return
                if is_session_expired_error(err):
                    logger.info("[wechat] session expired (errcode -14), 停止轮询")
                    self._report_status("error", "session expired")
                    return
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    self._report_status("error", str(err))
                delay = BACKOFF_DELAYS[min(consecutive_failures - 1, len(BACKOFF_DELAYS) - 1)]
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    return

    # ── 生命周期 ──

    async def start(self):
        """启动长轮询"""
        if self._running:
            return
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("[wechat] adapter started")

    async def stop(self):
        """停止轮询"""
        self._generation += 1
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        # 关闭 HTTP 客户端
        if self._client and not self._client.is_closed:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None
        self._report_status("disconnected")
        logger.info("[wechat] adapter stopped")

    async def get_me(self) -> dict:
        """验证 token"""
        try:
            logger.info(f"[wechat] verifying token with getconfig...")
            resp = await self._api_post(
                "ilink/bot/getconfig",
                {"base_info": {"channel_version": "1.0.0"}},
                timeout_ms=10_000,
            )
            logger.info(f"[wechat] getconfig response: ret={resp.get('ret')} keys={list(resp.keys())}")
            if resp.get("ret") and resp["ret"] != 0:
                raise Exception(resp.get("errmsg") or f"errcode {resp['ret']}")
            return {"ok": True, "platform": "wechat"}
        except Exception as err:
            logger.error(f"[wechat] token verification failed: {err}")
            raise Exception(f"微信 token 验证失败: {err}")

    @property
    def capabilities(self) -> dict:
        return {"proactive": False}

    def can_reply(self, chat_id: str) -> bool:
        return self._get_context_token(chat_id) is not None
