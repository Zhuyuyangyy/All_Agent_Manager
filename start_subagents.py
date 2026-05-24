#!/usr/bin/env python3
"""
start_subagents.py — 启动所有子 Agent 并注册到 MCP Bus

用法: python start_subagents.py
需要在 backend/app.py 已运行在 8000 的情况下执行。
"""

import asyncio
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BUS_URL = "http://localhost:8000/bus"

# Agent 定义: (name, port, capabilities, description)
AGENTS = [
    {
        "name": "hermes-agent",
        "port": 5101,
        "capabilities": ["reasoning", "planning", "documentation", "code_repair"],
        "description": "Hermes 复杂推理与规划 Agent",
        "mcp_endpoint": "http://localhost:5101/mcp",
        "tool_names": ["hermes_reasoning", "hermes_code_repair", "hermes_documentation"],
    },
    {
        "name": "openclaw-agent",
        "port": 5102,
        "capabilities": ["coding", "tool_use", "script", "file_edit"],
        "description": "OpenClaw 代码与工具 Agent",
        "mcp_endpoint": "http://localhost:5102/mcp",
        "tool_names": ["openclaw_coding", "openclaw_script", "openclaw_file_edit", "openclaw_tool_call"],
    },
    {
        "name": "openhanako-agent",
        "port": 5103,
        "capabilities": ["chat", "companion", "planning_light"],
        "description": "OpenHanako 陪伴与轻量规划 Agent",
        "mcp_endpoint": "http://localhost:5103/mcp",
        "tool_names": ["openhanako_chat", "openhanako_light_planning"],
    },
    {
        "name": "code-agent",
        "port": 5001,
        "capabilities": ["code", "execution", "testing"],
        "description": "Code Agent 代码执行与测试",
        "mcp_endpoint": "http://localhost:5001/mcp",
        "tool_names": ["execute_code_task", "run_tests", "code_review"],
    },
]

PROCESSES = []


def kill_agents():
    """停止所有已运行的子 agent 进程"""
    import subprocess
    for port in [5101, 5102, 5103, 5001]:
        subprocess.run(f'cmd /c "netstat -ano | findstr :{port} | findstr LISTENING"',
                       shell=True, capture_output=True)


async def register_all():
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        registered = []
        for agent in AGENTS:
            payload = {
                "agent_id": agent["name"],
                "name": agent["name"],
                "description": agent["description"],
                "capabilities": agent["capabilities"],
                "status": "online",
                "mcp_endpoint": agent["mcp_endpoint"],
                "version": "1.0.0",
            }
            try:
                resp = await client.post(f"{BUS_URL}/mcp/register", json=payload)
                if resp.status_code in (200, 201):
                    logger.info(f"[OK] {agent['name']} registered")
                    registered.append(agent["name"])
                else:
                    logger.warning(f"[FAIL] {agent['name']}: {resp.status_code} {resp.text[:100]}")
            except Exception as e:
                logger.error(f"[ERR] {agent['name']}: {e}")

        # Verify
        resp = await client.get(f"{BUS_URL}/mcp/agents")
        agents_data = resp.json()
        logger.info(f"Bus reports {len(agents_data.get('agents', []))} agents: "
                    f"{[a['agent_id'] for a in agents_data.get('agents', [])]}")

        return len(registered)


async def main():
    import httpx

    # Wait for bus to be ready
    logger.info("Waiting for MCP Bus...")
    for attempt in range(30):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{BUS_URL}/mcp/health")
                if resp.status_code == 200:
                    logger.info("MCP Bus is ready")
                    break
        except Exception:
            pass
        await asyncio.sleep(1)
    else:
        logger.error("MCP Bus not available on localhost:8000/bus")
        logger.error("Please start backend/app.py first: python -m uvicorn backend.app:create_app ...")
        return

    # Register all agents
    count = await register_all()
    logger.info(f"Registered {count} agents")


if __name__ == "__main__":
    asyncio.run(main())