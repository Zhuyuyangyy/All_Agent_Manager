"""
models.py — MCP Bus 数据模型
"""

from pydantic import BaseModel
from typing import List, Optional


class AgentInfo(BaseModel):
    """Agent 注册信息"""
    agent_id: str
    name: str                      # 如 "code-agent"
    description: str                # 能力描述，主控用来做语义匹配
    mcp_endpoint: str              # 该 Agent MCP Server 的 URL（HTTP/SSE）
    capabilities: List[str]        # ["python_coding", "debug", ...]
    status: str = "online"         # online | offline | busy
    version: str = "1.0.0"


class RegisterRequest(BaseModel):
    agent: AgentInfo


class DiscoverRequest(BaseModel):
    capability: str


class InvokeRequest(BaseModel):
    """主控 → 子 Agent 的 MCP 调用请求（JSON-RPC 2.0 子集）"""
    method: str = "tools/call"
    params: dict


class InvokeResponse(BaseModel):
    """MCP 调用响应"""
    result: Optional[dict] = None
    error: Optional[str] = None