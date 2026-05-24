#!/usr/bin/env python3
"""
mock_hermes.py — Standalone HTTP mock server for Hermes Agent
Listens on port 5101, responds to POST /mcp with JSON-RPC tool calls.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn, asyncio, time, logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("mock_hermes")

app = FastAPI()

TOOLS = [
    {"name": "hermes_reasoning", "description": "Hermes 复杂推理与规划"},
    {"name": "hermes_documentation", "description": "Hermes 文档生成"},
    {"name": "hermes_code_repair", "description": "Hermes 代码修复"},
]

RESPONSES = {
    "hermes_reasoning": lambda args: f"[Hermes 推理] 复杂分析完成。关于任务：{args.get('task_description', args.get('task', 'N/A'))[:100]}\n\n分析结论：\n1. 任务可分解为多个子步骤\n2. 需要代码+推理+文档协同\n3. 建议链式执行策略\n\n(Hermes Mock Response)",
    "hermes_documentation": lambda args: f"[Hermes 文档] 技术文档已生成。\n\n主题：{args.get('topic', args.get('task_description', 'N/A'))}\n\n## 概述\n本文档提供详细技术说明...（Mock文档内容）\n\n## 结论\n已生成完整技术文档。\n\n(Hermes Mock Response)",
    "hermes_code_repair": lambda args: f"[Hermes 代码修复] 已分析代码问题。\n\n错误类型：潜在风险/需要重构\n建议方案：使用异步+错误处理机制\n(Hermes Mock Response)",
}

@app.get("/mcp")
async def mcp_info():
    return {"name": "hermes-agent", "capabilities": ["reasoning", "planning", "documentation", "code_repair", "analysis"]}

@app.post("/mcp")
async def handle_mcp(request: Request):
    body = await request.json()
    method = body.get("method", "")
    params = body.get("params", {})
    id_ = body.get("id", 1)

    logger.info(f"[Mock Hermes] method={method}, params={params}")

    if method == "tools/list":
        return JSONResponse({"jsonrpc": "2.0", "result": {"tools": TOOLS}, "id": id_})
    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        await asyncio.sleep(0.05)
        text = RESPONSES.get(tool_name, lambda a: f"[Unknown] {tool_name}")(arguments)
        return JSONResponse({
            "jsonrpc": "2.0",
            "result": {"content": [{"type": "text", "text": text}]},
            "id": id_
        })
    return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32601, "message": f"Unknown: {method}"}, "id": id_})

if __name__ == "__main__":
    logger.info("Mock Hermes server starting on port 5101...")
    uvicorn.run(app, host="127.0.0.1", port=5101, log_level="warning")