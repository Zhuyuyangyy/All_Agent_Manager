#!/usr/bin/env python3
"""
mock_subagents.py — Runs ALL mock agent servers in-process.
Uses threading + werkzeug to avoid multiprocessing issues.
All servers share this process but listen on different ports.
"""

import sys
import os
import threading
import logging

# Ensure utf-8 encoding for stdout
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", encoding='utf-8')
logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

# ── Tool definitions ─────────────────────────────────────────

TOOLS = {
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

RESPONSES = {
    "hermes_reasoning": lambda a: f"[Hermes 推理] 复杂分析完成。\n\n任务：{a.get('task_description', a.get('task', 'N/A'))[:100]}\n\n结论：\n1. 任务可分解为多个子步骤\n2. 需要代码+推理+文档协同\n3. 建议链式执行策略\n\n(Hermes Mock)",
    "hermes_documentation": lambda a: f"[Hermes 文档] 技术文档已生成。\n\n主题：{a.get('topic', a.get('task_description', 'N/A'))[:80]}\n\n## 概述\n本文档提供详细技术说明...\n\n## 结论\n已生成完整技术文档。\n\n(Hermes Mock)",
    "hermes_code_repair": lambda a: f"[Hermes 代码修复] 代码问题已分析。\n\n建议：使用异步+错误处理机制\n(Hermes Mock)",
    "openclaw_coding": lambda a: f"[OpenClaw 代码] 已生成代码。\n\n```python\n# {a.get('task_description', 'Task')[:80]}\nimport asyncio\n\nasync def main():\n    print('Hello from OpenClaw Mock!')\n\nif __name__ == '__main__':\n    asyncio.run(main())\n```\n\n(OpenClaw Mock)",
    "openclaw_script": lambda a: f"[OpenClaw 脚本] 已生成脚本。\n\n```bash\n#!/bin/bash\nfor url in $(cat urls.txt); do\n    wget --tries=3 \"$url\"\ndone\n```\n\n(OpenClaw Mock)",
    "openclaw_file_edit": lambda a: f"[OpenClaw 文件编辑] 已完成文件修改。\n(OpenClaw Mock)",
    "openclaw_tool_call": lambda a: f"[OpenClaw 工具调用] 已执行。\n(OpenClaw Mock)",
    "openhanako_chat": lambda a: f"[OpenHanako 聊天] 你好呀！关于「{a.get('task_description', 'N/A')[:80]}」：\n\n我来帮你规划一下～\n四周学习计划建议：\n第1周：基础知识入门\n第2周：核心概念进阶\n第3周：实践项目\n第4周：综合应用\n\n加油！你可以的！🌸\n\n(OpenHanako Mock)",
    "openhanako_light_planning": lambda a: f"[OpenHanako 轻规划] 计划已生成！\n步骤1：准备阶段\n步骤2：执行阶段\n步骤3：收尾阶段\n\n(OpenHanako Mock)",
    "execute_code_task": lambda a: f"[Code Agent] 代码执行完成。\n任务：{a.get('task_description', 'N/A')[:100]}\n输出：模拟执行成功，无错误。\n\n(Code Agent Mock)",
    "run_tests": lambda a: f"[Code Agent 测试] 测试完成。\n测试用例：5 passed, 0 failed\n(Code Agent Mock)",
    "code_review": lambda a: f"[Code Agent 审查] 代码审查完成。\n建议：代码质量良好，建议增加注释\n(Code Agent Mock)",
    "analyze_data": lambda a: f"[数据分析] 分析完成。\n共分析 {1000} 条记录\n关键发现：数据分布均匀\n( Mock)",
    "web_scrape": lambda a: f"[网页搜索] 搜索结果。\n关于：{a.get('task_description', 'N/A')[:80]}\n最新资讯：AI Agent 快速发展\n( Mock)",
    "generate_copy": lambda a: f"[创意文案] 已生成文案。\n主题：{a.get('task_description', 'N/A')[:80]}\n✨ 创新解决方案，效率提升300%！\n( Mock)",
    "run_shell": lambda a: f"[Shell] 命令执行完成。\n( Mock)",
}


def make_app(agent_id: str, port: int):
    app = FastAPI()

    @app.get("/mcp")
    async def info():
        return {"name": agent_id, "capabilities": list(TOOLS.get(agent_id, []))}

    @app.post("/mcp")
    async def handle(request: Request):
        body = await request.json()
        method = body.get("method", "")
        params = body.get("params", {})
        id_ = body.get("id", 1)

        if method == "tools/list":
            return JSONResponse({"jsonrpc": "2.0", "result": {"tools": TOOLS.get(agent_id, [])}, "id": id_})
        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            text = RESPONSES.get(tool_name, lambda a: f"[Unknown] {tool_name}")(arguments)
            return JSONResponse({
                "jsonrpc": "2.0",
                "result": {"content": [{"type": "text", "text": text}]},
                "id": id_
            })
        return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32601, "message": f"Unknown: {method}"}, "id": id_})

    return app


def run_server(app, host, port):
    uvicorn.run(app, host=host, port=port, log_level="error", access_log=False)


AGENTS = [
    ("hermes-agent", 5101),
    ("openclaw-agent", 5102),
    ("openhanako-agent", 5103),
    ("code-agent", 5001),
]

if __name__ == "__main__":
    # Register with MCP Bus
    import httpx, asyncio, json

    BUS_URL = "http://localhost:8000/bus"

    async def register_all():
        await asyncio.sleep(1)  # wait for bus
        async with httpx.AsyncClient(timeout=10.0) as client:
            registered = []
            for agent_id, port in AGENTS:
                capabilities = {
                    "hermes-agent": ["reasoning", "planning", "documentation", "code_repair", "analysis"],
                    "openclaw-agent": ["coding", "tool_use", "script", "file_edit", "code"],
                    "openhanako-agent": ["chat", "companion", "planning_light"],
                    "code-agent": ["code", "execution", "testing"],
                }
                payload = {
                    "agent_id": agent_id,
                    "name": agent_id,
                    "description": f"{agent_id} Mock MCP Server",
                    "capabilities": capabilities.get(agent_id, []),
                    "mcp_endpoint": f"http://localhost:{port}/mcp",
                }
                try:
                    r = await client.post(f"{BUS_URL}/mcp/register", json=payload)
                    if r.status_code == 200:
                        logger.info(f"[OK] {agent_id} registered")
                        registered.append(agent_id)
                    else:
                        logger.warning(f"[FAIL] {agent_id}: {r.status_code}")
                except Exception as e:
                    logger.error(f"[ERR] {agent_id}: {e}")
            return registered

    async def main():
        registered = await register_all()
        logger.info(f"Registered {len(registered)} agents to bus")

        threads = []
        for agent_id, port in AGENTS:
            app = make_app(agent_id, port)
            t = threading.Thread(target=run_server, args=(app, "127.0.0.1", port), daemon=True)
            t.start()
            logger.info(f"Mock {agent_id} running on port {port}")

        # Add research capability to code-agent for scene 4
        code_agent_tools = TOOLS["code-agent"]
        code_agent_tools.append({"name": "web_scrape", "description": "Web search and scraping"})
        code_agent_tools.append({"name": "analyze_data", "description": "Data analysis"})

        logger.info("All mock agents running. Press Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(3600)
        except KeyboardInterrupt:
            logger.info("Shutting down...")

    asyncio.run(main())