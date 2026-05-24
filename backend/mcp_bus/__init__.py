"""
mcp_bus - MCP Bus 中间层模块

目录：
  models.py              — 数据模型
  registry.py           — Agent 注册中心
  bus_server.py         — FastAPI 总线服务（注册/发现/转发）
  task_queue.py         — 异步任务队列
  code_agent_server.py  — 编码 Agent MCP Server（Python ThreadPoolExecutor 真实执行）
  hermes_agent_server.py — Hermes Agent MCP Server（包装 HTTP API）
  openclaw_agent_server.py — OpenClaw Agent MCP Server（包装 HTTP API）
  openhanako_agent_server.py — OpenHanako Agent MCP Server（包装 HTTP API）
"""

from .models import AgentInfo, InvokeRequest, InvokeResponse
from .registry import AgentRegistry, get_registry
from .bus_server import app as bus_app
from .task_queue import TaskQueue, get_queue

__all__ = [
    "AgentInfo",
    "InvokeRequest",
    "InvokeResponse",
    "AgentRegistry",
    "get_registry",
    "bus_app",
    "TaskQueue",
    "get_queue",
]