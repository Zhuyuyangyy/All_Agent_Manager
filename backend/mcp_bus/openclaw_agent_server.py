"""
openclaw_agent_server.py — OpenClaw Agent MCP Server

包装 OpenClaw 的 HTTP API 为标准 MCP Server。
OpenClaw 擅长：代码修复、调试、工具调用、文件编辑、脚本执行。

Usage:
    python openclaw_agent_server.py --http --port 5102
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
SERVER_NAME = "openclaw-agent"

OPENCLAW_URL_ENV = "OPENCLAW_URL"
DEFAULT_OPENCLAW_URL = "http://127.0.0.1:18789/run-task"


def build_server(openclaw_url: str) -> Server:
    server = Server(SERVER_NAME)

    @server.list_tools()
    async def list_tools():
        return [
            {
                "name": "openclaw_coding",
                "description": "OpenClaw 代码修复与调试（适合报错修复、bug定位、代码优化）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "代码任务描述"},
                        "code": {"type": "string", "description": "相关代码片段", "default": ""},
                        "error": {"type": "string", "description": "错误或报错", "default": ""},
                        "context": {"type": "string", "description": "上下文", "default": ""},
                    },
                    "required": ["task"],
                },
            },
            {
                "name": "openclaw_script",
                "description": "OpenClaw 脚本执行（自动化脚本、批处理、工具链）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "script": {"type": "string", "description": "要执行的脚本或命令"},
                        "cwd": {"type": "string", "description": "工作目录", "default": ""},
                    },
                    "required": ["script"],
                },
            },
            {
                "name": "openclaw_file_edit",
                "description": "OpenClaw 文件编辑（创建/修改文件、代码重构）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "文件路径"},
                        "content": {"type": "string", "description": "文件内容"},
                        "operation": {"type": "string", "description": "操作：create/append/replace", "default": "create"},
                    },
                    "required": ["path", "content"],
                },
            },
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[dict]:
        logger.info(f"[OpenClaw] Tool call: {name}")
        if name == "openclaw_coding":
            return await _call_openclaw(openclaw_url, "coding", arguments)
        elif name == "openclaw_script":
            return await _call_openclaw(openclaw_url, "script", arguments)
        elif name == "openclaw_file_edit":
            return await _call_openclaw(openclaw_url, "file_edit", arguments)
        return [{"type": "text", "text": f"Unknown tool: {name}"}]

    @server.add_resource("config://capabilities")
    async def get_capabilities():
        return json.dumps({
            "name": SERVER_NAME,
            "capabilities": ["code_repair", "tool_call", "file_edit", "debugging", "script"],
            "openclaw_url": openclaw_url,
            "version": "1.0.0",
        })

    return server


async def _call_openclaw(url: str, task_type: str, args: dict) -> list[dict]:
    payload = {
        "task": args.get("task", "") or args.get("script", "") or args.get("path", ""),
        "task_type": task_type,
        "code": args.get("code", ""),
        "error": args.get("error", ""),
        "context": args.get("context", ""),
        "path": args.get("path", ""),
        "content": args.get("content", ""),
        "operation": args.get("operation", "create"),
        "cwd": args.get("cwd", ""),
    }
    # 移除空字段
    payload = {k: v for k, v in payload.items() if v}

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, timeout=120.0)
            if resp.status_code == 200:
                data = resp.json()
                text = data.get("result", "") or data.get("output", "") or str(data)
                return [{"type": "text", "text": text}]
            return [{"type": "text", "text": f"[OpenClaw] HTTP {resp.status_code}: {resp.text[:500]}"}]
    except Exception as e:
        return [{"type": "text", "text": f"[OpenClaw] Error: {str(e)}"}]


async def main(stdio: bool = True, http_port: int = 5102):
    if not HAS_MCP:
        logger.error("mcp SDK not installed.")
        return

    openclaw_url = os.environ.get(OPENCLAW_URL_ENV, DEFAULT_OPENCLAW_URL)
    server = build_server(openclaw_url)

    if stdio:
        logger.info(f"[{SERVER_NAME}] stdio mode, OpenClaw URL: {openclaw_url}")
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
            logger.info(f"[{SERVER_NAME}] HTTP SSE on port {http_port}, OpenClaw → {openclaw_url}")
            uvicorn.run(app, host="0.0.0.0", port=http_port)
        except ImportError:
            logger.error("HTTP SSE dependencies missing.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true")
    parser.add_argument("--port", type=int, default=5102)
    args = parser.parse_args()
    asyncio.run(main(stdio=not args.http, http_port=args.port))