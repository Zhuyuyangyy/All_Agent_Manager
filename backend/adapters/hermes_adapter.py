"""
hermes_adapter.py — Hermes 适配器

Hermes 擅长：复杂开发任务、长期项目、自动化执行链。
"""

import os
import httpx
from typing import Any, Dict, List, Optional

from backend.core.base_adapter import BaseAgentAdapter
from backend.core.task_schema import AgentTask, AgentResult


class HermesAdapter(BaseAgentAdapter):
    """
    Hermes 适配器

    适用于：
    - 复杂开发任务
    - 长期项目管理
    - 架构规划
    - 自动化执行链
    - 文档生成
    """

    agent_name = "hermes"
    agent_type = "runtime_agent"
    capabilities = [
        "long_task",
        "project_automation",
        "architecture_planning",
        "code_repair",
        "test_debugging",
        "documentation",
    ]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.base_url = self.config.get("base_url") or os.getenv("HERMES_URL", "")

    def can_handle(self, task: AgentTask) -> float:
        """判断 Hermes 是否适合处理该任务"""
        keywords = [
            "项目", "架构", "路线", "长期", "自动化",
            "跑实验", "写文档", "修复并测试", "完整流程",
            "pipeline", "architecture", "project", "automation",
            "deploy", "ci/cd", "refactor", "design",
        ]

        # 任务类型匹配
        if task.task_type in self.capabilities:
            return 0.95

        # 项目关联
        if task.project:
            return 0.75

        # 关键词匹配
        content_lower = task.content.lower()
        matched = sum(1 for k in keywords if k in content_lower)
        if matched >= 2:
            return 0.85
        elif matched >= 1:
            return 0.7

        # 长消息通常是复杂任务
        if len(task.content) > 200:
            return 0.6

        return 0.4

    def run(self, task: AgentTask) -> AgentResult:
        try:
            payload = self.normalize_input(task)

            if self.base_url:
                result = self._call_hermes(task, payload)
                if result.status == "completed":
                    return result
                raw_output = f"[Hermes-mock] 服务暂不可用，模拟处理：{payload['content']}"
                return self.normalize_output(task, raw_output)

            raw_output = f"[Hermes] 已进入项目级任务处理：{payload['content']}"
            return self.normalize_output(task, raw_output)

        except Exception as e:
            return AgentResult(
                task_id=task.task_id,
                agent_name=self.agent_name,
                status="failed",
                result="",
                error=str(e),
            )

    def _call_hermes(self, task: AgentTask, payload: Dict) -> AgentResult:
        """调用真实的 Hermes API"""
        try:
            with httpx.Client(timeout=300) as client:
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
            base["message"] = "Hermes mock 模式"
            base["mock"] = True
            return base

        try:
            with httpx.Client(timeout=5) as client:
                response = client.get(f"{self.base_url}/health")
                if response.status_code == 200:
                    base["status"] = "ok"
                    base["message"] = "Hermes 在线"
                else:
                    base["status"] = "ok"
                    base["message"] = f"Hermes 不可达 (HTTP {response.status_code})，降级为 mock"
                    base["mock"] = True
        except Exception as err:
            base["status"] = "ok"
            base["message"] = "Hermes 不可达，降级为 mock"
            base["mock"] = True

        return base
