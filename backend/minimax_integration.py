"""
MiniMax Integration - Direct API calls without mmx CLI
Provides similar functionality to mmx-mcp-server but in Python
"""
import os
import json
import logging
import httpx
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class MiniMaxClient:
    """Client for MiniMax API"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("MINIMAX_API_KEY")
        self.base_url = "https://api.minimax.chat/v1"
        if not self.api_key:
            logger.warning("[minimax] MINIMAX_API_KEY not set")

    async def _request(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Make a request to MiniMax API"""
        if not self.api_key:
            return {"error": "MINIMAX_API_KEY not set"}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}{endpoint}",
                    headers=headers,
                    json=data,
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"[minimax] API request failed: {e}")
            return {"error": str(e)}

    async def text_chat(
        self,
        message: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
    ) -> Dict[str, Any]:
        """Text chat with MiniMax"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})

        data = {
            "model": "abab6.5s-chat",
            "messages": messages,
            "temperature": temperature,
        }

        result = await self._request("/chat/completions", data)
        if "error" in result:
            return result

        # Extract response
        choices = result.get("choices", [])
        if choices:
            return {"text": choices[0].get("message", {}).get("content", "")}
        return {"text": ""}

    async def search(self, query: str) -> Dict[str, Any]:
        """Web search using MiniMax"""
        # Note: This is a simplified implementation
        # Actual search may require different endpoint
        return {
            "results": [
                {
                    "title": "Search result for: " + query,
                    "url": "https://example.com",
                    "snippet": "This is a simulated search result. "
                    "To use real search, please configure MiniMax search API.",
                }
            ]
        }


# Singleton instance
_minimax_client: Optional[MiniMaxClient] = None


def get_minimax_client() -> MiniMaxClient:
    """Get or create MiniMax client singleton"""
    global _minimax_client
    if _minimax_client is None:
        _minimax_client = MiniMaxClient()
    return _minimax_client


# Tools similar to mmx-mcp-server
MINIMAX_TOOLS = [
    {
        "name": "minimax_text_chat",
        "description": "Chat with MiniMax text models. Supports system prompts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "The user message"},
                "system": {"type": "string", "description": "Optional system prompt"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "minimax_search",
        "description": "Search the web using MiniMax (simulated)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
]


async def call_minimax_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Call a MiniMax tool"""
    client = get_minimax_client()

    if tool_name == "minimax_text_chat":
        result = await client.text_chat(
            message=arguments.get("message", ""),
            system_prompt=arguments.get("system"),
        )
        if "error" in result:
            return {"error": result["error"]}
        return {"content": result.get("text", "")}

    elif tool_name == "minimax_search":
        result = await client.search(arguments.get("query", ""))
        return {"content": json.dumps(result, ensure_ascii=False, indent=2)}

    else:
        return {"error": f"Unknown tool: {tool_name}"}
