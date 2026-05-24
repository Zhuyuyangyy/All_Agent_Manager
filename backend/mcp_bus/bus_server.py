"""
bus_server.py — MCP Bus 总路由

提供以下端点：
  POST /mcp/register      — 子 Agent 注册到总线
  GET  /mcp/discover     — 主控发现匹配的子 Agent
  POST /mcp/invoke/{id}  — 主控向指定 Agent 转发任务
  GET  /mcp/agents       — 列出所有已注册 Agent
  DELETE /mcp/unregister/{id} — 注销 Agent
  GET  /mcp/health       — 总线健康状态
"""

import logging
import time
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .models import AgentInfo, InvokeRequest
from .registry import get_registry

logger = logging.getLogger(__name__)

app = FastAPI(title="MCP Bus", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 注册 & 发现 ────────────────────────────────────────────

@app.post("/mcp/register")
def register_agent(agent: AgentInfo):
    """子 Agent 注册到总线"""
    return get_registry().register(agent)


@app.delete("/mcp/unregister/{agent_id}")
def unregister_agent(agent_id: str):
    """注销 Agent"""
    return get_registry().unregister(agent_id)


@app.get("/mcp/discover")
def discover(capability: str):
    """主控根据能力发现匹配的子 Agent"""
    agents = get_registry().find_by_capability(capability)
    return {
        "capability": capability,
        "agents": [
            {
                "agent_id": a.agent_id,
                "name": a.name,
                "description": a.description,
                "capabilities": a.capabilities,
                "status": a.status,
            }
            for a in agents
        ],
    }


@app.get("/mcp/agents")
def list_agents():
    """列出所有已注册 Agent"""
    agents = get_registry().find_all()
    return {
        "agents": [a.model_dump() for a in agents],
        "total": len(agents),
    }


@app.get("/mcp/capabilities")
def list_capabilities():
    """列出所有已知能力"""
    return {"capabilities": get_registry().list_capabilities()}


# ── 任务转发 ────────────────────────────────────────────────

@app.post("/mcp/invoke/{agent_id}")
async def invoke_agent(agent_id: str, request: InvokeRequest):
    """主控通过总线向指定 Agent 转发任务（同步 HTTP 转发）"""
    registry = get_registry()
    agent = registry.get_agent(agent_id)

    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    if agent.status != "online":
        raise HTTPException(status_code=503, detail=f"Agent {agent_id} is {agent.status}")

    logger.info(f"[Bus] Invoke → {agent.name} ({agent_id}), method={request.method}")

    # 构造 MCP JSON-RPC 2.0 请求，转发到子 Agent 的 MCP endpoint
    rpc_request = {
        "jsonrpc": "2.0",
        "method": request.method,
        "params": request.params,
        "id": int(time.time() * 1000),
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(agent.mcp_endpoint, json=rpc_request)
            resp.raise_for_status()
            return resp.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail=f"Agent {agent_id} timed out")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"Agent error: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to invoke agent: {str(e)}")


# ── 健康 & 统计 ─────────────────────────────────────────────

@app.get("/mcp/health")
def health():
    registry = get_registry()
    agents = registry.find_all()
    online = [a for a in agents if a.status == "online"]
    return {
        "status": "healthy",
        "total_agents": len(agents),
        "online_agents": len(online),
        "offline_agents": len(agents) - len(online),
        "capabilities": len(registry.list_capabilities()),
    }