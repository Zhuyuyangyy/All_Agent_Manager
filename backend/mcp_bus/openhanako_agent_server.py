"""
openhanako_agent_server.py — OpenHanako Agent MCP Server

包装 OpenHanako 的 HTTP API 为标准 MCP Server。
OpenHanako 擅长：聊天陪伴、轻量规划、人格化交互、情感支持。

Usage:
    python openhanako_agent_server.py --http --port 5103
"""

import argparse
import asyncio
import json
import logging
import os

try:
    from mcp.server import Server, NotificationOptions
    from mcp.server.models import InitializationCapabilities
    import mcp.server.stdio
    HAS_MCP = True
except ImportError:
    HAS_MCP = False

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
SERVER_NAME = "openhanako-agent"

OPENHANAKO_HOST_ENV = "OPENHANAKO_HOST"
OPENHANAKO_PORT_ENV = "OPENHANAKO_PORT"
DEFAULT_OPENHANAKO_HOST = "localhost"
DEFAULT_OPENHANAKO_PORT = 12306


def _build_url() -> str:
    host = os.environ.get(OPENHANAKO_HOST_ENV, DEFAULT_OPENHANAKO_HOST)
    port = os.environ.get(OPENHANAKO_PORT_ENV, DEFAULT_OPENHANAKO_PORT)
    return f"http://{host}:{port}/api/chat"


def build_server(hanako_url: str) -> Server:
    server = Server(SERVER_NAME)

    @server.list_tools()
    async def list_tools():
        return [
            {
                "name": "openhanako_chat",
                "description": "OpenHanako 聊天交互（日常对话、答疑、情感支持）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "用户消息"},
                        "persona": {"type": "string", "description": "人格设定", "default": ""},
                        "context": {"type": "string", "description": "对话上下文", "default": ""},
                    },
                    "required": ["message"],
                },
            },
            {
                "name": "openhanako_light_planning",
                "description": "OpenHanako 轻量规划（日程、建议、简单决策）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "规划任务描述"},
                        "constraints": {"type": "string", "description": "约束条件", "default": ""},
                    },
                    "required": ["task"],
                },
            },
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[dict]:
        logger.info(f"[OpenHanako] Tool call: {name}")
        if name == "openhanako_chat":
            return await _call_hanako_chat(hanako_url, arguments)
        elif name == "openhanako_light_planning":
            return await _call_hanako_planning(hanako_url, arguments)
        return [{"type": "text", "text": f"Unknown tool: {name}"}]

    @server.add_resource("config://capabilities")
    async def get_capabilities():
        return json.dumps({
            "name": SERVER_NAME,
            "capabilities": ["chat", "companion", "light_planning", "emotion"],
            "openhanako_url": hanako_url,
            "version": "1.0.0",
        })

    return server


async def _call_hanako_chat(url: str, args: dict) -> list[dict]:
    payload = {
        "message": args.get("message", ""),
        "persona": args.get("persona", ""),
        "context": args.get("context", ""),
    }
    payload = {k: v for k, v in payload.items() if v}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, timeout=60.0)
            if resp.status_code == 200:
                data = resp.json()
                text = data.get("reply", "") or data.get("response", "") or data.get("result", "") or str(data)
                return [{"type": "text", "text": text}]
            return [{"type": "text", "text": f"[OpenHanako] HTTP {resp.status_code}: {resp.text[:300]}"}]
    except Exception as e:
        return [{"type": "text", "text": f"[OpenHanako] Error: {str(e)}"}]


async def _call_hanako_planning(url: str, args: dict) -> list[dict]:
    payload = {
        "message": f"[规划] {args.get('task', '')}",
        "constraints": args.get("constraints", ""),
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, timeout=60.0)
            if resp.status_code == 200:
                data = resp.json()
                text = data.get("reply", "") or data.get("response", "") or str(data)
                return [{"type": "text", "text": text}]
            return [{"type": "text", "text": f"[OpenHanako] HTTP {resp.status_code}: {resp.text[:300]}"}]
    except Exception as e:
        return [{"type": "text", "text": f"[OpenHanako] Error: {str(e)}"}]


async def main(stdio: bool = True, http_port: int = 5103):
    if not HAS_MCP:
        logger.error("mcp SDK not installed.")
        return

    hanako_url = _build_url()
    server = build_server(hanako_url)

    if stdio:
        logger.info(f"[{SERVER_NAME}] stdio mode, OpenHanako URL: {hanako_url}")
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, InitializationCapabilities())
    else:
        try:
            from mcp.server.sse import SSEBasedServerTransport
            from starlette.applications import Starlette
            from starlette.routing import Route
            import uvicorn
            transport = SSEBasedServerTransport("/mcp")
            app = Starlette(routes=[Route("/mcp", transport.handle_request)])
            logger.info(f"[{SERVER_NAME}] HTTP SSE on port {http_port}, OpenHanako → {hanako_url}")
            uvicorn.run(app, host="0.0.0.0", port=http_port)
        except ImportError:
            logger.error("HTTP SSE dependencies missing.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true")
    parser.add_argument("--port", type=int, default=5103)
    args = parser.parse_args()
    asyncio.run(main(stdio=not args.http, http_port=args.port))