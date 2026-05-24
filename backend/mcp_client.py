"""
mcp_client.py — MCP 客户端模块

管理 MCP Server 连接，支持通过 stdio 协议与 MCP Server 通信。
借鉴 mmx-mcp-server 的 stdio 传输方式。

功能：
  - 注册/管理 MCP Server 配置
  - 启动 MCP Server 子进程
  - 列出可用工具
  - 调用工具
"""

import json
import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class McpServerConfig:
    """MCP Server 配置"""
    id: str = field(default_factory=lambda: f"mcp_{uuid.uuid4().hex[:8]}")
    name: str = ""
    command: str = "node"                    # 启动命令
    args: list[str] = field(default_factory=list)  # 命令参数
    env: dict[str, str] = field(default_factory=dict)  # 环境变量
    cwd: str = ""                            # 工作目录
    enabled: bool = True
    status: str = "stopped"                  # stopped | starting | running | error
    error: str = ""
    tools: list[dict] = field(default_factory=list)  # 缓存的工具列表
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    last_connected: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "command": self.command,
            "args": self.args,
            "env": {k: ("***" if "key" in k.lower() or "secret" in k.lower() else v)
                    for k, v in self.env.items()},
            "env_keys": list(self.env.keys()),
            "cwd": self.cwd,
            "enabled": self.enabled,
            "status": self.status,
            "error": self.error,
            "tool_count": len(self.tools),
            "tools": self.tools,
            "created_at": self.created_at,
            "last_connected": self.last_connected,
        }


class McpClient:
    """MCP 客户端 — 管理与 MCP Server 的 stdio 通信"""

    def __init__(self, storage_dir: str | Path = "storage"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.storage_dir / "mcp_servers.json"

        self._servers: dict[str, McpServerConfig] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._readers: dict[str, asyncio.StreamReader] = {}
        self._writers: dict[str, asyncio.StreamWriter] = {}
        self._request_id: dict[str, int] = {}

        self._load_config()

    # ── 持久化 ──

    def _load_config(self):
        if self.config_file.exists():
            try:
                data = json.loads(self.config_file.read_text(encoding="utf-8"))
                for s in data.get("servers", []):
                    config = McpServerConfig(**{k: v for k, v in s.items()
                                                if k in McpServerConfig.__dataclass_fields__})
                    self._servers[config.id] = config
            except Exception as e:
                logger.error(f"Failed to load MCP config: {e}")

    def _save_config(self):
        data = {
            "servers": [
                {k: v for k, v in s.to_dict().items()
                 if k not in ("tools",)}  # tools 不持久化
                for s in self._servers.values()
            ]
        }
        self.config_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    # ── 服务器管理 ──

    def list_servers(self) -> list[dict]:
        return [s.to_dict() for s in self._servers.values()]

    def get_server(self, server_id: str) -> Optional[dict]:
        server = self._servers.get(server_id)
        return server.to_dict() if server else None

    def add_server(self, name: str, command: str, args: list[str] = None,
                   env: dict[str, str] = None, cwd: str = "",
                   enabled: bool = True) -> dict:
        """添加 MCP Server"""
        server_id = f"mcp_{uuid.uuid4().hex[:8]}"
        config = McpServerConfig(
            id=server_id,
            name=name,
            command=command,
            args=args if args is not None else [],
            env=env if env is not None else {},
            cwd=cwd,
            enabled=enabled,
        )
        self._servers[server_id] = config
        self._save_config()
        return config.to_dict()

    def update_server(self, server_id: str, **kwargs) -> Optional[dict]:
        server = self._servers.get(server_id)
        if not server:
            return None
        for key, value in kwargs.items():
            if hasattr(server, key) and key != "id":
                setattr(server, key, value)
        self._save_config()
        return server.to_dict()

    def remove_server(self, server_id: str) -> bool:
        if server_id in self._servers:
            # 先停止进程
            asyncio.create_task(self.stop_server(server_id))
            del self._servers[server_id]
            self._save_config()
            return True
        return False

    # ── 进程管理 ──

    async def start_server(self, server_id: str) -> dict:
        """启动 MCP Server 子进程"""
        config = self._servers.get(server_id)
        if not config:
            return {"ok": False, "error": "Server not found"}

        if server_id in self._processes:
            return {"ok": True, "message": "Already running"}

        config.status = "starting"
        config.error = ""

        try:
            cmd = config.command
            cmd_args = config.args

            # 构建环境变量
            env = os.environ.copy()
            env.update(config.env)

            # 启动子进程
            process = await asyncio.create_subprocess_exec(
                cmd, *cmd_args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=config.cwd or None,
                env=env,
            )

            self._processes[server_id] = process
            self._request_id[server_id] = 0

            # 发送 initialize 请求
            init_result = await self._send_request(server_id, "initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "all-agent-manager",
                    "version": "1.0.0",
                },
            })

            if init_result and "result" in init_result:
                # 发送 initialized 通知
                await self._send_notification(server_id, "notifications/initialized", {})
                config.status = "running"
                config.last_connected = time.strftime("%Y-%m-%dT%H:%M:%S")
                self._save_config()
                return {"ok": True, "message": "Server started"}
            else:
                error_msg = init_result.get("error", {}).get("message", "Initialize failed") if init_result else "No response"
                config.status = "error"
                config.error = error_msg
                self._save_config()
                await self._kill_process(server_id)
                return {"ok": False, "error": error_msg}

        except FileNotFoundError:
            config.status = "error"
            config.error = f"Command not found: {config.command}"
            self._save_config()
            return {"ok": False, "error": config.error}
        except Exception as e:
            config.status = "error"
            config.error = str(e)
            self._save_config()
            await self._kill_process(server_id)
            return {"ok": False, "error": str(e)}

    async def stop_server(self, server_id: str) -> dict:
        """停止 MCP Server"""
        await self._kill_process(server_id)
        config = self._servers.get(server_id)
        if config:
            config.status = "stopped"
            config.tools = []
            self._save_config()
        return {"ok": True}

    async def _kill_process(self, server_id: str):
        process = self._processes.pop(server_id, None)
        if process:
            try:
                process.stdin.close()
            except Exception:
                pass
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
            except Exception:
                pass

    # ── JSON-RPC 通信 ──

    async def _send_request(self, server_id: str, method: str, params: dict,
                            timeout: float = 30.0) -> Optional[dict]:
        """发送 JSON-RPC 请求并等待响应"""
        process = self._processes.get(server_id)
        if not process or not process.stdin or not process.stdout:
            return None

        self._request_id[server_id] = self._request_id.get(server_id, 0) + 1
        req_id = self._request_id[server_id]

        message = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        try:
            data = json.dumps(message) + "\n"
            process.stdin.write(data.encode())
            await process.stdin.drain()

            # 等待响应
            response_line = await asyncio.wait_for(
                process.stdout.readline(),
                timeout=timeout
            )
            if response_line:
                return json.loads(response_line.decode())
        except asyncio.TimeoutError:
            logger.error(f"[MCP] Request timeout: {method}")
        except json.JSONDecodeError as e:
            logger.error(f"[MCP] JSON decode error: {e}")
        except Exception as e:
            logger.error(f"[MCP] Request error: {e}")

        return None

    async def _send_notification(self, server_id: str, method: str, params: dict):
        """发送 JSON-RPC 通知（无响应）"""
        process = self._processes.get(server_id)
        if not process or not process.stdin:
            return

        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        try:
            data = json.dumps(message) + "\n"
            process.stdin.write(data.encode())
            await process.stdin.drain()
        except Exception as e:
            logger.error(f"[MCP] Notification error: {e}")

    # ── 工具操作 ──

    async def list_tools(self, server_id: str) -> dict:
        """列出 MCP Server 的工具"""
        config = self._servers.get(server_id)
        if not config:
            return {"ok": False, "error": "Server not found"}

        # 如果没运行，先启动
        if config.status != "running":
            start_result = await self.start_server(server_id)
            if not start_result.get("ok"):
                return start_result

        result = await self._send_request(server_id, "tools/list", {})
        if result and "result" in result:
            tools = result["result"].get("tools", [])
            config.tools = tools
            self._save_config()
            return {"ok": True, "tools": tools}
        else:
            error_msg = result.get("error", {}).get("message", "Failed to list tools") if result else "No response"
            return {"ok": False, "error": error_msg}

    async def call_tool(self, server_id: str, tool_name: str,
                        arguments: dict = None) -> dict:
        """调用 MCP Server 的工具"""
        config = self._servers.get(server_id)
        if not config:
            return {"ok": False, "error": "Server not found"}

        # 如果没运行，先启动
        if config.status != "running":
            start_result = await self.start_server(server_id)
            if not start_result.get("ok"):
                return start_result

        result = await self._send_request(server_id, "tools/call", {
            "name": tool_name,
            "arguments": arguments or {},
        }, timeout=120.0)  # 工具调用可能需要更长时间

        if result and "result" in result:
            content = result["result"].get("content", [])
            # 提取文本内容
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    text_parts.append(block)
            return {"ok": True, "content": "\n".join(text_parts), "raw": content}
        else:
            error_msg = result.get("error", {}).get("message", "Tool call failed") if result else "No response"
            return {"ok": False, "error": error_msg}

    # ── 清理 ──

    async def shutdown(self):
        """关闭所有 MCP Server"""
        for server_id in list(self._processes.keys()):
            await self._kill_process(server_id)


# ── 预设 MCP Servers ──

def _resolve_mmx_mcp_path() -> str:
    """解析 mmx-mcp-server/dist/index.js 的路径"""
    # 优先使用环境变量
    env_path = os.getenv("MMX_MCP_SERVER_PATH")
    if env_path and Path(env_path).exists():
        return env_path

    # 常见安装位置
    candidates = [
        Path.home() / "mmx-mcp-server" / "dist" / "index.js",
        Path.home() / ".npm" / "_npx" / "mmx-mcp-server" / "dist" / "index.js",
        Path("D:/GITHUB/mmx-mcp-server/dist/index.js"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)

    # 回退：假设全局 npm 安装
    return "mmx-mcp-server"


def _resolve_mmx_env() -> dict[str, str]:
    """从环境变量收集 MiniMax API Key"""
    env = {}
    for key in ("MINIMAX_API_KEY", "MCP_MINIMAX_API_KEY"):
        val = os.getenv(key)
        if val:
            env[key] = val
            break
    return env


PRESET_MCP_SERVERS = {
    "mmx": {
        "name": "MiniMax 全模态",
        "command": "node",
        "args": [_resolve_mmx_mcp_path()],
        "env_keys": ["MINIMAX_API_KEY"],
        "env_defaults": _resolve_mmx_env(),
        "description": "MiniMax 全模态 MCP：搜索、图像理解、图像生成、语音合成、视频生成、音乐生成",
    },
    "filesystem": {
        "name": "Filesystem",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        "env_keys": [],
        "description": "文件系统 MCP：读写文件、目录浏览、文件搜索",
    },
    "fetch": {
        "name": "Fetch",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-fetch"],
        "env_keys": [],
        "description": "网页抓取 MCP：获取网页内容、API 调用",
    },
    "memory": {
        "name": "Memory",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
        "env_keys": [],
        "description": "记忆 MCP：持久化知识图谱，记住上下文信息",
    },
    "brave-search": {
        "name": "Brave Search",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-brave-search"],
        "env_keys": ["BRAVE_API_KEY"],
        "description": "Brave 搜索 MCP：网页搜索、新闻搜索",
    },
    "sequential-thinking": {
        "name": "Sequential Thinking",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
        "env_keys": [],
        "description": "顺序思维 MCP：结构化推理、复杂问题分解",
    },
}


def build_mcp_client_from_env() -> McpClient:
    storage_dir = os.getenv("MCP_STORAGE_DIR", "storage")
    return McpClient(storage_dir=storage_dir)
