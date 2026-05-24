"""
tool_agent_server.py — 工具调用 Agent MCP Server

提供常用工具：网页抓取、FFmpeg 媒体处理、文件操作等。
同样基于 mcp Python SDK。

Usage:
    python tool_agent_server.py --http --port 5002
"""

import argparse
import asyncio
import json
import logging
import subprocess
import sys

try:
    from mcp.server import Server, NotificationOptions
    from mcp.server.models import InitializationCapabilities
    import mcp.server.stdio
    HAS_MCP = True
except ImportError:
    HAS_MCP = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
SERVER_NAME = "tool-agent"


def build_server() -> Server:
    server = Server(SERVER_NAME)

    @server.list_tools()
    async def list_tools():
        return [
            {
                "name": "web_scrape",
                "description": "抓取网页文本内容",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "目标 URL"},
                        "max_chars": {"type": "integer", "description": "最大字符数", "default": 5000},
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "run_ffmpeg",
                "description": "执行 FFmpeg 音视频处理",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "args": {"type": "string", "description": "FFmpeg 参数（如 '-i input.mp4 output.mp3'）"},
                        "timeout": {"type": "integer", "description": "超时秒数", "default": 300},
                    },
                    "required": ["args"],
                },
            },
            {
                "name": "file_read",
                "description": "读取文件内容",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "文件路径"},
                        "max_lines": {"type": "integer", "description": "最大行数", "default": 200},
                    },
                    "required": ["path"],
                },
            },
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[dict]:
        logger.info(f"[ToolAgent] Tool call: {name}")

        if name == "web_scrape":
            return await _web_scrape(arguments.get("url", ""), arguments.get("max_chars", 5000))
        elif name == "run_ffmpeg":
            return await _run_ffmpeg(arguments.get("args", ""), arguments.get("timeout", 300))
        elif name == "file_read":
            return await _file_read(arguments.get("path", ""), arguments.get("max_lines", 200))
        return [{"type": "text", "text": f"Unknown tool: {name}"}]

    @server.add_resource("config://capabilities")
    async def get_capabilities():
        return json.dumps({
            "name": SERVER_NAME,
            "capabilities": ["web_scrape", "media_processing", "file_operations"],
            "version": "1.0.0",
        })

    return server


async def _web_scrape(url: str, max_chars: int = 5000) -> list[dict]:
    try:
        import urllib.request
        from urllib.error import URLError
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            content = r.read().decode("utf-8", errors="replace")[:max_chars]
        return [{"type": "text", "text": f"Fetched {len(content)} chars from {url}:\n{content}"}]
    except Exception as e:
        return [{"type": "text", "text": f"Error fetching {url}: {str(e)}"}]


async def _run_ffmpeg(args: str, timeout: int = 300) -> list[dict]:
    if not args:
        return [{"type": "text", "text": "Error: empty args"}]
    try:
        result = subprocess.run(
            ["ffmpeg", "-y"] + args.split(),
            capture_output=True, text=True, timeout=timeout,
        )
        output = result.stdout if result.returncode == 0 else f"Error: {result.stderr}"
    except subprocess.TimeoutExpired:
        output = f"Error: FFmpeg 超时（{timeout}秒）"
    except Exception as e:
        output = f"Error: {str(e)}"
    return [{"type": "text", "text": output}]


async def _file_read(path: str, max_lines: int = 200) -> list[dict]:
    if not path:
        return [{"type": "text", "text": "Error: empty path"}]
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = [f.readline() for _ in range(max_lines)]
            content = "".join(lines)
        return [{"type": "text", "text": f"File {path} (first {max_lines} lines):\n{content}"}]
    except Exception as e:
        return [{"type": "text", "text": f"Error reading {path}: {str(e)}"}]


async def main(stdio: bool = True, http_port: int = 5002):
    if not HAS_MCP:
        logger.error("mcp SDK not installed.")
        return

    server = build_server()
    if stdio:
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, InitializationCapabilities())
    else:
        from mcp.server.sse import SSEBasedServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Route
        import uvicorn
        transport = SSEBasedServerTransport("/mcp")
        app = Starlette(routes=[Route("/mcp", transport.handle_request)])
        uvicorn.run(app, host="0.0.0.0", port=http_port)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true")
    parser.add_argument("--port", type=int, default=5002)
    args = parser.parse_args()
    asyncio.run(main(stdio=not args.http, http_port=args.port))