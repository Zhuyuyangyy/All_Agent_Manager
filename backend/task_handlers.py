"""
task_handlers.py — 具体任务处理器实现

为 TaskRegistry 提供各种任务类型的处理器：
- HttpTaskHandler: OpenClaw/OpenHanako HTTP 调用
- CliTaskHandler: Hermes CLI 命令执行
- DiscoveryTaskHandler: 智能发现扫描
- ReplayTaskHandler: 复刻分析任务
- HealthCheckTaskHandler: Agent 健康检查
"""

import asyncio
import json
import logging
import subprocess
import time
from datetime import datetime

import httpx

from backend.task_registry import TaskHandler, TaskResult

logger = logging.getLogger(__name__)


class HttpTaskHandler(TaskHandler):
    """HTTP Worker 任务处理器"""

    def __init__(self, agent_name: str, url: str, timeout: int = 300):
        self._agent_name = agent_name
        self._url = url
        self._timeout = timeout
        self._abort_events: dict[str, asyncio.Event] = {}

    @property
    def task_type(self) -> str:
        return f"http_{self._agent_name}"

    async def execute(self, task_id: str, payload: dict) -> TaskResult:
        """执行 HTTP 任务"""
        start_time = time.time()
        self._abort_events[task_id] = asyncio.Event()

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._url,
                    json={
                        "task_id": task_id,
                        "task_content": payload.get("goal", ""),
                        "priority": payload.get("priority", "normal"),
                    },
                )

                if response.status_code < 300:
                    duration = time.time() - start_time
                    return TaskResult(
                        success=True,
                        payload=response.json() if response.text else {},
                        duration=duration,
                    )
                else:
                    return TaskResult(
                        success=False,
                        error=f"HTTP {response.status_code}: {response.text}",
                        duration=time.time() - start_time,
                    )

        except httpx.TimeoutException:
            return TaskResult(
                success=False,
                error=f"Timeout after {self._timeout}s",
                duration=time.time() - start_time,
            )
        except Exception as e:
            return TaskResult(
                success=False,
                error=str(e),
                duration=time.time() - start_time,
            )
        finally:
            self._abort_events.pop(task_id, None)

    async def abort(self, task_id: str) -> bool:
        """中止 HTTP 任务"""
        event = self._abort_events.get(task_id)
        if event:
            event.set()
            return True
        return False


class CliTaskHandler(TaskHandler):
    """CLI Worker 任务处理器（Hermes）"""

    def __init__(self, command: str, timeout: int = 300, busy_file: str | None = None):
        self._command = command
        self._timeout = timeout
        self._busy_file = busy_file
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    @property
    def task_type(self) -> str:
        return "cli_task"

    def _is_busy(self) -> bool:
        """检查 Hermes 是否忙碌"""
        if not self._busy_file:
            return False
        try:
            import os
            if os.path.exists(self._busy_file):
                # 检查 busy 文件是否过期
                mtime = os.path.getmtime(self._busy_file)
                age = time.time() - mtime
                if age > 120:  # 超过 2 分钟视为过期
                    os.remove(self._busy_file)
                    return False
                return True
        except Exception:
            pass
        return False

    async def execute(self, task_id: str, payload: dict) -> TaskResult:
        """执行 CLI 任务"""
        if self._is_busy():
            return TaskResult(
                success=False,
                error="Hermes is busy",
                duration=0,
            )

        start_time = time.time()

        # 创建 busy 文件
        if self._busy_file:
            try:
                import os
                os.makedirs(os.path.dirname(self._busy_file), exist_ok=True)
                with open(self._busy_file, "w") as f:
                    json.dump({
                        "agent": "hermes",
                        "task_id": task_id,
                        "started_at": datetime.now().isoformat(),
                    }, f)
            except Exception as e:
                logger.warning(f"Failed to create busy file: {e}")

        try:
            # 构建命令
            task_json = json.dumps({
                "task_id": task_id,
                "task_content": payload.get("goal", ""),
                "priority": payload.get("priority", "normal"),
            })
            cmd = f'{self._command} --task "{task_json}"'

            # 执行命令
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._processes[task_id] = process

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self._timeout,
                )

                if process.returncode == 0:
                    try:
                        result_data = json.loads(stdout.decode())
                        return TaskResult(
                            success=True,
                            payload=result_data,
                            duration=time.time() - start_time,
                        )
                    except json.JSONDecodeError:
                        return TaskResult(
                            success=True,
                            payload={"output": stdout.decode()},
                            duration=time.time() - start_time,
                        )
                else:
                    return TaskResult(
                        success=False,
                        error=stderr.decode() or f"Exit code: {process.returncode}",
                        duration=time.time() - start_time,
                    )

            except asyncio.TimeoutError:
                process.kill()
                return TaskResult(
                    success=False,
                    error=f"Timeout after {self._timeout}s",
                    duration=time.time() - start_time,
                )

        finally:
            self._processes.pop(task_id, None)
            # 删除 busy 文件
            if self._busy_file:
                try:
                    import os
                    if os.path.exists(self._busy_file):
                        os.remove(self._busy_file)
                except Exception:
                    pass

    async def abort(self, task_id: str) -> bool:
        """中止 CLI 任务"""
        process = self._processes.get(task_id)
        if process:
            process.kill()
            return True
        return False


class DiscoveryTaskHandler(TaskHandler):
    """智能发现任务处理器"""

    def __init__(self, discovery_module=None):
        self._discovery = discovery_module

    @property
    def task_type(self) -> str:
        return "discovery_task"

    async def execute(self, task_id: str, payload: dict) -> TaskResult:
        """执行发现任务"""
        start_time = time.time()

        try:
            if self._discovery:
                # 使用真实的发现模块
                scan_type = payload.get("scan_type", "all")
                results = await self._discovery.scan(scan_type)
                return TaskResult(
                    success=True,
                    payload={"discovered_tasks": results},
                    duration=time.time() - start_time,
                )
            else:
                # 模拟发现
                await asyncio.sleep(1)
                return TaskResult(
                    success=True,
                    payload={"discovered_tasks": []},
                    duration=time.time() - start_time,
                )
        except Exception as e:
            return TaskResult(
                success=False,
                error=str(e),
                duration=time.time() - start_time,
            )


class ReplayTaskHandler(TaskHandler):
    """复刻分析任务处理器"""

    def __init__(self, replay_engine=None):
        self._replay_engine = replay_engine

    @property
    def task_type(self) -> str:
        return "replay_task"

    async def execute(self, task_id: str, payload: dict) -> TaskResult:
        """执行复刻分析任务"""
        start_time = time.time()

        try:
            if self._replay_engine:
                # 使用真实的复刻引擎
                min_occurrences = payload.get("min_occurrences", 2)
                min_confidence = payload.get("min_confidence", 0.3)

                proposals = self._replay_engine.auto_generate_skills(
                    min_occurrences=min_occurrences,
                    min_confidence=min_confidence,
                )

                return TaskResult(
                    success=True,
                    payload={
                        "proposals": [p.to_dict() for p in proposals],
                        "count": len(proposals),
                    },
                    duration=time.time() - start_time,
                )
            else:
                return TaskResult(
                    success=True,
                    payload={"proposals": [], "count": 0},
                    duration=time.time() - start_time,
                )
        except Exception as e:
            return TaskResult(
                success=False,
                error=str(e),
                duration=time.time() - start_time,
            )


class HealthCheckTaskHandler(TaskHandler):
    """健康检查任务处理器"""

    def __init__(self, health_monitor=None):
        self._health_monitor = health_monitor

    @property
    def task_type(self) -> str:
        return "health_check"

    async def execute(self, task_id: str, payload: dict) -> TaskResult:
        """执行健康检查任务"""
        start_time = time.time()

        try:
            if self._health_monitor:
                # 使用真实的健康监控
                agent = payload.get("agent")
                if agent:
                    result = await self._health_monitor.check_agent(agent)
                else:
                    result = await self._health_monitor.check_all()

                return TaskResult(
                    success=True,
                    payload=result,
                    duration=time.time() - start_time,
                )
            else:
                return TaskResult(
                    success=True,
                    payload={"status": "healthy"},
                    duration=time.time() - start_time,
                )
        except Exception as e:
            return TaskResult(
                success=False,
                error=str(e),
                duration=time.time() - start_time,
            )
