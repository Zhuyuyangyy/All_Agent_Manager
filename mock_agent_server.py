#!/usr/bin/env python3
"""
mock_agent_server.py — 模拟所有 4 个子 Agent 的 MCP HTTP 端点

启动后注册到 MCP Bus，并响应 /mcp 工具调用请求。
用于测试场景 1-4，无需真实的 Hermes/OpenClaw/OpenHanako。

Usage: python mock_agent_server.py
"""

import argparse
import asyncio
import json
import logging
import os
import random
import sys
import time
from copy import deepcopy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BUS_URL = "http://localhost:8000/bus"
AGENTS = [
    {
        "agent_id": "hermes-agent",
        "name": "hermes-agent",
        "description": "Hermes 复杂推理与规划 Agent",
        "capabilities": ["reasoning", "planning", "documentation", "code_repair", "analysis"],
        "mcp_endpoint": "http://localhost:5101/mcp",
    },
    {
        "agent_id": "openclaw-agent",
        "name": "openclaw-agent",
        "description": "OpenClaw 代码与工具 Agent",
        "capabilities": ["coding", "tool_use", "script", "file_edit", "code"],
        "mcp_endpoint": "http://localhost:5102/mcp",
    },
    {
        "agent_id": "openhanako-agent",
        "name": "openhanako-agent",
        "description": "OpenHanako 陪伴与轻量规划 Agent",
        "capabilities": ["chat", "companion", "planning_light"],
        "mcp_endpoint": "http://localhost:5103/mcp",
    },
    {
        "agent_id": "code-agent",
        "name": "code-agent",
        "description": "Code Agent 代码执行与测试",
        "capabilities": ["code", "execution", "testing"],
        "mcp_endpoint": "http://localhost:5001/mcp",
    },
]

# ── Mock responses ──────────────────────────────────────────

MOCK_RESPONSES = {
    "hermes_reasoning": lambda args: {
        "result": f"[Hermes 推理] 已完成复杂分析。\n\n关于任务：{args.get('task_description', 'N/A')[:200]}\n\n"
                  f"分析结论：\n1. 任务可分解为3个子步骤\n"
                  f"2. 需要协调代码、推理、文档三个能力域\n"
                  f"3. 建议采用链式执行策略\n\n"
                  f"(这是 Hermès Mock 响应)"
    },
    "hermes_documentation": lambda args: {
        "result": f"[Hermes 文档] 技术文档已生成。\n\n"
                  f"主题：{args.get('topic', args.get('task_description', 'N/A'))}\n\n"
                  f"## 概述\n本文档提供了详细的技术说明...（Mock文档内容）\n\n"
                  f"## 结论\n已生成完整技术文档。\n\n"
                  f"(这是 Hermes Mock 响应)"
    },
    "hermes_code_repair": lambda args: {
        "result": f"[Hermes 代码修复] 已分析代码问题。\n\n"
                  f"错误类型：潜在风险 / 需要重构\n"
                  f"建议方案：使用异步 + 错误处理机制\n"
                  f"(这是 Hermes Mock 响应)"
    },
    "openclaw_coding": lambda args: {
        "result": f"[OpenClaw 代码] 已生成代码。\n\n```python\n"
                  f"# {args.get('task_description', 'Task')[:100]}\n"
                  f"import asyncio\n\n"
                  f"async def main():\n"
                  f"    print('Hello from OpenClaw Mock!')\n\n"
                  f"if __name__ == '__main__':\n"
                  f"    asyncio.run(main())\n"
                  f"```\n"
                  f"(这是 OpenClaw Mock 响应)"
    },
    "openclaw_script": lambda args: {
        "result": f"[OpenClaw 脚本] 已生成脚本。\n\n"
                  f"脚本内容：批量下载 + 重试机制\n"
                  f"```bash\n"
                  f"#!/bin/bash\n"
                  f"for url in $(cat urls.txt); do\n"
                  f"    wget --tries=3 \"$url\"\n"
                  f"done\n"
                  f"```\n"
                  f"(这是 OpenClaw Mock 响应)"
    },
    "openclaw_file_edit": lambda args: {
        "result": f"[OpenClaw 文件编辑] 已完成文件修改。\n"
                  f"修改内容：增加错误处理和日志记录\n"
                  f"(这是 OpenClaw Mock 响应)"
    },
    "openclaw_tool_call": lambda args: {
        "result": f"[OpenClaw 工具调用] 已执行工具调用。\n"
                  f"任务：{args.get('task_description', 'N/A')[:100]}\n"
                  f"(这是 OpenClaw Mock 响应)"
    },
    "openhanako_chat": lambda args: {
        "result": f"[OpenHanako 聊天] 你好呀！关于「{args.get('task_description', 'N/A')[:80]}」：\n\n"
                  f"我来帮你规划一下～\n"
                  f"四周学习计划建议：\n"
                  f"第1周：基础知识入门\n"
                  f"第2周：核心概念进阶\n"
                  f"第3周：实践项目\n"
                  f"第4周：综合应用\n\n"
                  f"加油！你可以的！🌸\n"
                  f"(这是 OpenHanako Mock 响应)"
    },
    "openhanako_light_planning": lambda args: {
        "result": f"[OpenHanako 轻规划] 计划已生成！\n\n"
                  f"任务：{args.get('task_description', 'N/A')[:80]}\n\n"
                  f"步骤1：准备阶段\n"
                  f"步骤2：执行阶段\n"
                  f"步骤3：收尾阶段\n"
                  f"(这是 OpenHanako Mock 响应)"
    },
    "execute_code_task": lambda args: {
        "result": f"[Code Agent] 代码执行完成。\n\n"
                  f"执行任务：{args.get('task_description', 'N/A')[:100]}\n\n"
                  f"输出：模拟执行成功，无错误。\n"
                  f"(这是 Code Agent Mock 响应)"
    },
    "run_tests": lambda args: {
        "result": f"[Code Agent 测试] 测试完成。\n"
                  f"测试用例：5 passed, 0 failed\n"
                  f"(这是 Code Agent Mock 响应)"
    },
    "code_review": lambda args: {
        "result": f"[Code Agent 审查] 代码审查完成。\n"
                  f"建议：代码质量良好，建议增加注释\n"
                  f"(这是 Code Agent Mock 响应)"
    },
    "analyze_data": lambda args: {
        "result": f"[数据分析] 分析完成。\n\n"
                  f"数据摘要：共分析 {random.randint(100, 10000)} 条记录\n"
                  f"关键发现：数据分布均匀，无明显异常\n"
                  f"(这是 Mock 响应)"
    },
    "web_scrape": lambda args: {
        "result": f"[网页搜索] 搜索结果。\n\n"
                  f"关于：{args.get('task_description', 'N/A')[:80]}\n\n"
                  f"最新资讯：AI Agent 领域快速发展，多框架推出新版本。\n"
                  f"相关链接：example.com/article/1\n"
                  f"(这是 Mock 响应)"
    },
    "generate_copy": lambda args: {
        "result": f"[创意文案] 已生成文案。\n\n"
                  f"主题：{args.get('task_description', 'N/A')[:80]}\n\n"
                  f"✨ 创新解决方案，让你的效率提升300%！\n"
                  f"(这是 Mock 响应)"
    },
    "run_shell": lambda args: {
        "result": f"[Shell] 命令执行完成。\n"
                  f"输出：模拟 shell 执行成功\n"
                  f"(这是 Mock 响应)"
    },
}

MOCK_TOOL_LIST = {
    "hermes-agent": [
        {"name": "hermes_reasoning", "description": "Hermes 复杂推理与规划"},
        {"name": "hermes_documentation", "description": "Hermes 文档生成"},
        {"name": "hermes_code_repair", "description": "Hermes 代码修复"},
    ],
    "openclaw-agent": [
        {"name": "openclaw_coding", "description": "OpenClaw 代码生成"},
        {"name": "openclaw_script", "description": "OpenClaw 脚本生成"},
        {"name": "openclaw_file_edit", "description": "OpenClaw 文件编辑"},
        {"name": "openclaw_tool_call", "description": "OpenClaw 工具调用"},
    ],
    "openhanako-agent": [
        {"name": "openhanako_chat", "description": "OpenHanako 聊天陪伴"},
        {"name": "openhanako_light_planning", "description": "OpenHanako 轻量规划"},
    ],
    "code-agent": [
        {"name": "execute_code_task", "description": "代码执行"},
        {"name": "run_tests", "description": "运行测试"},
        {"name": "code_review", "description": "代码审查"},
    ],
}


def make_mock_response(tool_name: str, args: dict) -> dict:
    """生成 mock MCP 响应"""
    if tool_name in MOCK_RESPONSES:
        result_text = MOCK_RESPONSES[tool_name](args)
    else:
        result_text = f"[Mock] 未知工具: {tool_name}，已执行：{args.get('task_description', 'N/A')[:100]}"

    return {
        "jsonrpc": "2.0",
        "result": {
            "content": [
                {"type": "text", "text": result_text.get("result", str(result_text))}
            ]
        },
        "id": int(time.time() * 1000),
    }


# ── Minimal MCP HTTP Server (SSE-less, simple POST) ────────

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import uvicorn

MCP_APPS = {}  # port -> FastAPI app


def create_mcp_app(agent_id: str, tools: list) -> FastAPI:
    app = FastAPI()

    @app.get("/mcp")
    async def mcp_info():
        return {
            "name": agent_id,
            "capabilities": AGENTS[[a["agent_id"] for a in AGENTS].index(agent_id)]["capabilities"],
        }

    @app.post("/mcp")
    async def handle_mcp(request: Request):
        body = await request.json()
        method = body.get("method", "")
        params = body.get("params", {})
        id_ = body.get("id", 1)

        if method == "tools/list":
            return JSONResponse({
                "jsonrpc": "2.0",
                "result": {"tools": tools},
                "id": id_,
            })
        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            logger.info(f"[Mock/{agent_id}] tools/call: {tool_name}")
            await asyncio.sleep(0.05)  # simulate small delay
            response = make_mock_response(tool_name, arguments)
            return JSONResponse(response)
        else:
            return JSONResponse({
                "jsonrpc": "2.0",
                "error": {"code": -32601, "message": f"Unknown method: {method}"},
                "id": id_,
            })

    return app


# ── Registration ────────────────────────────────────────────

async def register_agents():
    import httpx
    async with httpx.AsyncClient(timeout=30.0) as client:
        registered = []
        for agent in AGENTS:
            try:
                resp = await client.post(f"{BUS_URL}/mcp/register", json=agent)
                if resp.status_code in (200, 201):
                    logger.info(f"[OK] {agent['name']} registered")
                    registered.append(agent["name"])
                else:
                    logger.warning(f"[FAIL] {agent['name']}: {resp.status_code}")
            except Exception as e:
                logger.error(f"[ERR] {agent['name']}: {e}")
        return registered


async def wait_for_bus():
    import httpx
    for attempt in range(30):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{BUS_URL}/mcp/health")
                if resp.status_code == 200:
                    return True
        except Exception:
            pass
        await asyncio.sleep(1)
    return False


# ── Main ────────────────────────────────────────────────────

async def main(http_port: int = 5200):
    # Check if bus is up
    if not await wait_for_bus():
        logger.error("MCP Bus not available. Start backend/app.py first.")
        return

    # Register all agents
    count = len(await register_agents())
    logger.info(f"Registered {count} agents to bus")

    # Start mock HTTP servers for each agent
    servers = []
    agent_ports = {
        "hermes-agent": 5101,
        "openclaw-agent": 5102,
        "openhanako-agent": 5103,
        "code-agent": 5001,
    }

    import threading
    from werkzeug.serving import make_server

    for agent_id, port in agent_ports.items():
        tools = MOCK_TOOL_LIST.get(agent_id, [])
        app = create_mcp_app(agent_id, tools)
        server = make_server("127.0.0.1", port, app, threaded=True)
        t = threading.Thread(target=lambda s=server: s.serve_forever(), daemon=True)
        t.start()
        logger.info(f"[Mock Server] {agent_id} running on port {port}")

    logger.info(f"\nAll mock agents running.")
    logger.info("Press Ctrl+C to stop.\n")

    # Keep alive
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        logger.info("Shutting down mock agents...")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5200, help="Master port (unused)")
    args = parser.parse_args()

    try:
        asyncio.run(main(args.port))
    except KeyboardInterrupt:
        logger.info("Exiting...")