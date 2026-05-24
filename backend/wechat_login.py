"""
wechat_login.py — 微信 iLink 扫码登录模块

独立于 adapter 生命周期，被 REST route 直接调用。
参考 openhanako 的 wechat-login.js（MIT 协议）。
"""

import base64
import io
import logging

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://ilinkai.weixin.qq.com"
BOT_TYPE = "3"


def _login_headers() -> dict:
    """构造 iLink 请求头（登录阶段无需 Authorization）"""
    return {
        "iLink-App-ClientVersion": "1",
    }


async def get_wechat_qrcode() -> dict:
    """
    获取微信扫码登录二维码

    Returns:
        dict: { ok, qrcode_url (base64 PNG), qrcode_id, error }
    """
    try:
        url = f"{BASE_URL}/ilink/bot/get_bot_qrcode?bot_type={BOT_TYPE}"
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=_login_headers())
            response.raise_for_status()
            data = response.json()

        if not data.get("qrcode"):
            return {"ok": False, "error": "服务器未返回二维码"}

        # qrcode_img_content 是要被编码成二维码的 URL 文本
        qr_text = data.get("qrcode_img_content") or data["qrcode"]

        # 用 qrcode 库转成 data URL（base64 PNG）
        try:
            import qrcode
            qr = qrcode.QRCode(version=1, box_size=10, border=2)
            qr.add_data(qr_text)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            qrcode_data_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        except ImportError:
            # 如果没有 qrcode 库，返回原始文本让前端处理
            qrcode_data_url = qr_text

        return {
            "ok": True,
            "qrcode_url": qrcode_data_url,
            "qrcode_id": data["qrcode"],
        }
    except Exception as err:
        return {"ok": False, "error": str(err)}


async def poll_wechat_qrcode_status(qrcode_id: str) -> dict:
    """
    轮询微信扫码状态

    iLink 服务器会 hold 连接最多 35 秒（长轮询）。

    Args:
        qrcode_id: 从 get_wechat_qrcode 获取的 qrcode 值

    Returns:
        dict: { status, bot_token, bot_id, user_id, base_url, error }
    """
    if not qrcode_id:
        return {"status": "error", "error": "qrcodeId is required"}

    try:
        url = f"{BASE_URL}/ilink/bot/get_qrcode_status?qrcode={qrcode_id}"
        async with httpx.AsyncClient(timeout=40) as client:
            response = await client.get(url, headers=_login_headers())
            response.raise_for_status()
            data = response.json()

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
                "bot_token": data["bot_token"],
                "bot_id": data["ilink_bot_id"],
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
        return {"status": "error", "error": str(err)}
