"""
hermes_agent_server.py — Hermes Agent MCP Server

包装 Hermes 的 HTTP API 为标准 MCP Server。
Hermes 擅长：复杂推理、项目规划、架构设计、文档生成、代码修复。

Usage:
    python hermes_agent_server.py --http --port 5101
"""

import argparse
import asyncio
import json
import logging
import os
import sys

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
SERVER_NAME = "hermes-agent"

HERMES_URL_ENV = "HERMES_URL"
DEFAULT_HERMES_URL = "http://127.0.0.1:8102/run-task"


def build_server(hermes_url: str) -> Server:
    server = Server(SERVER_NAME)

    @server.list_tools()
    async def list_tools():
        return [
            {
                "name": "hermes_reasoning",
                "description": "Hermes 复杂推理与规划（适合项目架构、路线图、多步推理）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "推理/规划任务描述"},
                        "context": {"type": "string", "description": "相关背景上下文", "default": ""},
                        "mode": {"type": "string", "description": "模式：reasoning/planning/documentation", "default": "reasoning"},
                    },
                    "required": ["task"],
                },
            },
            {
                "name": "hermes_code_repair",
                "description": "Hermes 代码修复与调试（分析问题、根因定位、生成修复方案）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "有问题的代码"},
                        "error": {"type": "string", "description": "错误信息或报错描述", "default": ""},
                        "language": {"type": "string", "description": "编程语言", "default": "python"},
                    },
                    "required": ["code"],
                },
            },
            {
                "name": "hermes_documentation",
                "description": "Hermes 文档生成（技术文档、README、API 文档）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "description": "文档主题"},
                        "style": {"type": "string", "description": "文档风格：technical/USER/README/api", "default": "technical"},
                        "context": {"type": "string", "description": "相关上下文", "default": ""},
                    },
                    "required": ["topic"],
                },
            },
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[dict]:
        logger.info(f"[Hermes] Tool call: {name}")
        if name == "hermes_reasoning":
            return await _call_hermes_reasoning(hermes_url, arguments)
        elif name == "hermes_code_repair":
            return await _call_hermes_code_repair(hermes_url, arguments)
        elif name == "hermes_documentation":
            return await _call_hermes_documentation(hermes_url, arguments)
        return [{"type": "text", "text": f"Unknown tool: {name}"}]

    @server.add_resource("config://capabilities")
    async def get_capabilities():
        return json.dumps({
            "name": SERVER_NAME,
            "capabilities": ["reasoning", "planning", "documentation", "code_repair"],
            "hermes_url": hermes_url,
            "version": "1.0.0",
        })

    return server


async def _call_hermes_reasoning(url: str, args: dict) -> list[dict]:
    payload = {
        "task": args.get("task", ""),
        "context": args.get("context", ""),
        "mode": args.get("mode", "reasoning"),
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, timeout=120.0)
            if resp.status_code == 200:
                data = resp.json()
                text = data.get("result", "") or data.get("output", "") or str(data)
                return [{"type": "text", "text": text}]
            return [{"type": "text", "text": f"[Hermes] HTTP {resp.status_code}: {resp.text[:500]}"}]
    except Exception as e:
        return [{"type": "text", "text": f"[Hermes] Error: {str(e)}"}]

async def _call_hermes_code_repair(url: str, args: dict) -> list[dict]:
    payload = {
        "task": f"[代码修复] {args.get('code', '')}",
        "error": args.get("error", ""),
        "language": args.get("language", "python"),
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, timeout=120.0)
            if resp.status_code == 200:
                data = resp.json()
                text = data.get("result", "") or data.get("output", "") or str(data)
                return [{"type": "text", "text": text}]
            return [{"type": "text", "text": f"[Hermes] HTTP {resp.status_code}: {resp.text[:500]}"}]
    except Exception as e:
        return [{"type": "text", "text": f"[Hermes] Error: {str(e)}"}]

async def _call_hermes_documentation(url: str, args: dict) -> list[dict]:
    payload = {
        "task": f"[文档生成] 主题：{args.get('topic', '')}",
        "style": args.get("style", "technical"),
        "context": args.get("context", ""),
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, timeout=120.0)
            if resp.status_code == 200:
                data = resp.json()
                text = data.get("result", "") or data.get("output", "") or str(data)
                return [{"type": "text", "text": text}]
            return [{"type": "text", "text": f"[Hermes] HTTP {resp.status_code}: {resp.text[:500]}"}]
    except Exception as e:
        return [{"type": "text", "text": f"[Hermes] Error: {str(e)}"}]


async def main(stdio: bool = True, http_port: int = 5101):
    if not HAS_MCP:
        logger.error("mcp SDK not installed.")
        return

    hermes_url = os.environ.get(HERMES_URL_ENV, DEFAULT_HERMES_URL)
    server = build_server(hermes_url)

    if stdio:
        logger.info(f"[{SERVER_NAME}] stdio mode, Hermes URL: {hermes_url}")
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
            logger.info(f"[{SERVER_NAME}] HTTP SSE on port {http_port}, Hermes → {hermes_url}")
            uvicorn.run(app, host="0.0.0.0", port=http_port)
        except ImportError:
            logger.error("HTTP SSE dependencies missing.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true")
    parser.add_argument("--port", type=int, default=5101)
    args = parser.parse_args()
    asyncio.run(main(stdio=not args.http, http_port=args.port))