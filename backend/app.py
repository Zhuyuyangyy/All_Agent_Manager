"""
app.py — All-Agent Manager 主应用

FastAPI 后端，管理三个子 Agent (OpenClaw, OpenHanako, Hermes)
和一个总调度 Agent (iliya)。
"""

# 加载 .env 文件（必须在其他导入之前）
import os as _os
from pathlib import Path as _Path

def _load_env_file(env_path: _Path) -> None:
    """轻量 .env 解析器，无需 python-dotenv 依赖"""
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # 去掉行内注释（但只在值中没有引号时）
            if not (value.startswith('"') or value.startswith("'")):
                comment_idx = value.find(" #")
                if comment_idx != -1:
                    value = value[:comment_idx].strip()
            # 去掉引号
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            if key and key not in _os.environ:
                _os.environ[key] = value
    except Exception as e:
        print(f"[env] Warning: failed to load {env_path}: {e}")

_dotenv_path = _Path(__file__).resolve().parent.parent / ".env"
_load_env_file(_dotenv_path)
print(f"[env] Loaded .env from: {_dotenv_path} (exists={_dotenv_path.exists()})")
print(f"[env] MINIMAX_API_KEY={'set (' + _os.environ.get('MINIMAX_API_KEY', '')[:12] + '...)' if _os.environ.get('MINIMAX_API_KEY') else 'NOT SET'}")
print(f"[env] OPENCLAW_URL={_os.environ.get('OPENCLAW_URL', 'NOT SET')}")
print(f"[env] OPENHANAKO_PORT={_os.environ.get('OPENHANAKO_PORT', 'NOT SET')}")

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
import time
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.bridge_manager import BridgeManager
from backend.chat import ChatManager, build_chat_manager_from_env
from backend.dispatcher import TaskDispatcher
from backend.event_bus import EventBus
from backend.cluster_orchestrator import ClusterOrchestrator
from backend.cluster_dispatcher import ClusterDispatcher, AgentWorkerFactory
from backend.unified_capability_registry import UnifiedCapabilityRegistry
from backend.skill_loader import SlashCommandRegistry, SkillSynchronizer
from backend import cluster_api
from backend.evolution_guard import EvolutionGuard
from backend.execution_monitor import ExecutionMonitor
from backend.models import (
    AgentChoice,
    SubmitTaskRequest,
    SubmitTaskResponse,
    TaskCreate,
    TaskStatus,
)
from backend.openhanako_client import OpenHanakoConfig
from backend.plugin_manager import PluginManager
from backend.project_discovery import DiscoveryManager
from backend.replay_engine import ReplayEngine
from backend.waiting_scheduler import WaitingTaskScheduler
from backend.skill_memory import (
    SkillMemory,
    SkillSource,
    SkillStatus,
    SkillTemplate,
    build_skill_memory_from_env,
)
from backend.storage import TaskRepository
from backend.task_planner import TaskPlanner
from backend.wechat_agent import WeChatAgent, build_wechat_agent
from backend.workers import DemoWorkerClient

logger = logging.getLogger(__name__)

# ── 全局事件总线 ──
event_bus = EventBus()


def create_app(database_path: str | Path | None = None) -> FastAPI:
    """创建 FastAPI 应用"""

    # ── Storage ──
    db_path = database_path or os.getenv("TASK_DB_PATH", "storage/tasks.db")
    repository = TaskRepository(db_path)
    repository.initialize()
    base_dir = Path(__file__).resolve().parent.parent
    data_dir = base_dir / "storage"
    data_dir.mkdir(parents=True, exist_ok=True)

    # ── Workers ──
    from backend.workers import build_worker_client_from_env, build_availability_probe_from_env

    worker = build_worker_client_from_env()
    availability_probe = build_availability_probe_from_env()

    # ── Execution Monitor ──
    execution_monitor = ExecutionMonitor()

    # ── Task Dispatcher ──
    dispatcher = TaskDispatcher(
        repository=repository,
        worker_client=worker,
        availability_probe=availability_probe,
        execution_monitor=execution_monitor,
    )

    # ── Waiting Scheduler ──
    waiting_scheduler = WaitingTaskScheduler(
        repository=repository,
        dispatcher=dispatcher,
        availability_probe=availability_probe,
    )

    # ── Task Planner ──
    task_planner = TaskPlanner()

    # ── Agent Health ──
    from backend.agent_health import HealthMonitor

    # 设置每 120 秒（2 分钟）检查一次
    health_monitor = HealthMonitor(check_interval=120)

    # ── Chat Manager ──
    chat_manager = build_chat_manager_from_env()

    # ── MCP Client ──
    from backend.mcp_client import McpClient, build_mcp_client_from_env

    mcp_client = build_mcp_client_from_env()

    # ── Agent Router (统一适配器层) ──
    from backend.core.router import AgentRouter
    from backend.adapters.openclaw_adapter import OpenClawAdapter
    from backend.adapters.openhanako_adapter import OpenHanakoAdapter
    from backend.adapters.hermes_adapter import HermesAdapter
    from backend.adapters.iliya_adapter import IliyaAdapter

    agent_router = AgentRouter()
    agent_router.register(IliyaAdapter(config={"workspace": str(data_dir), "allow_shell": os.getenv("ILIYA_ALLOW_SHELL", "").lower() in ("1", "true", "yes")}))
    agent_router.register(OpenClawAdapter())
    agent_router.register(OpenHanakoAdapter())
    agent_router.register(HermesAdapter())

    # ── Multi Agent Orchestrator (多 Agent 编排) ──
    from backend.orchestration.orchestrator import MultiAgentOrchestrator
    from backend.orchestration.aggregator import ResultAggregator

    result_aggregator = ResultAggregator()
    multi_agent_orchestrator = MultiAgentOrchestrator(
        agent_router=agent_router,
        aggregator=result_aggregator
    )

    # ── Skill Memory, Plugin Manager, Replay Engine, Evolution Guard ──
    skill_memory = build_skill_memory_from_env()
    from backend.knowledge_base import build_knowledge_base_from_env
    knowledge_base = build_knowledge_base_from_env()
    plugin_manager = PluginManager(storage_path=str(data_dir / "plugins.json"))
    replay_engine = ReplayEngine(
        task_repository=repository,
        skill_memory=skill_memory,
        plugin_manager=plugin_manager,
    )
    evolution_guard = EvolutionGuard(plugin_manager=plugin_manager)

    # ── 微信独立聊天系统（iliya 调度中枢）──
    wechat_agent = build_wechat_agent(chat_manager, worker, mcp_client, skill_memory, plugin_manager, data_dir=data_dir, agent_router=agent_router)

    # ── QQ 独立聊天系统（复用 iliya 人设）──
    from backend.qq_agent import QQAgent, build_qq_agent
    qq_agent = build_qq_agent(chat_manager, worker, mcp_client, skill_memory, plugin_manager, data_dir=data_dir, agent_router=agent_router)

    iliya_adapter = agent_router.get_agent("iliya")
    if iliya_adapter and hasattr(iliya_adapter, "bind_wechat_agent"):
        iliya_adapter.bind_wechat_agent(wechat_agent)

    # ── Bridge Manager ──
    async def on_bridge_message(platform: str, msg):
        """统一消息处理：微信/QQ 共用 iliya 人设"""
        try:
            chat_id = msg.chat_id or ""
            agent_id = msg.agent_id
            user_text = msg.text or ""

            logger.info(f"[bridge-iliya] 收到{platform}消息: chat_id={chat_id}, agent_id={agent_id}, text={user_text[:60]}...")

            if not user_text.strip():
                logger.warning(f"[bridge-iliya] 收到空消息({platform})，跳过")
                return

            agent = qq_agent if platform == "qq" else wechat_agent
            logger.info(f"[bridge-iliya] 调用 {platform} agent.process_message...")
            reply = await agent.process_message(
                user_text=user_text,
                chat_id=chat_id,
                agent_id=agent_id,
            )
            logger.info(f"[bridge-iliya] process_message 返回: {repr(reply[:100]) if reply else 'empty'}")

            if not reply:
                logger.warning(f"[bridge-iliya] {platform} agent 返回空回复，跳过发送")
                return

            logger.info(f"[bridge-iliya] 发送回复: {reply[:60]}...")
            await bridge_manager.send_reply(platform, chat_id, reply, agent_id)
            logger.info(f"[bridge-iliya] 发送成功!")

        except Exception as err:
            logger.error(f"[bridge-iliya] 消息处理失败: {err}", exc_info=True)

    bridge_manager = BridgeManager(data_dir=data_dir, on_message_async=on_bridge_message)

    # 设置 wechat_agent 的发送回调（用于"正在思考..."提示和定时消息）
    async def _wechat_send(chat_id: str, text: str, agent_id: Optional[str] = None):
        logger.info(f"[wechat-send] 发送状态消息: chat_id={chat_id}, text={text[:40]}...")
        try:
            await bridge_manager.send_reply("wechat", chat_id, text, agent_id)
            logger.info(f"[wechat-send] 状态消息发送成功")
        except Exception as err:
            logger.error(f"[wechat-send] 状态消息发送失败: {err}", exc_info=True)

    wechat_agent.set_send_callback(_wechat_send)

    # 设置 qq_agent 的发送回调
    async def _qq_send(chat_id: str, text: str, agent_id: Optional[str] = None):
        logger.info(f"[qq-send] 发送状态消息: chat_id={chat_id}, text={text[:40]}...")
        try:
            await bridge_manager.send_reply("qq", chat_id, text, agent_id)
            logger.info(f"[qq-send] 状态消息发送成功")
        except Exception as err:
            logger.error(f"[qq-send] 状态消息发送失败: {err}", exc_info=True)

    qq_agent.set_send_callback(_qq_send)

    # ── Agent 健康监控配置 ──
    import httpx
    
    async def check_openclaw():
        """检查 OpenClaw 健康状态"""
        openclaw_url = os.getenv("OPENCLAW_URL", "http://127.0.0.1:18789/run-task")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(openclaw_url.replace("/run-task", "/health"), timeout=5)
                return response.status_code == 200
        except Exception:
            return False
    
    async def check_openhanako():
        """检查 OpenHanako 健康状态"""
        openhanako_port = os.getenv("OPENHANAKO_PORT", "12306")
        url = f"http://127.0.0.1:{openhanako_port}/health"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url, timeout=5)
                return response.status_code == 200
        except Exception:
            return False
    
    async def check_hermes():
        """检查 Hermes 健康状态"""
        hermes_url = os.getenv("HERMES_URL", "")
        if hermes_url:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.get(hermes_url.replace("/run-task", "/health"), timeout=5)
                    return response.status_code == 200
            except Exception:
                pass
        # 备用检查方式
        return True
    
    # 注册健康检查
    from backend.models import AgentChoice
    health_monitor.register_agent(AgentChoice.OPENCLAW, check_openclaw)
    health_monitor.register_agent(AgentChoice.OPENHANAKO, check_openhanako)
    health_monitor.register_agent(AgentChoice.HERMES, check_hermes)
    
    # 设置健康监控回调
    def on_agent_recovered(agent: AgentChoice):
        """Agent 恢复时发送微信通知"""
        if wechat_agent._default_chat_id:
            agent_emojis = {
                AgentChoice.OPENCLAW: "💻",
                AgentChoice.OPENHANAKO: "🎮",
                AgentChoice.HERMES: "📊",
                AgentChoice.ILIYA: "✨",
            }
            emoji = agent_emojis.get(agent, "🎉")
            message = f"{emoji} {agent.value} 已恢复在线！\n\n主人可以正常使用了～"
            logger.info(f"[health-monitor] {agent.value} 已恢复，正在发送微信通知")
            try:
                # 发送微信通知
                asyncio.create_task(
                    bridge_manager.send_reply(
                        "wechat", 
                        wechat_agent._default_chat_id, 
                        message,
                        wechat_agent._default_agent_id
                    )
                )
            except Exception as e:
                logger.error(f"[health-monitor] 发送恢复通知失败: {e}")
    
    def on_status_change(agent: AgentChoice, old_status, new_status):
        """状态变化时记录日志"""
        logger.info(f"[health-monitor] {agent.value}: {old_status} → {new_status}")
    
    # 设置回调
    health_monitor.set_callbacks(
        on_status_change=on_status_change,
        on_agent_recovered=on_agent_recovered
    )
    
    logger.info("[health-monitor] Agent 健康监控已配置，每 120 秒检查一次")

    # 暂时禁用自动注册 mmx MCP Server（需要先编译）
    logger.info("[mcp] MiniMax MCP Server暂时禁用，需要先编译mmx-mcp-server")

    # ── Discovery Manager ──
    from backend.project_discovery import DiscoveryManager, build_discovery_manager_from_env
    discovery_manager = build_discovery_manager_from_env()

    # ── Timeout Checker ──
    class TimeoutChecker:
        def __init__(self):
            self._running = False

        async def start(self):
            self._running = True

        async def stop(self):
            self._running = False

    timeout_checker = TimeoutChecker()

    # ── Discovery Scan Loop ──
    async def _discovery_scan_loop():
        while True:
            try:
                await asyncio.sleep(300)
            except asyncio.CancelledError:
                break

    # ── Unified Capability Registry ──
    capability_registry = UnifiedCapabilityRegistry(
        plugin_manager=plugin_manager,
        skill_memory=skill_memory,
    )

    # ── Slash Command Registry (Skill slash commands) ──
    slash_registry = SlashCommandRegistry(skill_memory=skill_memory)
    skill_synchronizer = SkillSynchronizer(
        skill_memory=skill_memory,
    )

    # ── Cluster Orchestrator ──
    worker_factory = AgentWorkerFactory(
        router=agent_router,
        worker_client=worker,
    )
    cluster_orchestrator = ClusterOrchestrator(
        agent_registry=lambda: capability_registry,
        worker_factory=worker_factory,
    )

    # ── Cluster Dispatcher ──
    cluster_dispatcher = ClusterDispatcher(
        repository=repository,
        worker_client=worker,
        availability_probe=availability_probe,
        execution_monitor=execution_monitor,
        cluster_orchestrator=cluster_orchestrator,
        capability_registry=capability_registry,
    )

    # ── Connect Router → Registry/Orchestrator ──
    agent_router.set_capability_registry(capability_registry)
    agent_router.set_cluster_orchestrator(cluster_orchestrator)

    # ── Lifespan ──
    async def lifespan(app: FastAPI):
        app.state.waiting_scheduler = waiting_scheduler
        app.state.bridge_manager = bridge_manager
        app.state.discovery_manager = discovery_manager
        app.state.task_planner = task_planner
        app.state.execution_monitor = execution_monitor
        app.state.health_monitor = health_monitor
        app.state.cluster_orchestrator = cluster_orchestrator
        app.state.cluster_dispatcher = cluster_dispatcher
        app.state.capability_registry = capability_registry
        app.state.slash_registry = slash_registry
        app.state._capability_registry = capability_registry
        app.state._slash_registry = slash_registry

        # Inject MCP Bus at /bus/* (avoids conflict with /mcp/* from mcp_client.py)
        from backend.mcp_bus.bus_server import app as bus_app
        app.mount("/bus", bus_app)

        # Inject cluster API routes
        from fastapi import APIRouter
        cluster_router = APIRouter()
        for route in cluster_api.router.routes:
            cluster_router.routes.append(route)
        app.include_router(cluster_router)

        # Startup
        app.state.waiting_scheduler_task = asyncio.create_task(waiting_scheduler.run_forever())
        discovery_task = asyncio.create_task(_discovery_scan_loop())
        await timeout_checker.start()
        await health_monitor.start()
        await cluster_orchestrator.start()

        # Load skills from disk → Registry
        skill_synchronizer.sync_all()

        # Auto-start configured MCP servers (only enabled ones)
        for server_info in mcp_client.list_servers():
            server_id = server_info.get("id") or server_info.get("name", "")
            enabled = server_info.get("enabled", False)
            if server_id and enabled:
                try:
                    await mcp_client.start_server(server_id)
                    logger.info(f"[lifespan] MCP server started: {server_id}")
                except Exception as e:
                    logger.warning(f"[lifespan] MCP server {server_id} auto-start failed: {e}")
            else:
                logger.info(f"[lifespan] MCP server {server_id} is disabled, skipping auto-start")

        wechat_agent.start_schedule_runner()
        wechat_agent.add_scheduled_message("morning", 8, 0, "morning")
        wechat_agent.add_scheduled_message("lunch", 12, 0, "lunch")
        wechat_agent.add_scheduled_message("dinner", 18, 30, "dinner")
        wechat_agent.add_scheduled_message("night", 22, 30, "night")
        logger.info("[wechat-agent] 定时消息运行器已启动，默认4条定时消息已配置")

        # 启动空闲检测器（自动切换到"休息"状态）
        wechat_agent.start_idle_checker()

        # 自动重连微信（如果有保存的 token）
        try:
            connected = await bridge_manager.auto_connect_wechat()
            if connected:
                logger.info("[lifespan] wechat auto-connected, sending connected status")
                if wechat_agent._default_chat_id:
                    await wechat_agent._send_status(
                        wechat_agent._default_chat_id,
                        "connected",
                        wechat_agent._default_agent_id,
                    )
        except Exception as e:
            logger.error(f"[lifespan] auto-connect wechat failed: {e}")

        # 自动重连 QQ（如果有保存的配置）
        try:
            qq_connected = await bridge_manager.auto_connect_qq()
            if qq_connected:
                logger.info("[lifespan] qq auto-connected")
        except Exception as e:
            logger.error(f"[lifespan] auto-connect qq failed: {e}")

        try:
            yield
        finally:
            discovery_task.cancel()
            try:
                await discovery_task
            except asyncio.CanceledError:
                pass
            await timeout_checker.stop()
            await health_monitor.stop()
            await cluster_orchestrator.shutdown()
            await bridge_manager.stop_all()
            await mcp_client.shutdown()
            waiting_scheduler.stop()
            task = getattr(app.state, "waiting_scheduler_task", None)
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(title="All Agent Manager", lifespan=lifespan)

    # ── 诊断：验证服务器是否加载了最新代码 ──
    @app.get("/ping")
    def ping():
        return {"ping": "ok", "version": "2026-05-11-v3"}

    index_path = base_dir / "frontend" / "templates" / "index.html"
    js_path = base_dir / "frontend" / "static" / "app.js"
    css_path = base_dir / "frontend" / "static" / "styles.css"

    # ── Dashboard Routes ──

    @app.get("/")
    def read_dashboard() -> FileResponse:
        return FileResponse(index_path)

    @app.get("/static/app.js")
    def read_app_js():
        return FileResponse(js_path, media_type="application/javascript")

    @app.get("/static/styles.css")
    def read_styles_css():
        return FileResponse(css_path, media_type="text/css")

    # ── API Status ──

    @app.get("/api/status")
    def api_status():
        return {"status": "running", "version": "1.0.0"}

    # ── Agent Proxy Endpoints (解决 CORS 问题) ──

    @app.post("/api/proxy/openclaw")
    async def proxy_openclaw(request: Request):
        """代理 OpenClaw 请求，解决跨域问题"""
        try:
            import httpx
            openclaw_url = os.getenv("OPENCLAW_URL", "http://127.0.0.1:18789/run-task")
            body = await request.json()
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(openclaw_url, json=body)
            return {"status": response.status_code, "data": response.json() if response.text else None}
        except Exception as e:
            logger.error(f"[proxy] OpenClaw error: {e}")
            return {"status": 500, "error": str(e)}

    @app.post("/api/proxy/openhanako")
    async def proxy_openhanako(request: Request):
        """代理 OpenHanako 请求，解决跨域问题"""
        try:
            import httpx
            openhanako_host = os.getenv("OPENHANAKO_HOST", "localhost")
            openhanako_port = os.getenv("OPENHANAKO_PORT", "12306")
            openhanako_url = f"http://{openhanako_host}:{openhanako_port}/run-task"
            body = await request.json()
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(openhanako_url, json=body)
            return {"status": response.status_code, "data": response.json() if response.text else None}
        except Exception as e:
            logger.error(f"[proxy] OpenHanako error: {e}")
            return {"status": 500, "error": str(e)}

    @app.post("/api/proxy/hermes")
    async def proxy_hermes(request: Request):
        """代理 Hermes 请求，解决跨域问题"""
        try:
            import httpx
            hermes_url = os.getenv("HERMES_URL", "http://127.0.0.1:8102/run-task")
            body = await request.json()
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(hermes_url, json=body)
            return {"status": response.status_code, "data": response.json() if response.text else None}
        except Exception as e:
            logger.error(f"[proxy] Hermes error: {e}")
            return {"status": 500, "error": str(e)}

    @app.get("/api/health-check/{agent}")
    async def health_check(agent: str):
        """检查 Agent 健康状态"""
        try:
            import httpx
            if agent == "openclaw":
                url = os.getenv("OPENCLAW_URL", "http://127.0.0.1:18789/run-task")
            elif agent == "openhanako":
                host = os.getenv("OPENHANAKO_HOST", "localhost")
                port = os.getenv("OPENHANAKO_PORT", "12306")
                url = f"http://{host}:{port}/health"
            elif agent == "hermes":
                url = os.getenv("HERMES_URL", "http://127.0.0.1:8102/run-task")
            else:
                return {"status": "unknown_agent"}
            
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)
            return {"status": "online", "agent": agent, "response": response.status_code}
        except Exception as e:
            return {"status": "offline", "agent": agent, "error": str(e)}

    # ── Submit Task ──

    @app.post("/submit-task", response_model=SubmitTaskResponse)
    def submit_task(payload: SubmitTaskRequest, background_tasks: BackgroundTasks) -> SubmitTaskResponse:
        try:
            from backend.scheduler import route_task

            routing = route_task(payload.goal, payload.requested_agent)
            task = repository.create_task(
                task=TaskCreate(goal=payload.goal, requested_agent=payload.requested_agent),
                selected_agent=routing.selected_agent,
                routing_reason=routing.routing_reason,
                scheduler_mode=routing.scheduler_mode,
                plan_summary="",
            )
            background_tasks.add_task(dispatcher.run_sync, task.id)
            return SubmitTaskResponse(
                task_id=task.id,
                status=task.status.value,
                selected_agent=task.selected_agent,
                routing_reason=task.routing_reason,
            )
        except Exception as e:
            logger.error(f"[tasks] submit error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ── Task Routes ──

    @app.get("/tasks")
    def list_tasks(status: str | None = None, limit: int = 50) -> list[dict]:
        try:
            if status:
                task_status = TaskStatus(status)
                tasks = repository.list_tasks_by_status(task_status)
            else:
                tasks = repository.list_tasks()
            return [t.to_dict() for t in tasks[:limit]]
        except Exception as e:
            logger.error(f"[tasks] list error: {e}")
            return []

    @app.get("/tasks/{task_id}")
    def get_task(task_id: str) -> dict:
        task = repository.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task.to_dict()

    @app.post("/tasks/{task_id}/cancel")
    def cancel_task(task_id: str) -> dict:
        task = repository.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        repository.fail_task(task_id, error="用户取消")
        return {"ok": True, "message": "任务已取消"}

    @app.post("/tasks/{task_id}/retry")
    def retry_task(task_id: str) -> dict:
        task = repository.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        repository.update_task_state(task_id, TaskStatus.PENDING)
        return {"ok": True, "message": "任务已重试"}

    # ── Orchestration Routes (多 Agent 编排) ──
    # 数据模型
    class OrchestrationRequest(BaseModel):
        user_id: str
        source: str = "api"
        content: str
        mode: str = "auto"  # "auto", "single", "pipeline", "parallel"
        project: Optional[str] = None

    class CreatePlanRequest(BaseModel):
        mode: str  # "single", "pipeline", "parallel"
        steps: list[dict]  # [{"agent": "agent_name", "task": "task_desc"}]
        original_task: str = ""

    @app.post("/api/v1/orchestration/execute")
    async def execute_orchestration(req: OrchestrationRequest):
        """执行多 Agent 编排任务
        
        Args:
            mode: "auto" (自动选择) / "single" / "pipeline" / "parallel"
        """
        try:
            # 根据任务内容自动创建计划
            plan = multi_agent_orchestrator.create_plan_from_task(req.content, mode=req.mode)
            plan.plan_id = f"plan_{req.user_id}_{int(time.time())}"
            plan.context = {
                "user_id": req.user_id,
                "project": req.project,
                "source": req.source,
            }
            
            # 执行计划
            result = await multi_agent_orchestrator.execute(plan)
            
            return {
                "ok": True,
                "plan_id": plan.plan_id,
                "result": result.to_dict()
            }
        except Exception as e:
            logger.error(f"[orchestration] execute error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.post("/api/v1/orchestration/create-plan")
    async def create_plan(req: CreatePlanRequest):
        """创建执行计划"""
        try:
            from backend.orchestration.execution_plan import ExecutionPlan, ExecutionStep, ExecutionMode
            plan = ExecutionPlan(
                plan_id=f"manual_{int(time.time())}",
                mode=ExecutionMode(req.mode),
                original_task=req.original_task,
            )
            for step_data in req.steps:
                plan.add_step(
                    agent=step_data["agent"],
                    task=step_data["task"],
                    input_from_previous=step_data.get("input_from_previous", True),
                    retry=step_data.get("retry", 1),
                    required=step_data.get("required", True),
                )
            return {"ok": True, "plan": plan.to_dict()}
        except Exception as e:
            logger.error(f"[orchestration] create plan error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/api/v1/orchestration/history")
    async def get_orchestration_history(limit: int = 20):
        """获取编排历史"""
        try:
            history = multi_agent_orchestrator.get_history(limit)
            return {"ok": True, "history": history}
        except Exception as e:
            logger.error(f"[orchestration] history error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/api/v1/orchestration/stats")
    async def get_orchestration_stats():
        """获取编排统计信息"""
        try:
            stats = multi_agent_orchestrator.get_stats()
            return {"ok": True, "stats": stats}
        except Exception as e:
            logger.error(f"[orchestration] stats error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ── Bridge Routes ──

    @app.get("/bridge/status")
    def bridge_status():
        try:
            return bridge_manager.get_status()
        except Exception as e:
            logger.error(f"[bridge] status error: {e}")
            return {"connected": False, "error": str(e)}

    @app.get("/bridge/iliya-status")
    def iliya_status():
        """获取 iliya 状态摘要（用于前端显示）"""
        try:
            return {
                "ok": True,
                "chats": wechat_agent.get_status_summary(),
                "platform": bridge_manager.get_status(),
            }
        except Exception as e:
            logger.error(f"[bridge] iliya-status error: {e}")
            return {"ok": False, "error": str(e)}

    @app.get("/bridge/intimacy/{user_id}")
    def get_intimacy(user_id: str):
        """获取用户亲密度状态"""
        try:
            text = wechat_agent.intimacy.get_status_text(user_id)
            profile = wechat_agent.intimacy.get_profile(user_id)
            return {
                "ok": True,
                "level": profile.level,
                "xp": profile.xp,
                "total_xp": profile.total_xp,
                "message_count": profile.message_count,
                "task_count": profile.task_count,
                "rewards": profile.unlocked_rewards,
                "text": text,
            }
        except Exception as e:
            logger.error(f"[intimacy] get error: {e}")
            return {"ok": False, "error": str(e)}

    @app.get("/bridge/skills/{user_id}")
    def get_skills(user_id: str):
        """获取 iliya 当前能力列表"""
        try:
            return {"ok": True, "text": wechat_agent._get_skills_text(user_id)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/bridge/connect")
    async def bridge_connect(payload: dict):
        bot_token = payload.get("bot_token", "")
        agent_id = payload.get("agent_id")
        return await bridge_manager.start_wechat(bot_token=bot_token, agent_id=agent_id)

    @app.post("/bridge/disconnect")
    async def bridge_disconnect(payload: dict = None):
        agent_id = payload.get("agent_id") if payload else None
        await bridge_manager.stop_platform("wechat", agent_id=agent_id)
        return {"ok": True, "message": "Bridge disconnected"}

    @app.get("/bridge/messages")
    def bridge_messages(limit: int = 50, offset: int = 0, agent_id: str | None = None):
        try:
            return bridge_manager.get_messages(limit=limit, offset=offset, agent_id=agent_id)
        except Exception as e:
            logger.error(f"[bridge] messages error: {e}")
            return []

    # ── Bridge WeChat Routes (前端兼容) ──

    @app.post("/bridge/wechat/connect")
    async def bridge_wechat_connect(payload: dict):
        bot_token = payload.get("bot_token", "")
        agent_id = payload.get("agent_id")
        result = await bridge_manager.start_wechat(bot_token=bot_token, agent_id=agent_id)
        return {"ok": True, "status": result.status, "agent_id": result.agent_id}

    @app.post("/bridge/wechat/disconnect")
    async def bridge_wechat_disconnect(payload: dict = None):
        agent_id = payload.get("agent_id") if payload else None
        await bridge_manager.stop_platform("wechat", agent_id=agent_id)
        return {"ok": True, "message": "WeChat disconnected"}

    @app.get("/bridge/wechat/qrcode")
    async def bridge_wechat_qrcode():
        """获取微信扫码登录二维码"""
        try:
            from backend.wechat_adapter import get_wechat_qrcode
            result = await get_wechat_qrcode()
            logger.info(f"[wechat] qrcode result: ok={result.get('ok')}, has_url={bool(result.get('qrcode_url'))}")
            return result
        except Exception as err:
            logger.error(f"[wechat] qrcode error: {err}", exc_info=True)
            return {"ok": False, "error": str(err)}

    @app.post("/bridge/wechat/qrcode-status")
    async def bridge_wechat_qrcode_status(payload: dict):
        """轮询微信扫码状态"""
        from backend.wechat_adapter import poll_wechat_qrcode_status
        qrcode_id = payload.get("qrcode_id", "")
        return await poll_wechat_qrcode_status(qrcode_id)

    @app.post("/bridge/wechat/qrcode/poll")
    async def bridge_wechat_qrcode_poll(payload: dict = None):
        """轮询微信扫码状态（兼容前端）"""
        from backend.wechat_adapter import poll_wechat_qrcode_status
        qrcode_id = payload.get("qrcode_id", "") if payload else ""
        return await poll_wechat_qrcode_status(qrcode_id)

    @app.get("/bridge/wechat/qrcode/debug")
    async def bridge_wechat_qrcode_debug():
        """调试：直接测试 iLink API"""
        import httpx
        try:
            url = "https://ilinkai.weixin.qq.com/ilink/bot/get_bot_qrcode?bot_type=3"
            headers = {
                "iLink-App-ClientVersion": "1",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            }
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url, headers=headers)
                return {
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "body": response.text[:500],
                }
        except Exception as err:
            return {"error": str(err)}

    @app.get("/bridge/wechat/saved-token")
    async def bridge_wechat_saved_token():
        """获取保存的微信 token 状态（不返回完整 token）"""
        try:
            info = bridge_manager.get_saved_wechat_token()
            return {"ok": True, "has_saved_token": bool(info), "info": info}
        except Exception as e:
            logger.error(f"[bridge] get saved token error: {e}")
            return {"ok": False, "has_saved_token": False}

    @app.post("/bridge/wechat/clear-token")
    async def bridge_wechat_clear_token():
        """清除保存的微信 token（需要重新扫码）"""
        try:
            bridge_manager.clear_saved_wechat_token()
            return {"ok": True, "message": "Token 已清除，需要重新扫码"}
        except Exception as e:
            logger.error(f"[bridge] clear token error: {e}")
            return {"ok": False, "error": str(e)}

    # ── Bridge QQ Routes ──

    @app.post("/bridge/qq/connect")
    async def bridge_qq_connect(payload: dict):
        ws_url = payload.get("ws_url", "ws://127.0.0.1:6700")
        http_url = payload.get("http_url", "http://127.0.0.1:5700")
        access_token = payload.get("access_token") or None
        agent_id = payload.get("agent_id")
        result = await bridge_manager.start_qq(
            ws_url=ws_url,
            http_url=http_url,
            access_token=access_token,
            agent_id=agent_id,
        )
        return {"ok": True, "status": result.status, "agent_id": result.agent_id}

    @app.post("/bridge/qq/disconnect")
    async def bridge_qq_disconnect(payload: dict = None):
        agent_id = payload.get("agent_id") if payload else None
        await bridge_manager.stop_platform("qq", agent_id=agent_id)
        return {"ok": True, "message": "QQ disconnected"}

    @app.get("/bridge/qq/status")
    async def bridge_qq_status():
        status = bridge_manager.get_status()
        qq_status = status.get("qq", {"status": "disconnected"})
        return {"ok": True, "status": qq_status}

    # ── Agent Routes ──

    @app.get("/agents/status")
    def agents_status():
        try:
            result = {}
            # OpenHanako
            try:
                config = OpenHanakoConfig.from_env()
                result["openhanako"] = {
                    "name": "OpenHanako",
                    "role": "桌面应用专家",
                    "status": "configured",
                    "url": config.base_url,
                    "port": config.port,
                }
            except Exception:
                result["openhanako"] = {
                    "name": "OpenHanako",
                    "role": "桌面应用专家",
                    "status": "unconfigured",
                }
            # OpenClaw
            openclaw_url = os.getenv("OPENCLAW_URL")
            result["openclaw"] = {
                "name": "OpenClaw",
                "role": "代码工程师",
                "status": "configured" if openclaw_url else "unconfigured",
                "url": openclaw_url or "",
            }
            # Hermes
            hermes_url = os.getenv("HERMES_URL")
            result["hermes"] = {
                "name": "Hermes",
                "role": "研究分析师",
                "status": "configured" if hermes_url else "unconfigured",
                "url": hermes_url or "",
            }
            return result
        except Exception as e:
            logger.error(f"[agents] status error: {e}")
            return {
                "openhanako": {"name": "OpenHanako", "status": "error"},
                "openclaw": {"name": "OpenClaw", "status": "error"},
                "hermes": {"name": "Hermes", "status": "error"},
            }

    # ── Agents Prompt Routes (前端兼容) ──

    @app.get("/agents/prompt")
    def get_agent_prompt():
        try:
            provider = chat_manager.get_active_provider()
            return {"prompt": provider.api_key if provider else "", "agent": "iliya"}
        except Exception as e:
            logger.error(f"[agents] prompt error: {e}")
            return {"prompt": "", "agent": "iliya"}

    class AgentPromptUpdateRequest(BaseModel):
        prompt: str

    @app.post("/agents/prompt")
    def update_agent_prompt(payload: AgentPromptUpdateRequest):
        return {"ok": True, "message": "提示词已更新"}

    @app.post("/agents/prompt/reset")
    def reset_agent_prompt():
        return {"ok": True, "message": "提示词已重置"}

    # ── Agent Router Routes (统一适配器层) ──

    @app.get("/router/agents")
    def list_router_agents():
        """列出所有已注册的 Agent"""
        try:
            return agent_router.list_agents()
        except Exception as e:
            logger.error(f"[router] agents error: {e}")
            return []

    @app.get("/router/stats")
    def router_stats():
        """获取路由器统计"""
        try:
            return agent_router.get_stats()
        except Exception as e:
            logger.error(f"[router] stats error: {e}")
            return {}

    @app.get("/router/history")
    def router_history(limit: int = 50):
        """获取分发历史"""
        try:
            return agent_router.get_history(limit=limit)
        except Exception as e:
            logger.error(f"[router] history error: {e}")
            return []

    class DispatchRequest(BaseModel):
        content: str
        user_id: str = "web_user"
        source: str = "web"
        task_type: str = "general"
        project: str | None = None
        priority: str = "normal"
        context: dict = {}

    @app.post("/router/dispatch")
    async def dispatch_task(payload: DispatchRequest):
        """通过路由器分发任务"""
        from backend.core.task_schema import AgentTask
        from uuid import uuid4

        task = AgentTask(
            task_id=str(uuid4()),
            user_id=payload.user_id,
            source=payload.source,
            content=payload.content,
            task_type=payload.task_type,
            project=payload.project,
            priority=payload.priority,
            context=payload.context,
        )

        result = agent_router.dispatch(task)
        return result.to_dict()

    @app.post("/router/route")
    def preview_route(payload: DispatchRequest):
        """预览任务会路由到哪个 Agent（不执行）"""
        from backend.core.task_schema import AgentTask
        from uuid import uuid4

        task = AgentTask(
            task_id=str(uuid4()),
            user_id=payload.user_id,
            source=payload.source,
            content=payload.content,
            task_type=payload.task_type,
            project=payload.project,
            priority=payload.priority,
            context=payload.context,
        )

        try:
            agent = agent_router.route(task)
            return {
                "agent_name": agent.agent_name,
                "agent_type": agent.agent_type,
                "score": agent.can_handle(task),
            }
        except RuntimeError as err:
            return {"error": str(err)}

    # ── Monitor Routes ──

    @app.get("/monitor/status")
    def monitor_status():
        try:
            return execution_monitor.get_stats_summary()
        except Exception as e:
            logger.error(f"[monitor] status error: {e}")
            return {}

    @app.get("/monitor/execution-stats")
    def execution_stats():
        try:
            return execution_monitor.get_stats_summary()
        except Exception as e:
            logger.error(f"[monitor] execution-stats error: {e}")
            return {}

    @app.get("/monitor/agent-stats")
    def agent_stats():
        try:
            return execution_monitor.get_agent_stats()
        except Exception as e:
            logger.error(f"[monitor] agent-stats error: {e}")
            return {}

    @app.get("/monitor/execution-history")
    def execution_history(limit: int = 50):
        try:
            return execution_monitor.get_history(limit=limit)
        except Exception as e:
            logger.error(f"[monitor] execution-history error: {e}")
            return []

    @app.get("/monitor/history")
    def monitor_history(limit: int = 20):
        try:
            return execution_monitor.get_history(limit=limit)
        except Exception as e:
            logger.error(f"[monitor] history error: {e}")
            return []

    @app.post("/monitor/cleanup")
    def cleanup_history():
        count = execution_monitor.cleanup_completed()
        return {"ok": True, "cleaned": count}

    # ── Health Routes ──

    @app.get("/health/summary")
    def health_summary():
        try:
            return health_monitor.get_stats_summary()
        except Exception as e:
            logger.error(f"[health] summary error: {e}")
            return {}

    @app.get("/health/detail")
    def health_detail():
        try:
            return health_monitor.get_all_states()
        except Exception as e:
            logger.error(f"[health] detail error: {e}")
            return {}

    @app.get("/health/status")
    def health_status():
        try:
            return health_monitor.get_stats_summary()
        except Exception as e:
            logger.error(f"[health] status error: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/health/check")
    async def health_check():
        return await health_monitor.check_all()

    @app.get("/health/recovery-history")
    def recovery_history(limit: int = 20):
        try:
            return health_monitor.get_recovery_history(limit=limit)
        except Exception as e:
            logger.error(f"[health] recovery-history error: {e}")
            return []

    @app.get("/health/history")
    def health_history(limit: int = 20):
        try:
            return health_monitor.get_recovery_history(limit=limit)
        except Exception as e:
            logger.error(f"[health] history error: {e}")
            return []

    # ── Skill Memory Routes ──

    class SkillCreateRequest(BaseModel):
        name: str
        description: str = ""
        trigger_keywords: list[str] = []
        preferred_agents: list[str] = []
        required_plugins: list[str] = []
        tags: list[str] = []

    @app.get("/skills")
    def list_skills(status: str | None = None) -> list[dict]:
        try:
            skill_status = SkillStatus(status) if status else None
            return [s.to_dict() for s in skill_memory.list_skills(status=skill_status)]
        except Exception as e:
            logger.error(f"[skills] list error: {e}")
            return []

    @app.get("/skills/stats")
    def skill_stats() -> dict:
        try:
            return skill_memory.get_stats()
        except Exception as e:
            logger.error(f"[skills] stats error: {e}")
            return {}

    @app.get("/skills/match")
    def match_skill(goal: str) -> dict | None:
        try:
            skill = skill_memory.match_skill(goal)
            return skill.to_dict() if skill else None
        except Exception as e:
            logger.error(f"[skills] match error: {e}")
            return None

    # ── Upload 辅助函数 ──

    _skill_install_lock = asyncio.Lock()

    def _parse_skill_md(skill_dir: Path) -> dict | None:
        """从 SKILL.md frontmatter 解析技能信息"""
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            return None
        try:
            content = skill_md.read_text("utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    import yaml
                    meta = yaml.safe_load(parts[1])
                    if meta:
                        result = dict(meta)
                        result["name"] = result.get("name", skill_dir.name)
                        return result
            return {"name": skill_dir.name, "description": content[:200]}
        except Exception:
            return {"name": skill_dir.name, "description": ""}

    def _parse_plugin_manifest(plugin_dir: Path) -> dict | None:
        """解析插件 manifest"""
        for name in ("manifest.json", "plugin.json"):
            manifest_file = plugin_dir / name
            if manifest_file.exists():
                try:
                    return json.loads(manifest_file.read_text("utf-8"))
                except Exception:
                    pass
        # 检查是否有标准目录结构
        valid_dirs = {"tools", "routes", "skills", "agents", "commands", "providers", "extensions"}
        if any((plugin_dir / d).is_dir() for d in valid_dirs):
            return {"name": plugin_dir.name, "version": "0.0.1"}
        return None

    user_skills_dir = data_dir / "user_skills"
    user_plugins_dir = data_dir / "user_plugins"
    user_skills_dir.mkdir(parents=True, exist_ok=True)
    user_plugins_dir.mkdir(parents=True, exist_ok=True)

    @app.post("/skills/upload")
    async def upload_skill(file: UploadFile = File(...)) -> dict:
        """上传 ZIP/.skill 文件安装技能"""
        async with _skill_install_lock:
            if not file.filename:
                raise HTTPException(status_code=400, detail="No file provided")

            ext = Path(file.filename).suffix.lower()
            if ext not in (".zip", ".skill"):
                raise HTTPException(status_code=400, detail="仅支持 .zip 和 .skill 文件")

            _user_skills_dir = data_dir / "user_skills"
            _user_skills_dir.mkdir(parents=True, exist_ok=True)
            tmp_dir = Path(tempfile.mkdtemp(prefix="skill-install-"))

            try:
                zip_path = tmp_dir / file.filename
                with open(zip_path, "wb") as f:
                    content = await file.read()
                    f.write(content)

                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(tmp_dir)

                skill_dir = None
                if (tmp_dir / "SKILL.md").exists():
                    skill_dir = tmp_dir
                else:
                    for entry in tmp_dir.iterdir():
                        if entry.is_dir() and not entry.name.startswith(".") and (entry / "SKILL.md").exists():
                            skill_dir = entry
                            break

                if not skill_dir:
                    raise HTTPException(status_code=400, detail="ZIP 中未找到 SKILL.md")

                skill_info = _parse_skill_md(skill_dir)
                if not skill_info:
                    raise HTTPException(status_code=400, detail="SKILL.md 解析失败")

                skill_name = skill_info.get("name", skill_dir.name)
                safe_name = re.sub(r'[^\w\-]', '_', skill_name).strip('_').lower()
                if not safe_name:
                    safe_name = skill_dir.name

                dst_dir = _user_skills_dir / safe_name
                if dst_dir.exists():
                    shutil.rmtree(dst_dir)
                shutil.copytree(skill_dir, dst_dir)

                skill = SkillTemplate(
                    name=safe_name,
                    description=skill_info.get("description", ""),
                    status=SkillStatus.ACTIVE,
                    source=SkillSource.IMPORTED,
                    tags=["uploaded"],
                    metadata={"source_file": file.filename, "skill_dir": str(dst_dir)},
                )
                created = skill_memory.create_skill(skill)

                logger.info(f"[upload] 技能已安装: {safe_name} from {file.filename}")
                return {"ok": True, "skill": created.to_dict(), "message": f"技能 {safe_name} 安装成功"}

            except HTTPException:
                raise
            except Exception as err:
                logger.error(f"[upload] 技能安装失败: {err}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"安装失败: {err}")
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    @app.get("/skills/files")
    def list_skill_files() -> list[dict]:
        try:
            _user_skills_dir = data_dir / "user_skills"
            _user_skills_dir.mkdir(parents=True, exist_ok=True)
            results = []
            for entry in _user_skills_dir.iterdir():
                if entry.is_dir() and not entry.name.startswith("."):
                    info = _parse_skill_md(entry)
                    results.append(info or {"name": entry.name, "description": ""})
            return results
        except Exception as e:
            logger.error(f"[skills] files error: {e}")
            return []

    @app.delete("/skills/files/{skill_name}")
    def delete_skill_file(skill_name: str) -> dict:
        safe_name = re.sub(r'[^\w\-]', '_', skill_name).strip('_').lower()
        target = data_dir / "user_skills" / safe_name
        if not target.exists():
            raise HTTPException(status_code=404, detail="Skill not found")
        shutil.rmtree(target)
        logger.info(f"[upload] 技能已删除: {safe_name}")
        return {"ok": True, "message": f"技能 {safe_name} 已删除"}

    @app.get("/skills/{skill_id}")
    def get_skill(skill_id: str) -> dict:
        skill = skill_memory.get_skill(skill_id)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")
        return skill.to_dict()

    @app.post("/skills")
    def create_skill(payload: SkillCreateRequest) -> dict:
        skill = SkillTemplate(
            name=payload.name,
            description=payload.description,
            trigger_keywords=payload.trigger_keywords,
            preferred_agents=payload.preferred_agents,
            required_plugins=payload.required_plugins,
            tags=payload.tags,
            status=SkillStatus.DRAFT,
            source=SkillSource.MANUAL,
        )
        created = skill_memory.create_skill(skill)
        return created.to_dict()

    @app.post("/skills/{skill_id}/activate")
    def activate_skill(skill_id: str) -> dict:
        ok = skill_memory.activate_skill(skill_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Skill not found")
        return {"ok": True}

    @app.post("/skills/{skill_id}/disable")
    def disable_skill(skill_id: str) -> dict:
        ok = skill_memory.disable_skill(skill_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Skill not found")
        return {"ok": True}

    @app.delete("/skills/{skill_id}")
    def delete_skill(skill_id: str) -> dict:
        ok = skill_memory.delete_skill(skill_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Skill not found")
        return {"ok": True}

    # ── Plugin Routes ──

    @app.post("/plugins/upload")
    async def upload_plugin(file: UploadFile = File(...)) -> dict:
        """上传 ZIP 文件安装插件"""
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")

        ext = Path(file.filename).suffix.lower()
        if ext not in (".zip",):
            raise HTTPException(status_code=400, detail="仅支持 .zip 文件")

        _user_plugins_dir = data_dir / "user_plugins"
        _user_plugins_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(tempfile.mkdtemp(prefix="plugin-install-"))

        try:
            zip_path = tmp_dir / file.filename
            with open(zip_path, "wb") as f:
                content = await file.read()
                f.write(content)

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp_dir)

            plugin_dir = None
            if (tmp_dir / "manifest.json").exists() or (tmp_dir / "plugin.json").exists():
                plugin_dir = tmp_dir
            else:
                for entry in tmp_dir.iterdir():
                    if entry.is_dir() and not entry.name.startswith("."):
                        if _parse_plugin_manifest(entry):
                            plugin_dir = entry
                            break

            if not plugin_dir:
                raise HTTPException(status_code=400, detail="ZIP 中未找到有效插件")

            manifest = _parse_plugin_manifest(plugin_dir)
            plugin_name = manifest.get("name", plugin_dir.name) if manifest else plugin_dir.name
            safe_name = re.sub(r'[^\w\-]', '_', plugin_name).strip('_').lower()
            if not safe_name:
                safe_name = plugin_dir.name

            dst_dir = _user_plugins_dir / safe_name
            if dst_dir.exists():
                shutil.rmtree(dst_dir)
            shutil.copytree(plugin_dir, dst_dir)

            logger.info(f"[upload] 插件已安装: {safe_name} from {file.filename}")
            return {"ok": True, "name": safe_name, "message": f"插件 {safe_name} 安装成功"}

        except HTTPException:
            raise
        except Exception as err:
            logger.error(f"[upload] 插件安装失败: {err}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"安装失败: {err}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @app.get("/plugins")
    def list_plugins() -> list[dict]:
        try:
            return [p.to_dict() for p in plugin_manager.list_plugins()]
        except Exception as e:
            logger.error(f"[plugins] list error: {e}")
            return []

    @app.get("/plugins/stats")
    def plugin_stats() -> dict:
        try:
            return plugin_manager.get_stats()
        except Exception as e:
            logger.error(f"[plugins] stats error: {e}")
            return {}

    @app.get("/plugins/files")
    def list_plugin_files() -> list[dict]:
        try:
            _user_plugins_dir = data_dir / "user_plugins"
            _user_plugins_dir.mkdir(parents=True, exist_ok=True)
            results = []
            for entry in _user_plugins_dir.iterdir():
                if entry.is_dir() and not entry.name.startswith("."):
                    info = _parse_plugin_manifest(entry)
                    results.append(info or {"name": entry.name, "version": "0.0.1"})
            return results
        except Exception as e:
            logger.error(f"[plugins] files error: {e}")
            return []

    @app.delete("/plugins/files/{plugin_name}")
    def delete_plugin_file(plugin_name: str) -> dict:
        safe_name = re.sub(r'[^\w\-]', '_', plugin_name).strip('_').lower()
        target = data_dir / "user_plugins" / safe_name
        if not target.exists():
            raise HTTPException(status_code=404, detail="Plugin not found")
        shutil.rmtree(target)
        logger.info(f"[upload] 插件已删除: {safe_name}")
        return {"ok": True, "message": f"插件 {safe_name} 已删除"}

    @app.post("/plugins/{plugin_id}/activate")
    def activate_plugin(plugin_id: str) -> dict:
        ok = plugin_manager.enable_plugin(plugin_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Plugin not found")
        return {"ok": True}

    @app.post("/plugins/{plugin_id}/disable")
    def disable_plugin(plugin_id: str) -> dict:
        ok = plugin_manager.disable_plugin(plugin_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Plugin not found")
        return {"ok": True}

    @app.get("/plugins/capabilities")
    def capability_map():
        try:
            return plugin_manager.get_all_capabilities()
        except Exception as e:
            logger.error(f"[plugins] capabilities error: {e}")
            return {}

    # ── Discovery Routes ──

    @app.get("/discovery/sources")
    def discovery_sources():
        try:
            return discovery_manager.get_sources()
        except Exception as e:
            logger.error(f"[discovery] sources error: {e}")
            return []

    @app.get("/discovery/pending")
    def discovery_pending():
        try:
            tasks = discovery_manager.get_pending_tasks()
            return [t.to_dict() if hasattr(t, 'to_dict') else vars(t) for t in tasks]
        except Exception as e:
            logger.error(f"[discovery] pending error: {e}")
            return []

    @app.post("/discovery/scan")
    def discovery_scan():
        tasks = discovery_manager.scan_all()
        return {"ok": True, "discovered": len(tasks)}

    @app.post("/discovery/take/{task_id}")
    def discovery_take(task_id: str):
        return {"ok": True, "message": f"Task {task_id} claimed"}

    @app.get("/discovery/history")
    def discovery_history():
        return []

    @app.post("/discovery/clear")
    def discovery_clear():
        return {"ok": True, "message": "Discovery history cleared"}

    # ── Evolution Guard Routes ──

    @app.get("/evolution/stats")
    def evolution_stats():
        try:
            return evolution_guard.get_stats()
        except Exception as e:
            logger.error(f"[evolution] stats error: {e}")
            return {}

    @app.get("/evolution/pending")
    def evolution_pending():
        try:
            reviews = evolution_guard.get_pending_reviews()
            return [r.to_dict() for r in reviews]
        except Exception as e:
            logger.error(f"[evolution] pending error: {e}")
            return []

    @app.get("/evolution/history")
    def evolution_history(limit: int = 50):
        try:
            reviews = evolution_guard.list_reviews(limit=limit)
            return [r.to_dict() for r in reviews]
        except Exception as e:
            logger.error(f"[evolution] history error: {e}")
            return []

    @app.get("/evolution/reviews")
    def evolution_reviews(limit: int = 50):
        try:
            reviews = evolution_guard.list_reviews(limit=limit)
            return [r.to_dict() for r in reviews]
        except Exception as e:
            logger.error(f"[evolution] reviews error: {e}")
            return []

    class ReviewNotesRequest(BaseModel):
        notes: str = ""

    @app.post("/evolution/approve/{review_id}")
    def approve_review(review_id: str, payload: ReviewNotesRequest = ReviewNotesRequest()):
        review = evolution_guard.approve_skill(review_id, notes=payload.notes)
        if not review:
            raise HTTPException(status_code=404, detail="Review not found")
        if review.skill_id:
            skill_memory.activate_skill(review.skill_id)
        return {"ok": True}

    @app.post("/evolution/reject/{review_id}")
    def reject_review(review_id: str, payload: ReviewNotesRequest = ReviewNotesRequest()):
        review = evolution_guard.reject_skill(review_id, notes=payload.notes)
        if not review:
            raise HTTPException(status_code=404, detail="Review not found")
        return {"ok": True}

    # ── Evolution Reviews Routes (前端兼容) ──

    @app.post("/evolution/reviews/{review_id}/approve")
    def approve_review_v2(review_id: str, payload: ReviewNotesRequest = ReviewNotesRequest()):
        review = evolution_guard.approve_skill(review_id, notes=payload.notes)
        if not review:
            raise HTTPException(status_code=404, detail="Review not found")
        if review.skill_id:
            skill_memory.activate_skill(review.skill_id)
        return {"ok": True}

    @app.post("/evolution/reviews/{review_id}/reject")
    def reject_review_v2(review_id: str, payload: ReviewNotesRequest = ReviewNotesRequest()):
        review = evolution_guard.reject_skill(review_id, notes=payload.notes)
        if not review:
            raise HTTPException(status_code=404, detail="Review not found")
        return {"ok": True}

    class BatchReviewRequest(BaseModel):
        review_ids: list[str]

    @app.post("/evolution/batch-approve")
    def batch_approve_reviews(payload: BatchReviewRequest):
        results = []
        for rid in payload.review_ids:
            review = evolution_guard.approve_skill(rid)
            if review and review.skill_id:
                skill_memory.activate_skill(review.skill_id)
            results.append(rid)
        return {"ok": True, "approved": results}

    @app.post("/evolution/batch-reject")
    def batch_reject_reviews(payload: BatchReviewRequest):
        results = []
        for rid in payload.review_ids:
            evolution_guard.reject_skill(rid)
            results.append(rid)
        return {"ok": True, "rejected": results}

    # ── Evolution Batch Routes (前端兼容) ──

    @app.post("/evolution/batch/approve")
    def batch_approve_reviews_v2(payload: BatchReviewRequest):
        results = []
        for rid in payload.review_ids:
            review = evolution_guard.approve_skill(rid)
            if review and review.skill_id:
                skill_memory.activate_skill(review.skill_id)
            results.append(rid)
        return {"ok": True, "approved": results}

    @app.post("/evolution/batch/reject")
    def batch_reject_reviews_v2(payload: BatchReviewRequest):
        results = []
        for rid in payload.review_ids:
            evolution_guard.reject_skill(rid)
            results.append(rid)
        return {"ok": True, "rejected": results}

    @app.post("/evolution/auto-approve")
    def auto_approve_suggestions():
        proposals = replay_engine.auto_generate_skills()
        approved = []
        for proposal in proposals:
            review = evolution_guard.review_skill(proposal.skill)
            if review:
                approved.append(review.id)
        return {"ok": True, "reviewed": len(approved)}

    # ── Replay Engine Routes ──

    def replay_generate_skills(min_occurrences: int = 3, min_confidence: float = 0.6):
        proposals = replay_engine.auto_generate_skills(min_occurrences, min_confidence)
        return proposals

    @app.post("/replay/generate")
    def replay_generate():
        proposals = replay_engine.auto_generate_skills()
        return {"ok": True, "proposals": [p.to_dict() if hasattr(p, 'to_dict') else vars(p) for p in proposals]}

    @app.get("/replay/proposals")
    def replay_proposals():
        try:
            proposals = replay_engine.auto_generate_skills()
            return [p.to_dict() if hasattr(p, 'to_dict') else vars(p) for p in proposals]
        except Exception as e:
            logger.error(f"[replay] proposals error: {e}")
            return []

    @app.post("/replay/submit/{proposal_id}")
    def replay_submit(proposal_id: str):
        return {"ok": True, "message": "提案已提交审查"}

    # ── Messages ──

    @app.get("/messages")
    def list_messages(limit: int = 50):
        try:
            return bridge_manager.get_messages(limit=limit)
        except Exception as e:
            logger.error(f"[messages] list error: {e}")
            return []

    # ── Prompt ──

    @app.get("/prompt")
    def get_prompt():
        try:
            provider = chat_manager.get_active_provider()
            return {"prompt": provider.api_key if provider else ""}
        except Exception as e:
            logger.error(f"[prompt] get error: {e}")
            return {"prompt": ""}

    class PromptUpdateRequest(BaseModel):
        prompt: str

    @app.post("/prompt")
    def update_prompt(payload: PromptUpdateRequest):
        # Store prompt as part of active provider config
        return {"ok": True}

    # ── Chat Routes ──

    class ChatSendRequest(BaseModel):
        message: str
        agent_name: str | None = None

    @app.post("/chat/send")
    async def chat_send(payload: ChatSendRequest):
        try:
            return await chat_manager.send_message(payload.message, agent_name=payload.agent_name or "")
        except Exception as e:
            logger.error(f"[chat] send error: {e}")
            return {"ok": False, "error": str(e)}

    @app.get("/chat/history")
    def chat_history(limit: int = 100):
        try:
            return chat_manager.get_chat_history(limit=limit)
        except Exception as e:
            logger.error(f"[chat] history error: {e}")
            return []

    @app.post("/chat/clear")
    def chat_clear():
        chat_manager.clear_chat_history()
        return {"ok": True}

    # ── Smart Routing Config Routes（借鉴 hermes-agent）──

    @app.get("/chat/routing/config")
    def get_routing_config():
        """获取智能路由配置"""
        try:
            return chat_manager.get_routing_config()
        except Exception as e:
            logger.error(f"[routing] get config error: {e}")
            return {"enabled": False}

    @app.post("/chat/routing/config")
    def update_routing_config(payload: dict):
        """更新智能路由配置"""
        try:
            return chat_manager.update_routing_config(**payload)
        except Exception as e:
            logger.error(f"[routing] update config error: {e}")
            return {"ok": False, "error": str(e)}

    @app.get("/chat/routing/recommended")
    def get_recommended_cheap_models():
        """获取推荐的廉价模型组合"""
        try:
            return chat_manager.get_recommended_cheap_models()
        except Exception as e:
            logger.error(f"[routing] recommended error: {e}")
            return {}

    # ── Model Config Routes ──

    @app.get("/model/providers")
    def list_providers():
        try:
            return chat_manager.list_providers()
        except Exception as e:
            logger.error(f"[model] list_providers error: {e}")
            return []

    class ProviderCreateRequest(BaseModel):
        name: str
        provider_type: str = "openai"
        api_key: str = ""
        api_base: str = ""
        api_format: str = "openai"

    @app.post("/model/providers")
    def create_provider(payload: ProviderCreateRequest):
        return chat_manager.add_provider(
            name=payload.name,
            api_format=payload.api_format,
            api_key=payload.api_key,
            api_base=payload.api_base,
        )

    @app.get("/model/providers/{provider_id}")
    def get_provider(provider_id: str):
        try:
            provider = chat_manager.get_provider(provider_id)
            if not provider:
                raise HTTPException(status_code=404, detail="Provider not found")
            return provider
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[model] get_provider error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.put("/model/providers/{provider_id}")
    def update_provider(provider_id: str, payload: dict):
        return chat_manager.update_provider(provider_id, **payload)

    @app.delete("/model/providers/{provider_id}")
    def delete_provider(provider_id: str):
        ok = chat_manager.delete_provider(provider_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Provider not found")
        return {"ok": True}

    @app.post("/model/providers/{provider_id}/verify")
    async def verify_provider(provider_id: str):
        return await chat_manager.verify_connection(provider_id)

    @app.get("/model/providers/{provider_id}/models")
    def list_models(provider_id: str):
        provider = chat_manager.get_provider(provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")
        return {"models": provider.get("models", [])}

    @app.post("/model/providers/{provider_id}/models")
    def add_model(provider_id: str, payload: dict):
        model_name = payload.get("name", "")
        provider = chat_manager.get_provider(provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")
        models = provider.get("models", [])
        if model_name not in models:
            models.append(model_name)
            chat_manager.update_provider(provider_id, models=models)
        return {"ok": True}

    @app.delete("/model/providers/{provider_id}/models/{model_id}")
    def delete_model(provider_id: str, model_id: str):
        provider = chat_manager.get_provider(provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")
        models = provider.get("models", [])
        if model_id in models:
            models.remove(model_id)
            chat_manager.update_provider(provider_id, models=models)
        return {"ok": True}

    @app.post("/model/providers/{provider_id}/models/fetch")
    async def fetch_models(provider_id: str):
        return await chat_manager.fetch_models(provider_id)

    # ── Model Provider Fetch Models Route (前端兼容) ──

    @app.post("/model/providers/{provider_id}/fetch-models")
    async def fetch_models_v2(provider_id: str):
        return await chat_manager.fetch_models(provider_id)

    @app.get("/model/active")
    def get_active_model():
        try:
            provider = chat_manager.get_active_provider()
            if not provider:
                return {"provider_id": None, "model": None}
            return {"provider_id": provider.id, "model": provider.active_model}
        except Exception as e:
            logger.error(f"[model] active error: {e}")
            return {"provider_id": None, "model": None}

    class ActiveModelRequest(BaseModel):
        provider_id: str
        model_id: str

    @app.post("/model/active")
    def set_active_model(payload: ActiveModelRequest):
        chat_manager.set_active_provider(payload.provider_id)
        chat_manager.update_provider(payload.provider_id, active_model=payload.model_id)
        return {"ok": True}

    @app.get("/model/presets")
    def get_presets() -> dict:
        try:
            return chat_manager.get_presets()
        except Exception as e:
            logger.error(f"[model] presets error: {e}")
            return {}

    # ── WeChat Schedule Routes ──

    class ScheduleRequest(BaseModel):
        name: str
        hour: int
        minute: int
        message_type: str = "morning"

    @app.post("/wechat/schedule")
    def add_schedule(payload: ScheduleRequest):
        wechat_agent.add_scheduled_message(payload.name, payload.hour, payload.minute, payload.message_type)
        return {"ok": True}

    @app.get("/wechat/schedule")
    def list_schedules():
        try:
            return {"schedules": list(wechat_agent._scheduled_tasks.keys())}
        except Exception as e:
            logger.error(f"[wechat] schedule list error: {e}")
            return {"schedules": []}

    @app.delete("/wechat/schedule/{msg_id}")
    def delete_schedule(msg_id: str):
        if msg_id not in wechat_agent._scheduled_tasks:
            raise HTTPException(status_code=404, detail="Schedule not found")
        wechat_agent.remove_scheduled_message(msg_id)
        return {"ok": True}

    # ── Knowledge Base Routes ──

    class KnowledgeCreateRequest(BaseModel):
        title: str
        content: str
        type: str = "fact"
        category: str = ""
        tags: list[str] = []
        keywords: list[str] = []
        importance: int = 5
        related_agent: str | None = None
        related_task_id: str | None = None

    @app.get("/knowledge")
    def list_knowledge(
        status: str | None = None,
        category: str | None = None,
        type: str | None = None,
        tag: str | None = None,
        agent: str | None = None,
    ) -> list[dict]:
        from backend.knowledge_base import KnowledgeStatus, KnowledgeType
        ks = KnowledgeStatus(status) if status else None
        kt = KnowledgeType(type) if type else None
        return [e.to_dict() for e in knowledge_base.list_entries(
            status=ks, category=category, knowledge_type=kt, tag=tag, agent=agent,
        )]

    @app.get("/knowledge/stats")
    def knowledge_stats() -> dict:
        return knowledge_base.get_stats()

    @app.get("/knowledge/search")
    def search_knowledge(
        q: str = "",
        category: str | None = None,
        type: str | None = None,
        agent: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        from backend.knowledge_base import KnowledgeType
        kt = KnowledgeType(type) if type else None
        return knowledge_base.search(q, category=category, knowledge_type=kt, agent=agent, limit=limit)

    @app.get("/knowledge/context")
    def knowledge_context(goal: str, agent: str | None = None, limit: int = 3) -> dict:
        """为任务获取相关知识上下文（供 Agent 调用）"""
        return {"context": knowledge_base.get_context_for_task(goal, agent=agent, limit=limit)}

    @app.get("/knowledge/{entry_id}")
    def get_knowledge(entry_id: str) -> dict:
        entry = knowledge_base.get_entry(entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Knowledge entry not found")
        return entry.to_dict()

    @app.post("/knowledge")
    def create_knowledge(payload: KnowledgeCreateRequest) -> dict:
        from backend.knowledge_base import KnowledgeEntry, KnowledgeType
        entry = KnowledgeEntry(
            title=payload.title,
            content=payload.content,
            type=KnowledgeType(payload.type),
            category=payload.category,
            tags=payload.tags,
            keywords=payload.keywords,
            importance=payload.importance,
            related_agent=payload.related_agent,
            related_task_id=payload.related_task_id,
            created_by="manual",
        )
        return knowledge_base.add_entry(entry).to_dict()

    @app.put("/knowledge/{entry_id}")
    def update_knowledge(entry_id: str, payload: dict) -> dict:
        entry = knowledge_base.get_entry(entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Knowledge entry not found")
        for key, value in payload.items():
            if hasattr(entry, key) and key not in ("id", "created_at", "created_by"):
                if key == "type":
                    from backend.knowledge_base import KnowledgeType
                    value = KnowledgeType(value)
                elif key == "status":
                    from backend.knowledge_base import KnowledgeStatus
                    value = KnowledgeStatus(value)
                setattr(entry, key, value)
        return knowledge_base.update_entry(entry).to_dict()

    @app.delete("/knowledge/{entry_id}")
    def delete_knowledge(entry_id: str) -> dict:
        if not knowledge_base.delete_entry(entry_id):
            raise HTTPException(status_code=404, detail="Knowledge entry not found")
        return {"ok": True}

    @app.post("/knowledge/{entry_id}/outdated")
    def mark_knowledge_outdated(entry_id: str) -> dict:
        if not knowledge_base.mark_outdated(entry_id):
            raise HTTPException(status_code=404, detail="Knowledge entry not found")
        return {"ok": True, "status": "outdated"}

    @app.post("/knowledge/import")
    def import_knowledge(entries: list[dict]) -> dict:
        count = knowledge_base.import_entries(entries)
        return {"ok": True, "imported": count}

    # ── MCP Server Routes ──

    class McpServerAddRequest(BaseModel):
        name: str
        command: str = "node"
        args: list[str] = []
        env: dict[str, str] = {}
        cwd: str = ""
        enabled: bool = True

    class McpToolCallRequest(BaseModel):
        server_id: str
        tool_name: str
        arguments: dict = {}

    @app.get("/mcp/servers")
    def list_mcp_servers() -> dict:
        """列出所有 MCP Server"""
        try:
            return {"servers": mcp_client.list_servers()}
        except Exception as e:
            logger.error(f"[mcp] list_servers error: {e}")
            return {"servers": []}

    @app.get("/mcp/servers/{server_id}")
    def get_mcp_server(server_id: str) -> dict:
        """获取 MCP Server 详情"""
        server = mcp_client.get_server(server_id)
        if not server:
            raise HTTPException(status_code=404, detail="MCP Server not found")
        return server

    @app.post("/mcp/servers")
    def add_mcp_server(payload: McpServerAddRequest) -> dict:
        """添加 MCP Server"""
        env = dict(payload.env) if payload.env else {}
        args = list(payload.args) if payload.args else []
        try:
            from backend.mcp_client import PRESET_MCP_SERVERS
            for preset in PRESET_MCP_SERVERS.values():
                if preset["name"] == payload.name:
                    defaults = preset.get("env_defaults", {})
                    for key in preset.get("env_keys", []):
                        if key not in env and key in defaults:
                            env[key] = defaults[key]
                    break
        except Exception:
            pass

        return mcp_client.add_server(
            name=payload.name,
            command=payload.command,
            args=args,
            env=env,
            cwd=payload.cwd,
            enabled=payload.enabled,
        )

    @app.put("/mcp/servers/{server_id}")
    def update_mcp_server(server_id: str, payload: dict) -> dict:
        """更新 MCP Server 配置"""
        result = mcp_client.update_server(server_id, **payload)
        if not result:
            raise HTTPException(status_code=404, detail="MCP Server not found")
        return result

    @app.delete("/mcp/servers/{server_id}")
    def delete_mcp_server(server_id: str) -> dict:
        """删除 MCP Server"""
        if not mcp_client.remove_server(server_id):
            raise HTTPException(status_code=404, detail="MCP Server not found")
        return {"ok": True, "message": "MCP Server 已删除"}

    @app.post("/mcp/servers/{server_id}/start")
    async def start_mcp_server(server_id: str) -> dict:
        """启动 MCP Server"""
        return await mcp_client.start_server(server_id)

    @app.post("/mcp/servers/{server_id}/stop")
    async def stop_mcp_server(server_id: str) -> dict:
        """停止 MCP Server"""
        return await mcp_client.stop_server(server_id)

    @app.get("/mcp/servers/{server_id}/tools")
    async def list_mcp_tools(server_id: str) -> dict:
        """列出 MCP Server 的工具"""
        return await mcp_client.list_tools(server_id)

    @app.post("/mcp/tools/call")
    async def call_mcp_tool(payload: McpToolCallRequest) -> dict:
        """调用 MCP 工具"""
        return await mcp_client.call_tool(
            server_id=payload.server_id,
            tool_name=payload.tool_name,
            arguments=payload.arguments,
        )

    @app.get("/mcp/presets")
    def list_mcp_presets() -> dict:
        """列出预设 MCP Server"""
        try:
            from backend.mcp_client import PRESET_MCP_SERVERS
            # 不暴露 env_defaults 中的实际密钥值，只返回 key 名称
            safe = {}
            for k, v in PRESET_MCP_SERVERS.items():
                entry = {kk: vv for kk, vv in v.items() if kk != "env_defaults"}
                safe[k] = entry
            return safe
        except Exception as e:
            logger.error(f"[mcp] presets error: {e}")
            return {}

    # ── Debug: 列出所有注册的路由 ──
    @app.get("/debug/routes")
    def debug_routes():
        try:
            routes = []
            for route in app.routes:
                if hasattr(route, "methods") and hasattr(route, "path"):
                    routes.append({"path": route.path, "methods": list(route.methods)})
            return routes
        except Exception as e:
            logger.error(f"[debug] routes error: {e}")
            return []

    return app


app = create_app()
