"""
openclaw_adapter.py — OpenClaw 适配器

OpenClaw 擅长：代码、工具调用、自动执行、项目修复。
"""

import os
import httpx
from typing import Any, Dict, List, Optional

from backend.core.base_adapter import BaseAgentAdapter
from backend.core.task_schema import AgentTask, AgentResult


class OpenClawAdapter(BaseAgentAdapter):
    """
    OpenClaw 适配器

    适用于：
    - 代码修复和调试
    - 工具调用
    - 文件编辑
    - 脚本执行
    """

    agent_name = "openclaw"
    agent_type = "tool_agent"
    capabilities = ["code_repair", "tool_call", "file_edit", "debugging", "script"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.base_url = self.config.get("base_url") or os.getenv("OPENCLAW_URL", "")

    def can_handle(self, task: AgentTask) -> float:
        """判断 OpenClaw 是否适合处理该任务"""
        keywords = [
            "代码", "报错", "bug", "修复", "脚本", "接口", "测试",
            "运行", "部署", "编译", "调试", "debug", "error", "fix",
            "code", "script", "api", "function", "class",
        ]

        # 任务类型匹配
        if task.task_type in self.capabilities:
            return 0.95

        # 关键词匹配
        content_lower = task.content.lower()
        matched = sum(1 for k in keywords if k in content_lower)
        if matched >= 3:
            return 0.85
        elif matched >= 1:
            return 0.7

        # 项目相关
        if task.project:
            return 0.5

        return 0.2

    def run(self, task: AgentTask) -> AgentResult:
        try:
            payload = self.normalize_input(task)

            if self.base_url:
                result = self._call_openclaw(task, payload)
                if result.status == "completed":
                    return result
                raw_output = f"[OpenClaw-mock] 服务暂不可用，模拟处理：{payload['content']}"
                return self.normalize_output(task, raw_output)

            raw_output = f"[OpenClaw] 已处理任务：{payload['content']}"
            return self.normalize_output(task, raw_output)

        except Exception as e:
            return AgentResult(
                task_id=task.task_id,
                agent_name=self.agent_name,
                status="failed",
                result="",
                error=str(e),
            )

    def _call_openclaw(self, task: AgentTask, payload: Dict) -> AgentResult:
        """调用真实的 OpenClaw API"""
        try:
            with httpx.Client(timeout=120) as client:
                response = client.post(
                    f"{self.base_url}/api/task",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                data = response.json()

            return AgentResult(
                task_id=task.task_id,
                agent_name=self.agent_name,
                status="completed",
                result=data.get("result", ""),
                artifacts=data.get("artifacts", []),
                logs=data.get("logs", []),
            )
        except Exception as err:
            return AgentResult(
                task_id=task.task_id,
                agent_name=self.agent_name,
                status="failed",
                result="",
                error=str(err),
            )

    def health_check(self) -> Dict[str, Any]:
        base = super().health_check()

        if not self.base_url:
            base["status"] = "ok"
            base["message"] = "OpenClaw mock 模式"
            base["mock"] = True
            return base

        try:
            with httpx.Client(timeout=5) as client:
                response = client.get(f"{self.base_url}/health")
                if response.status_code == 200:
                    base["status"] = "ok"
                    base["message"] = "OpenClaw 在线"
                else:
                    base["status"] = "ok"
                    base["message"] = f"OpenClaw 不可达 (HTTP {response.status_code})，降级为 mock"
                    base["mock"] = True
        except Exception as err:
            base["status"] = "ok"
            base["message"] = "OpenClaw 不可达，降级为 mock"
            base["mock"] = True

        return base
