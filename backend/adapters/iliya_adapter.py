"""
iliya_adapter.py — 伊利亚 (iliya) 适配器

iliya 是 All-Agent Manager 的总调度中枢——从废墟里长出来的少年，
同时具备独立执行能力：
  - 意图识别与任务拆解
  - 子 Agent 路由调度
  - 命令执行（shell、系统操作）
  - 文件读写操作
  - 亲密度与技能管理
  - MCP / MiniMax 工具调用
"""

import asyncio
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.base_adapter import BaseAgentAdapter
from backend.core.task_schema import AgentTask, AgentResult
from backend.command_safety import is_command_safe

logger = logging.getLogger(__name__)


class IliyaAdapter(BaseAgentAdapter):
    """
    iliya 适配器

    适用于：
    - 意图识别与任务拆解
    - 子 Agent 路由调度与协同编排
    - 命令执行（受安全策略约束）
    - 文件读写操作
    - 技能/插件/亲密度管理
    - MCP / MiniMax 工具调用

    人格：从废墟里长出来的少年，白天大大咧咧阳光开朗，
    夜晚脆弱内耗，死磕行动力，心软记恩，说话直接。
    """

    agent_name = "iliya"
    agent_type = "orchestrator_agent"
    capabilities = [
        "intent_recognition",
        "task_decomposition",
        "agent_routing",
        "command_execution",
        "file_operation",
        "skill_management",
        "plugin_management",
        "mcp_tool_call",
        "minimax_tool_call",
        "intimacy_management",
    ]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.workspace = self.config.get("workspace") or os.getenv("ILIYA_WORKSPACE", "")
        self._allow_shell = self.config.get("allow_shell", False)
        self._wechat_agent = None

    def bind_wechat_agent(self, wechat_agent: Any) -> None:
        self._wechat_agent = wechat_agent

    def can_handle(self, task: AgentTask) -> float:
        keywords = [
            "调度", "分发", "路由", "编排", "协调", "指挥",
            "执行命令", "运行命令", "跑一下", "shell", "命令行",
            "读文件", "写文件", "查看文件", "文件操作",
            "技能", "插件", "亲密度",
            "iliya", "伊利亚", "从废墟里长出来",
            "schedule", "dispatch", "orchestrate", "route",
            "execute", "command", "run",
        ]

        if task.task_type in self.capabilities:
            return 0.95

        content_lower = task.content.lower()
        matched = sum(1 for k in keywords if k in content_lower)
        if matched >= 3:
            return 0.90
        elif matched >= 2:
            return 0.80
        elif matched >= 1:
            return 0.65

        if task.task_type in ("dispatched", "orchestration", "command"):
            return 0.70

        return 0.15

    def run(self, task: AgentTask) -> AgentResult:
        try:
            payload = self.normalize_input(task)
            task_type = payload.get("task_type", "general")
            context = payload.get("context", {})
            content = payload.get("content", "")

            if task_type == "command_execution" or context.get("action") == "execute":
                return self._execute_command(task, content, context)

            if task_type == "file_operation" or context.get("action") in ("read", "write", "list"):
                return self._execute_file_operation(task, content, context)

            if task_type == "skill_management" or context.get("action") == "skill":
                return self._execute_skill_management(task, content, context)

            if task_type == "agent_routing" or context.get("action") == "dispatch":
                return self._execute_agent_routing(task, content, context)

            if self._wechat_agent:
                return AgentResult(
                    task_id=task.task_id,
                    agent_name=self.agent_name,
                    status="completed",
                    result=f"[iliya] 任务已接收，请通过 WeChatAgent 异步处理：{content}",
                    metadata={"note": "同步 run() 不支持 WeChatAgent 异步调用，请使用 run_async()"},
                )

            raw_output = f"[iliya] 已处理任务：{content}"
            return self.normalize_output(task, raw_output)

        except Exception as e:
            return AgentResult(
                task_id=task.task_id,
                agent_name=self.agent_name,
                status="failed",
                result="",
                error=str(e),
            )

    async def run_async(self, task: AgentTask) -> AgentResult:
        try:
            payload = self.normalize_input(task)
            task_type = payload.get("task_type", "general")
            context = payload.get("context", {})
            content = payload.get("content", "")

            if task_type == "command_execution" or context.get("action") == "execute":
                return await asyncio.get_event_loop().run_in_executor(
                    None, self._execute_command, task, content, context
                )

            if task_type == "file_operation" or context.get("action") in ("read", "write", "list"):
                return await self._execute_file_operation_async(task, content, context)

            if task_type == "skill_management" or context.get("action") == "skill":
                return self._execute_skill_management(task, content, context)

            if task_type == "agent_routing" or context.get("action") == "dispatch":
                return self._execute_agent_routing(task, content, context)

            if self._wechat_agent:
                result = await self._wechat_agent.process_message(
                    user_text=content,
                    chat_id=context.get("chat_id", ""),
                    agent_id=context.get("agent_id"),
                )
                return AgentResult(
                    task_id=task.task_id,
                    agent_name=self.agent_name,
                    status="completed",
                    result=result or "",
                )

            raw_output = f"[iliya] 已处理任务：{content}"
            return self.normalize_output(task, raw_output)

        except Exception as e:
            return AgentResult(
                task_id=task.task_id,
                agent_name=self.agent_name,
                status="failed",
                result="",
                error=str(e),
            )

    def _execute_command(self, task: AgentTask, content: str, context: dict) -> AgentResult:
        command = context.get("command") or content
        cwd = context.get("cwd", self.workspace or None)
        timeout = context.get("timeout", 60)

        if not self._allow_shell and not context.get("force", False):
            return AgentResult(
                task_id=task.task_id,
                agent_name=self.agent_name,
                status="failed",
                result="",
                error="命令执行未启用。请在 IliyaAdapter 配置中设置 allow_shell=True 或在 context 中传入 force=True",
            )

        safe, reason = is_command_safe(command)
        if not safe:
            return AgentResult(
                task_id=task.task_id,
                agent_name=self.agent_name,
                status="failed",
                result="",
                error=f"命令被安全策略拦截: {reason}",
            )

        try:
            logger.info(f"[iliya] 执行命令: {command} (cwd={cwd})")
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )

            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"

            status = "completed" if result.returncode == 0 else "failed"
            error = "" if result.returncode == 0 else f"Exit code: {result.returncode}"

            return AgentResult(
                task_id=task.task_id,
                agent_name=self.agent_name,
                status=status,
                result=output,
                error=error,
                metadata={"return_code": result.returncode, "command": command},
            )

        except subprocess.TimeoutExpired:
            return AgentResult(
                task_id=task.task_id,
                agent_name=self.agent_name,
                status="failed",
                result="",
                error=f"命令执行超时 ({timeout}s)",
            )
        except Exception as e:
            return AgentResult(
                task_id=task.task_id,
                agent_name=self.agent_name,
                status="failed",
                result="",
                error=str(e),
            )

    def _execute_file_operation(self, task: AgentTask, content: str, context: dict) -> AgentResult:
        operation = context.get("action", "read")
        path = context.get("path", content)

        try:
            target = Path(path)
            if not target.is_absolute() and self.workspace:
                target = Path(self.workspace) / path

            if operation == "read":
                if not target.exists():
                    return AgentResult(
                        task_id=task.task_id,
                        agent_name=self.agent_name,
                        status="failed",
                        result="",
                        error=f"文件不存在: {target}",
                    )
                text = target.read_text(encoding="utf-8")
                return AgentResult(
                    task_id=task.task_id,
                    agent_name=self.agent_name,
                    status="completed",
                    result=text,
                    metadata={"operation": "read", "path": str(target)},
                )

            elif operation == "write":
                file_content = context.get("file_content", context.get("content", ""))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(file_content, encoding="utf-8")
                return AgentResult(
                    task_id=task.task_id,
                    agent_name=self.agent_name,
                    status="completed",
                    result=f"文件已写入: {target}",
                    metadata={"operation": "write", "path": str(target)},
                )

            elif operation == "list":
                if not target.exists():
                    return AgentResult(
                        task_id=task.task_id,
                        agent_name=self.agent_name,
                        status="failed",
                        result="",
                        error=f"目录不存在: {target}",
                    )
                entries = [f"{p.name}{'/' if p.is_dir() else ''}" for p in sorted(target.iterdir())]
                return AgentResult(
                    task_id=task.task_id,
                    agent_name=self.agent_name,
                    status="completed",
                    result="\n".join(entries),
                    metadata={"operation": "list", "path": str(target), "count": len(entries)},
                )

            else:
                return AgentResult(
                    task_id=task.task_id,
                    agent_name=self.agent_name,
                    status="failed",
                    result="",
                    error=f"未知文件操作: {operation}",
                )

        except Exception as e:
            return AgentResult(
                task_id=task.task_id,
                agent_name=self.agent_name,
                status="failed",
                result="",
                error=str(e),
            )

    async def _execute_file_operation_async(self, task: AgentTask, content: str, context: dict) -> AgentResult:
        return await asyncio.get_event_loop().run_in_executor(
            None, self._execute_file_operation, task, content, context
        )

    def _execute_skill_management(self, task: AgentTask, content: str, context: dict) -> AgentResult:
        if not self._wechat_agent:
            return AgentResult(
                task_id=task.task_id,
                agent_name=self.agent_name,
                status="failed",
                result="",
                error="WeChatAgent 未绑定，无法管理技能",
            )

        sub_action = context.get("sub_action", "list")
        if sub_action == "list":
            result_text = self._wechat_agent._list_all_skills()
        elif sub_action == "execute":
            skill_id = context.get("skill_id", "")
            result_text = f"技能 {skill_id} 执行请求已记录（异步执行需通过 WeChatAgent）"
        elif sub_action == "plugins":
            result_text = self._wechat_agent._list_plugins()
        else:
            result_text = self._wechat_agent._list_all_skills()

        return AgentResult(
            task_id=task.task_id,
            agent_name=self.agent_name,
            status="completed",
            result=result_text,
        )

    def _execute_agent_routing(self, task: AgentTask, content: str, context: dict) -> AgentResult:
        target_agent = context.get("target_agent", "")
        task_description = context.get("task_description", content)

        if not target_agent:
            return AgentResult(
                task_id=task.task_id,
                agent_name=self.agent_name,
                status="completed",
                result=f"[iliya] 任务已接收，待路由分发: {task_description}",
                metadata={"routed": False},
            )

        return AgentResult(
            task_id=task.task_id,
            agent_name=self.agent_name,
            status="completed",
            result=f"[iliya] 任务已路由到 {target_agent}: {task_description}",
            metadata={"routed": True, "target_agent": target_agent},
        )

    def health_check(self) -> Dict[str, Any]:
        base = super().health_check()
        base["capabilities_count"] = len(self.capabilities)
        base["shell_enabled"] = self._allow_shell
        base["workspace"] = self.workspace or "(未设置)"
        base["wechat_agent_bound"] = self._wechat_agent is not None
        return base
