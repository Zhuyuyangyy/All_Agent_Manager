"""
openhanako_client.py — OpenHanako 本地客户端

通过 HTTP API 与本地运行的 OpenHanako 桌面应用通信。
OpenHanako 是一个 Electron 应用，内置 Hono HTTP 服务器，
通常运行在 localhost 的随机端口上（可通过 HANA_PORT 环境变量指定）。

通信方式：
1. 通过 HTTP POST 发送任务到 OpenHanako 的会话 API
2. 通过 WebSocket 监听流式响应
3. 支持多种会话模式（session key / 直接消息）

端口发现：
- 优先使用 OPENHANAKO_PORT 环境变量
- 其次读取 OpenHanako 的 server-info.json 文件
- 最后使用默认端口 12306
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

from backend.models import AgentChoice
from backend.workers import WorkerClient, WorkerResult

logger = logging.getLogger(__name__)

# ── OpenHanako 服务器配置 ──
DEFAULT_PORT = 12306
DEFAULT_HOST = "localhost"

# OpenHanako 可能的 home 目录位置
HANAKO_HOME_CANDIDATES = [
    Path.home() / ".openhanako",
    Path.home() / "AppData" / "Roaming" / "openhanako",
    Path.home() / "AppData" / "Local" / "openhanako",
]


def _discover_port_from_server_info() -> Optional[int]:
    """从 OpenHanako 的 server-info.json 文件发现端口"""
    for home_dir in HANAKO_HOME_CANDIDATES:
        info_file = home_dir / "server-info.json"
        if info_file.exists():
            try:
                data = json.loads(info_file.read_text("utf-8"))
                port = data.get("port")
                if port:
                    logger.info(f"[openhanako] Discovered port {port} from {info_file}")
                    return int(port)
            except Exception as err:
                logger.debug(f"Failed to read {info_file}: {err}")
    return None


@dataclass
class OpenHanakoConfig:
    """OpenHanako 连接配置"""
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    api_key: Optional[str] = None  # 可选的 API key

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @classmethod
    def from_env(cls) -> "OpenHanakoConfig":
        """从环境变量加载配置，支持自动发现端口"""
        # 1. 优先使用环境变量
        env_port = os.getenv("OPENHANAKO_PORT") or os.getenv("HANA_PORT")
        if env_port:
            port = int(env_port)
        else:
            # 2. 尝试从 server-info.json 发现
            discovered = _discover_port_from_server_info()
            port = discovered if discovered else DEFAULT_PORT

        return cls(
            host=os.getenv("OPENHANAKO_HOST", DEFAULT_HOST),
            port=port,
            api_key=os.getenv("OPENHANAKO_API_KEY"),
        )


class OpenHanakoClient:
    """
    OpenHanako 本地客户端

    与 OpenHanako 桌面应用通信，发送任务并获取结果。
    支持两种模式：
    1. HTTP API 模式（推荐）：通过 REST API 发送任务
    2. WebSocket 模式：通过 WebSocket 实时接收流式响应
    """

    def __init__(self, config: Optional[OpenHanakoConfig] = None):
        self.config = config or OpenHanakoConfig.from_env()

    def _build_headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    async def health_check(self) -> bool:
        """检查 OpenHanako 服务器是否运行"""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(
                    f"{self.config.base_url}/api/config",
                    headers=self._build_headers(),
                )
                return response.status_code == 200
        except Exception as err:
            logger.debug(f"OpenHanako health check failed: {err}")
            return False

    async def send_message(self, text: str, session_key: Optional[str] = None) -> dict:
        """
        发送消息到 OpenHanako

        通过 OpenHanako 的 Hub API 发送消息，触发 LLM 处理。

        Args:
            text: 消息文本
            session_key: 可选的 session key，用于指定会话

        Returns:
            dict: { ok, text, error }
        """
        try:
            # 构造消息 payload
            payload = {
                "text": text,
                "role": "owner",
            }
            if session_key:
                payload["sessionKey"] = session_key

            # 使用 OpenHanako 的 chat API
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{self.config.base_url}/api/chat/send",
                    headers=self._build_headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            if data.get("error"):
                return {"ok": False, "error": data["error"]}

            # 提取回复文本
            reply_text = data.get("text") or data.get("reply") or ""
            return {"ok": True, "text": reply_text}

        except httpx.TimeoutException:
            return {"ok": False, "error": "OpenHanako request timeout (120s)"}
        except httpx.ConnectError:
            return {"ok": False, "error": f"Cannot connect to OpenHanako at {self.config.base_url}"}
        except Exception as err:
            return {"ok": False, "error": str(err)}

    async def send_task_via_session(self, text: str, agent_id: Optional[str] = None) -> dict:
        """
        通过 session API 发送任务

        使用 OpenHanako 的 session 管理 API，更可靠地发送任务。

        Args:
            text: 任务文本
            agent_id: 可选的 agent ID

        Returns:
            dict: { ok, text, error }
        """
        try:
            payload = {
                "message": text,
            }
            if agent_id:
                payload["agentId"] = agent_id

            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{self.config.base_url}/api/sessions/submit",
                    headers=self._build_headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            if data.get("error"):
                return {"ok": False, "error": data["error"]}

            reply_text = data.get("text") or data.get("reply") or data.get("result") or ""
            return {"ok": True, "text": reply_text}

        except httpx.TimeoutException:
            return {"ok": False, "error": "OpenHanako request timeout (120s)"}
        except httpx.ConnectError:
            return {"ok": False, "error": f"Cannot connect to OpenHanako at {self.config.base_url}"}
        except Exception as err:
            return {"ok": False, "error": str(err)}

    async def list_sessions(self) -> list[dict]:
        """列出 OpenHanako 的所有会话"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.config.base_url}/api/sessions",
                    headers=self._build_headers(),
                )
                response.raise_for_status()
                data = response.json()
                return data.get("sessions", [])
        except Exception as err:
            logger.error(f"Failed to list OpenHanako sessions: {err}")
            return []

    async def get_session(self, session_path: str) -> Optional[dict]:
        """获取指定会话的信息"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.config.base_url}/api/sessions/{session_path}",
                    headers=self._build_headers(),
                )
                response.raise_for_status()
                return response.json()
        except Exception as err:
            logger.error(f"Failed to get OpenHanako session: {err}")
            return None


class OpenHanakoWorkerClient(WorkerClient):
    """
    OpenHanako Worker 客户端

    实现 WorkerClient 接口，将任务发送到本地 OpenHanako 桌面应用。
    """

    def __init__(self, config: Optional[OpenHanakoConfig] = None):
        self.client = OpenHanakoClient(config)

    async def run_task(self, agent: AgentChoice, task_id: str, goal: str) -> WorkerResult:
        """执行任务"""
        logger.info(f"[openhanako] Running task {task_id}: {goal[:80]}...")

        # 先检查 OpenHanako 是否运行
        if not await self.client.health_check():
            return WorkerResult(
                ok=False,
                error_message="OpenHanako is not running. Please start the OpenHanako desktop app.",
            )

        # 发送任务
        result = await self.client.send_message(goal)

        if result["ok"]:
            logger.info(f"[openhanako] Task {task_id} completed")
            return WorkerResult(ok=True, payload=result.get("text", ""))
        else:
            logger.error(f"[openhanako] Task {task_id} failed: {result['error']}")
            return WorkerResult(ok=False, error_message=result["error"])
