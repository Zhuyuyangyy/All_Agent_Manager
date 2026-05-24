"""
iliya_agent_server.py — iliya Agent MCP Server

将 iliya 的核心能力包装为标准 MCP Server，对外暴露工具接口。
iliya 擅长：意图识别、任务调度、命令执行、文件操作、技能管理。

Usage:
    python iliya_agent_server.py --http --port 5100
"""

import argparse
import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

try:
    from mcp.server import Server, NotificationOptions
    from mcp.server.models import InitializationCapabilities
    import mcp.server.stdio
    HAS_MCP = True
except ImportError:
    HAS_MCP = False

from backend.command_safety import is_command_safe

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
SERVER_NAME = "iliya-agent"

ILIYA_WORKSPACE_ENV = "ILIYA_WORKSPACE"
DEFAULT_WORKSPACE = ""


def build_server(workspace: str, allow_shell: bool = False) -> Server:
    server = Server(SERVER_NAME)

    @server.list_tools()
    async def list_tools():
        tools = [
            {
                "name": "iliya_route",
                "description": "iliya 任务路由调度（意图识别 → 子Agent分发）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "任务描述"},
                        "target_agent": {"type": "string", "description": "目标Agent（openclaw/hermes/openhanako/auto）", "default": "auto"},
                        "context": {"type": "string", "description": "额外上下文", "default": ""},
                    },
                    "required": ["task"],
                },
            },
            {
                "name": "iliya_file_read",
                "description": "iliya 文件读取",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "文件路径"},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "iliya_file_write",
                "description": "iliya 文件写入",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "文件路径"},
                        "content": {"type": "string", "description": "文件内容"},
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "iliya_file_list",
                "description": "iliya 目录列表",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "目录路径", "default": "."},
                    },
                    "required": [],
                },
            },
            {
                "name": "iliya_skill_list",
                "description": "iliya 技能列表查询",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "filter": {"type": "string", "description": "过滤关键词", "default": ""},
                    },
                    "required": [],
                },
            },
            {
                "name": "iliya_plugin_list",
                "description": "iliya 插件列表查询",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        ]

        if allow_shell:
            tools.append({
                "name": "iliya_execute",
                "description": "iliya 命令执行（受安全策略约束，危险命令被拦截）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "要执行的命令"},
                        "cwd": {"type": "string", "description": "工作目录", "default": ""},
                        "timeout": {"type": "integer", "description": "超时秒数", "default": 60},
                    },
                    "required": ["command"],
                },
            })

        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[dict]:
        logger.info(f"[iliya] Tool call: {name}")
        if name == "iliya_route":
            return await _handle_route(arguments)
        elif name == "iliya_file_read":
            return await _handle_file_read(workspace, arguments)
        elif name == "iliya_file_write":
            return await _handle_file_write(workspace, arguments)
        elif name == "iliya_file_list":
            return await _handle_file_list(workspace, arguments)
        elif name == "iliya_skill_list":
            return await _handle_skill_list(arguments)
        elif name == "iliya_plugin_list":
            return await _handle_plugin_list()
        elif name == "iliya_execute":
            return await _handle_execute(arguments)
        return [{"type": "text", "text": f"Unknown tool: {name}"}]

    @server.add_resource("config://capabilities")
    async def get_capabilities():
        caps = [
            "intent_recognition", "task_decomposition", "agent_routing",
            "command_execution", "file_operation",
            "skill_management", "plugin_management",
            "mcp_tool_call", "minimax_tool_call", "intimacy_management",
        ]
        return json.dumps({
            "name": SERVER_NAME,
            "capabilities": caps,
            "workspace": workspace,
            "shell_enabled": allow_shell,
            "version": "1.0.0",
        })

    return server


async def _handle_route(args: dict) -> list[dict]:
    task_desc = args.get("task", "")
    target = args.get("target_agent", "auto")
    ctx = args.get("context", "")

    result = {
        "status": "routed",
        "task": task_desc,
        "target_agent": target,
        "context": ctx,
        "message": f"iliya 已接收任务，将路由到 {target}",
    }
    return [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]


async def _handle_file_read(workspace: str, args: dict) -> list[dict]:
    path = args.get("path", "")
    try:
        target = Path(path)
        if not target.is_absolute() and workspace:
            target = Path(workspace) / path
        if not target.exists():
            return [{"type": "text", "text": f"文件不存在: {target}"}]
        text = target.read_text(encoding="utf-8")
        return [{"type": "text", "text": text}]
    except Exception as e:
        return [{"type": "text", "text": f"读取失败: {e}"}]


async def _handle_file_write(workspace: str, args: dict) -> list[dict]:
    path = args.get("path", "")
    content = args.get("content", "")
    try:
        target = Path(path)
        if not target.is_absolute() and workspace:
            target = Path(workspace) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return [{"type": "text", "text": f"文件已写入: {target}"}]
    except Exception as e:
        return [{"type": "text", "text": f"写入失败: {e}"}]


async def _handle_file_list(workspace: str, args: dict) -> list[dict]:
    path = args.get("path", ".")
    try:
        target = Path(path)
        if not target.is_absolute() and workspace:
            target = Path(workspace) / path
        if not target.exists():
            return [{"type": "text", "text": f"目录不存在: {target}"}]
        entries = [f"{p.name}{'/' if p.is_dir() else ''}" for p in sorted(target.iterdir())]
        return [{"type": "text", "text": "\n".join(entries)}]
    except Exception as e:
        return [{"type": "text", "text": f"列目录失败: {e}"}]


async def _handle_skill_list(args: dict) -> list[dict]:
    return [{"type": "text", "text": "技能列表需通过 WeChatAgent 查询（MCP Server 独立运行时不可用）"}]


async def _handle_plugin_list() -> list[dict]:
    return [{"type": "text", "text": "插件列表需通过 WeChatAgent 查询（MCP Server 独立运行时不可用）"}]


async def _handle_execute(args: dict) -> list[dict]:
    command = args.get("command", "")
    cwd = args.get("cwd", "") or None
    timeout = args.get("timeout", 60)

    if not command:
        return [{"type": "text", "text": "命令为空"}]

    safe, reason = is_command_safe(command)
    if not safe:
        return [{"type": "text", "text": f"命令被安全策略拦截: {reason}"}]

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        return [{"type": "text", "text": output}]
    except subprocess.TimeoutExpired:
        return [{"type": "text", "text": f"命令执行超时 ({timeout}s)"}]
    except Exception as e:
        return [{"type": "text", "text": f"执行失败: {e}"}]


async def main(stdio: bool = True, http_port: int = 5100):
    if not HAS_MCP:
        logger.error("mcp SDK not installed.")
        return

    workspace = os.environ.get(ILIYA_WORKSPACE_ENV, DEFAULT_WORKSPACE)
    allow_shell = os.environ.get("ILIYA_ALLOW_SHELL", "").lower() in ("1", "true", "yes")
    server = build_server(workspace, allow_shell=allow_shell)

    if stdio:
        logger.info(f"[{SERVER_NAME}] stdio mode, workspace: {workspace}, shell: {allow_shell}")
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
            logger.info(f"[{SERVER_NAME}] HTTP SSE on port {http_port}, workspace: {workspace}")
            uvicorn.run(app, host="0.0.0.0", port=http_port)
        except ImportError:
            logger.error("HTTP SSE dependencies missing.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true")
    parser.add_argument("--port", type=int, default=5100)
    args = parser.parse_args()
    asyncio.run(main(stdio=not args.http, http_port=args.port))
