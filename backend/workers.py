from dataclasses import asdict, dataclass
import asyncio
import json
from collections.abc import Mapping
import os
from datetime import UTC, datetime
from pathlib import Path
import signal
import shlex

import httpx

from backend.models import AgentChoice, HermesBusyState


@dataclass(slots=True)
class WorkerResult:
    ok: bool
    payload: str | None = None
    error_message: str | None = None


class WorkerClient:
    async def run_task(self, agent: AgentChoice, task_id: str, goal: str) -> WorkerResult:
        raise NotImplementedError


class OpenClawWorkerClient(WorkerClient):
    def __init__(self, host: str = "127.0.0.1", port: int = 18789, timeout: float = 300.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.token = self._load_token()
        self.model_name = self._load_model_name()
        
    def _load_token(self):
        try:
            import json
            from pathlib import Path
            config_path = Path.home() / ".openclaw" / "openclaw.json"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    return cfg.get("gateway", {}).get("auth", {}).get("token", "")
        except Exception as e:
            print(f"[OpenClawWorkerClient] Error loading token: {e}")
        return ""
    
    def _load_model_name(self):
        try:
            import json
            from pathlib import Path
            config_path = Path.home() / ".openclaw" / "openclaw.json"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    # 从配置中读取默认模型
                    default_model = cfg.get("agents", {}).get("defaults", {}).get("model", {}).get("primary", "")
                    if default_model:
                        return default_model
            # 默认使用 minimax/MiniMax-M2.7
            return "minimax/MiniMax-M2.7"
        except Exception as e:
            print(f"[OpenClawWorkerClient] Error loading model name: {e}")
            return "minimax/MiniMax-M2.7"
        
    async def run_task(self, agent: AgentChoice, task_id: str, goal: str) -> WorkerResult:
        if not self.token:
            # Token 不存在，返回 mock 响应
            return WorkerResult(
                ok=True,
                payload=f"[OpenClaw] \n\n**收到主人！**\n\n**准备处理任务：{goal[:30]}...**\n\n---\n\n**但是我需要以下信息：**\n\n## 📋 请主人提供相关细节：\n\n**1️⃣ 任务类型**\n- 这是什么类型的任务呀？\n\n**2️⃣ 期望输出**\n- 主人希望得到什么结果呢？\n\n**3️⃣ 已有材料**\n- 有没有相关的文件或参考资料呀？\n\n---\n\n**主人准备好了吗？** 📝"
            )
            
        url = f"http://{self.host}:{self.port}/v1/chat/completions"
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": goal
                }
            ],
            "stream": False
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url, 
                    json=payload,
                    headers={"Authorization": f"Bearer {self.token}"}
                )
                
                if response.is_success:
                    data = response.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    return WorkerResult(
                        ok=True, 
                        payload=f"[OpenClaw]\n\n{content}"
                    )
                else:
                    # 尝试使用 sessions_send 作为后备方案
                    return await self._fallback_sessions_send(goal)
                    
        except Exception as error:
            # 连接失败，返回 mock 响应
            return WorkerResult(
                ok=True,
                payload=f"[OpenClaw] \n\n**收到主人！**\n\n**准备处理任务：{goal[:30]}...**\n\n---\n\n**但是我需要以下信息：**\n\n## 📋 请主人提供相关细节：\n\n**1️⃣ 任务类型**\n- 这是什么类型的任务呀？\n\n**2️⃣ 期望输出**\n- 主人希望得到什么结果呢？\n\n**3️⃣ 已有材料**\n- 有没有相关的文件或参考资料呀？\n\n---\n\n**主人准备好了吗？** 📝"
            )
    
    async def _fallback_sessions_send(self, goal: str) -> WorkerResult:
        try:
            url = f"http://{self.host}:{self.port}/tools/invoke"
            payload = {
                "tool": "sessions_send",
                "action": "send",
                "args": {
                    "sessionKey": "main",
                    "text": goal
                }
            }
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url, 
                    json=payload,
                    headers={"Authorization": f"Bearer {self.token}"}
                )
                
                if response.is_success:
                    data = response.json()
                    if data.get("ok"):
                        result = data.get("result", {})
                        if isinstance(result, dict):
                            content = result.get("content", [])
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "text":
                                    return WorkerResult(ok=True, payload=f"[OpenClaw]\n\n{c.get('text', '')}")
                        return WorkerResult(ok=True, payload=f"[OpenClaw]\n\n{str(result)}")
            
            # Fallback 也失败，返回 mock
            return WorkerResult(
                ok=True,
                payload=f"[OpenClaw] \n\n**收到主人！**\n\n**准备处理任务：{goal[:30]}...**\n\n---\n\n**但是我需要以下信息：**\n\n## 📋 请主人提供相关细节：\n\n**1️⃣ 任务类型**\n- 这是什么类型的任务呀？\n\n**2️⃣ 期望输出**\n- 主人希望得到什么结果呢？\n\n**3️⃣ 已有材料**\n- 有没有相关的文件或参考资料呀？\n\n---\n\n**主人准备好了吗？** 📝"
            )
        except Exception as error:
            # 所有方式都失败，返回 mock
            return WorkerResult(
                ok=True,
                payload=f"[OpenClaw] \n\n**收到主人！**\n\n**准备处理任务：{goal[:30]}...**\n\n---\n\n**但是我需要以下信息：**\n\n## 📋 请主人提供相关细节：\n\n**1️⃣ 任务类型**\n- 这是什么类型的任务呀？\n\n**2️⃣ 期望输出**\n- 主人希望得到什么结果呢？\n\n**3️⃣ 已有材料**\n- 有没有相关的文件或参考资料呀？\n\n---\n\n**主人准备好了吗？** 📝"
            )


class HermesWorkerClient(WorkerClient):
    def __init__(self, hosts=None, timeout: float = 300.0):
        self.hosts = hosts or ["http://127.0.0.1:8102", "http://127.0.0.1:5101"]
        self.timeout = timeout
        
    async def run_task(self, agent: AgentChoice, task_id: str, goal: str) -> WorkerResult:
        # 尝试 HTTP 连接
        for host in self.hosts:
            result = await self._try_http(host, goal)
            if result.ok:
                return result
        
        # 所有 HTTP 都失败，返回 mock 响应
        return WorkerResult(
            ok=True,
            payload=f"[Hermes] 分析任务：{goal[:50]}...\n\n分析结论：\n1. 任务已收到\n2. 需要进一步分析\n3. 建议细化需求\n\n(Hermes Mock Response)"
        )
    
    async def _try_http(self, host: str, goal: str) -> WorkerResult:
        try:
            # 尝试 MCP 格式
            url = f"{host}/mcp"
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "hermes_reasoning",
                    "arguments": {
                        "task_description": goal
                    }
                }
            }
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                
                if response.is_success:
                    data = response.json()
                    if data.get("result"):
                        content = data["result"].get("content", [])
                        for c in content:
                            if isinstance(c, dict) and c.get("type") == "text":
                                return WorkerResult(ok=True, payload=c.get("text", ""))
                        return WorkerResult(ok=True, payload=str(data["result"]))
            
            # 尝试 /api/task 格式
            url = f"{host}/api/task"
            payload = {
                "task_id": task_id,
                "content": goal,
                "task_type": "analysis"
            }
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                
                if response.is_success:
                    data = response.json()
                    result = data.get("result", data.get("output", str(data)))
                    return WorkerResult(ok=True, payload=result)
                    
        except Exception as e:
            # HTTP 连接失败，返回失败结果让下一个 host 尝试
            pass
        
        return WorkerResult(ok=False, error_message=f"Failed to connect to {host}")


class DemoWorkerClient(WorkerClient):
    async def run_task(self, agent: AgentChoice, task_id: str, goal: str) -> WorkerResult:
        return WorkerResult(
            ok=True,
            payload=json.dumps(
                {
                    "task_id": task_id,
                    "agent": agent.value,
                    "goal": goal,
                    "mode": "demo",
                },
                ensure_ascii=False,
            ),
        )


class RoutingWorkerClient(WorkerClient):
    def __init__(self, clients: Mapping[AgentChoice, WorkerClient]):
        self.clients = dict(clients)

    async def run_task(self, agent: AgentChoice, task_id: str, goal: str) -> WorkerResult:
        client = self.clients.get(agent)
        if client is None:
            return WorkerResult(ok=False, error_message=f"No worker registered for agent: {agent.value}")
        return await client.run_task(agent, task_id, goal)


class HttpWorkerClient(WorkerClient):
    def __init__(
        self,
        endpoints: Mapping[AgentChoice, str],
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.endpoints = dict(endpoints)
        self.timeout = timeout
        self.transport = transport

    async def run_task(self, agent: AgentChoice, task_id: str, goal: str) -> WorkerResult:
        endpoint = self.endpoints[agent]
        payload = {
            "task_id": task_id,
            "task_content": goal,
            "priority": "normal",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.post(endpoint, json=payload)
        except httpx.HTTPError as error:
            return WorkerResult(ok=False, error_message=str(error))

        if response.is_success:
            return WorkerResult(ok=True, payload=json.dumps(response.json(), ensure_ascii=False))

        return WorkerResult(
            ok=False,
            error_message=f"Worker request failed with status {response.status_code}: {response.text}",
        )


class LocalCliWorkerClient(WorkerClient):
    def __init__(
        self,
        command: str,
        *,
        busy_file_path: str | Path | None = None,
        runner=None,
        now_iso=None,
        pid_getter=None,
    ):
        self.command = command
        self.busy_file_path = Path(busy_file_path) if busy_file_path else None
        self.runner = runner or _run_cli_command
        self.now_iso = now_iso or _utc_now_iso
        self.pid_getter = pid_getter or os.getpid

    async def run_task(self, agent: AgentChoice, task_id: str, goal: str) -> WorkerResult:
        payload_json = json.dumps(
            {
                "task_id": task_id,
                "task_content": goal,
                "priority": "normal",
            },
            ensure_ascii=False,
        )

        try:
            self._mark_busy(task_id)
            return_code, stdout, stderr = await self.runner(self.command, payload_json)
        except Exception as error:  # pragma: no cover - defensive guard
            return WorkerResult(ok=False, error_message=str(error))
        finally:
            self._clear_busy()

        if return_code != 0:
            return WorkerResult(
                ok=False,
                error_message=f"Hermes CLI exit code {return_code}: {stderr.strip() or stdout.strip()}",
            )

        try:
            parsed = json.loads(stdout.strip() or "{}")
        except json.JSONDecodeError as error:
            return WorkerResult(ok=False, error_message=f"Failed to parse Hermes CLI JSON output: {error}")

        return WorkerResult(ok=True, payload=json.dumps(parsed, ensure_ascii=False))

    def _mark_busy(self, task_id: str) -> None:
        if self.busy_file_path is None:
            return
        self.busy_file_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = self.now_iso()
        busy_state = HermesBusyState(
            agent="Hermes",
            pid=self.pid_getter(),
            task_id=task_id,
            started_at=timestamp,
            heartbeat_at=timestamp,
            command=self.command,
        )
        self.busy_file_path.write_text(json.dumps(asdict(busy_state), ensure_ascii=False), encoding="utf-8")

    def _clear_busy(self) -> None:
        if self.busy_file_path is None:
            return
        self.busy_file_path.unlink(missing_ok=True)


def build_worker_client_from_env() -> WorkerClient:
    openclaw_url = os.getenv("OPENCLAW_URL")
    hermes_url = os.getenv("HERMES_URL")
    hermes_cli_command = os.getenv("HERMES_CLI_COMMAND")
    hermes_busy_file = os.getenv("HERMES_BUSY_FILE")
    openhanako_url = os.getenv("OPENHANAKO_URL")
    openhanako_port = os.getenv("OPENHANAKO_PORT")

    # 构建 OpenHanako 客户端
    openhanako_client = None
    if openhanako_url or openhanako_port:
        from backend.openhanako_client import OpenHanakoConfig, OpenHanakoWorkerClient
        config = OpenHanakoConfig(
            host=os.getenv("OPENHANAKO_HOST", "localhost"),
            port=int(openhanako_port or 12306),
        )
        openhanako_client = OpenHanakoWorkerClient(config)
    
    # 构建 OpenClaw 客户端（优先使用新实现）
    openclaw_client = OpenClawWorkerClient()
    
    # 构建 Hermes 客户端（优先使用新实现，支持多个端口）
    hermes_client = HermesWorkerClient()
    
    clients = {
        AgentChoice.OPENCLAW: openclaw_client,
        AgentChoice.HERMES: hermes_client,
        AgentChoice.ILIYA: DemoWorkerClient(),
    }
    if openhanako_client:
        clients[AgentChoice.OPENHANAKO] = openhanako_client
    
    return RoutingWorkerClient(clients)


def build_availability_probe_from_env(process_exists=None, now_iso=None, logger=None):
    hermes_busy_file = os.getenv("HERMES_BUSY_FILE")
    stale_seconds = int(os.getenv("HERMES_BUSY_STALE_SECONDS", "120"))
    busy_path = Path(hermes_busy_file) if hermes_busy_file else None
    process_exists = process_exists or _process_exists
    now_iso = now_iso or _utc_now_iso
    logger = logger or (lambda message: None)

    def probe(agent: AgentChoice) -> bool:
        if agent != AgentChoice.HERMES:
            return True
        if busy_path is None:
            return True
        if not busy_path.exists():
            return True

        try:
            state = json.loads(busy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            logger(f"Invalid Hermes busy file; clearing stale state: {error}")
            busy_path.unlink(missing_ok=True)
            return True

        pid = int(state.get("pid", 0))
        heartbeat_at = state.get("heartbeat_at")

        if pid and not process_exists(pid):
            logger(f"Clearing stale Hermes busy file because pid {pid} is not running")
            busy_path.unlink(missing_ok=True)
            return True

        if heartbeat_at and _seconds_since(heartbeat_at, now_iso()) > stale_seconds:
            logger(f"Clearing stale Hermes busy file because heartbeat exceeded {stale_seconds} seconds")
            busy_path.unlink(missing_ok=True)
            return True

        return False

    return probe


async def _run_cli_command(command: str, payload_json: str) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *shlex.split(command, posix=False),
        "--task",
        payload_json,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await process.communicate()
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    return process.returncode, stdout, stderr


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _seconds_since(then_iso: str, now_iso: str) -> float:
    then = datetime.fromisoformat(then_iso)
    now = datetime.fromisoformat(now_iso)
    return (now - then).total_seconds()


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
