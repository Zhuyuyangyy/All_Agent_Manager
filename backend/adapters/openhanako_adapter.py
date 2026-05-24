"""
openhanako_adapter.py — OpenHanako 适配器

OpenHanako 擅长：聊天、人设、陪伴、轻任务、用户交互。
"""

import os
import httpx
from typing import Any, Dict, List, Optional

from backend.core.base_adapter import BaseAgentAdapter
from backend.core.task_schema import AgentTask, AgentResult


class OpenHanakoAdapter(BaseAgentAdapter):
    """
    OpenHanako 适配器

    适用于：
    - 日常聊天和陪伴
    - 人格化交互
    - 轻量级规划和建议
    - 用户情感支持
    """

    agent_name = "hanako"
    agent_type = "chat_agent"
    capabilities = ["chat", "persona", "companion", "light_planning", "emotion"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._mock_mode = False
        try:
            from backend.openhanako_client import OpenHanakoConfig
            self.hanako_config = OpenHanakoConfig.from_env()
            self.base_url = self.hanako_config.base_url
        except Exception:
            self.hanako_config = None
            self.base_url = ""
            self._mock_mode = True

        if not self.base_url:
            self._mock_mode = True

    def can_handle(self, task: AgentTask) -> float:
        keywords = [
            "聊聊", "陪我", "解释一下", "帮我想想", "建议", "规划",
            "吐槽", "心情", "开心", "难过", "无聊", "聊天", "对话",
            "说说", "想想", "思考", "分析一下", "怎么看",
        ]

        if task.task_type in self.capabilities:
            return 0.95

        content_lower = task.content.lower()
        matched = sum(1 for k in keywords if k in content_lower)
        if matched >= 2:
            return 0.85
        elif matched >= 1:
            return 0.7

        if len(task.content) < 50:
            return 0.6

        return 0.3

    def run(self, task: AgentTask) -> AgentResult:
        try:
            payload = self.normalize_input(task)

            if self._mock_mode:
                raw_output = f"[Hanako] 收到你的消息啦～让我想想：{payload['content']}"
                return self.normalize_output(task, raw_output)

            with httpx.Client(timeout=120) as client:
                try:
                    health_resp = client.get(f"{self.base_url}/api/config")
                    if health_resp.status_code != 200:
                        raw_output = f"[Hanako-mock] 服务暂不可用，模拟回复：{payload['content']}"
                        return self.normalize_output(task, raw_output)
                except Exception:
                    raw_output = f"[Hanako-mock] 服务暂不可用，模拟回复：{payload['content']}"
                    return self.normalize_output(task, raw_output)

                resp = client.post(
                    f"{self.base_url}/api/chat/send",
                    json={"text": task.content, "role": "owner"},
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()

            if data.get("error"):
                return AgentResult(
                    task_id=task.task_id,
                    agent_name=self.agent_name,
                    status="failed",
                    result="",
                    error=data["error"],
                )

            reply_text = data.get("text") or data.get("reply") or ""
            return AgentResult(
                task_id=task.task_id,
                agent_name=self.agent_name,
                status="completed",
                result=reply_text,
                metadata={"source": "openhanako"},
            )

        except Exception as e:
            return AgentResult(
                task_id=task.task_id,
                agent_name=self.agent_name,
                status="failed",
                result="",
                error=str(e),
            )

    def health_check(self) -> Dict[str, Any]:
        base = super().health_check()

        if self._mock_mode:
            base["status"] = "ok"
            base["message"] = "Hanako mock 模式"
            base["mock"] = True
            return base

        try:
            with httpx.Client(timeout=5) as client:
                response = client.get(f"{self.base_url}/api/config")
                if response.status_code == 200:
                    base["status"] = "ok"
                    base["message"] = "OpenHanako 在线"
                else:
                    base["status"] = "ok"
                    base["message"] = f"OpenHanako 不可达 (HTTP {response.status_code})，降级为 mock"
                    base["mock"] = True
        except Exception as err:
            base["status"] = "ok"
            base["message"] = f"OpenHanako 不可达，降级为 mock"
            base["mock"] = True

        if self.hanako_config:
            base["port"] = self.hanako_config.port
            base["url"] = self.hanako_config.base_url

        return base
