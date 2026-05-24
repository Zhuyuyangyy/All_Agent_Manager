# All-Agent Manager V2 架构设计

> 基于 OpenHanako 启发的架构升级方案

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend 层                            │
│  Dashboard · WebSocket Client · Event Subscriber            │
└───────────────────────────┬─────────────────────────────────┘
                            │ REST + WebSocket
┌───────────────────────────┴─────────────────────────────────┐
│                        API 层                                │
│  FastAPI · Event WS Handler · Auth Middleware                │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────┴─────────────────────────────────┐
│              ⚡ EventBus — 统一事件总线                       │
│  松耦合通信 · 请求/响应 · 按类型/来源过滤                      │
│  task.* · agent.* · skill.* · review.* · plugin.* · system.* │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────┴─────────────────────────────────┐
│                    Core 层 — 业务逻辑                         │
│  TaskRegistry · MasterScheduler · TaskDispatcher             │
│  WaitingScheduler · ExecutionMonitor · HealthMonitor         │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────┴─────────────────────────────────┐
│               Self-Evolution 层 — 自进化闭环                  │
│  SkillMemory · ReplayEngine · EvolutionGuard                 │
│  PluginManager · SkillContributor                            │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────┴─────────────────────────────────┐
│                   Infrastructure 层                          │
│  SQLite Storage · Config Manager · Event Bus Persistence     │
│  Skill Store                                                │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────┴─────────────────────────────────┐
│                   Worker 层 — 执行引擎                        │
│  OpenClaw Worker · OpenHanako Worker · Hermes Worker         │
│  Worker Pool · Sandbox Manager                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 模块设计

### 1. EventBus 事件总线

参考 OpenHanako 的 `hub/event-bus.js`，实现统一事件系统。

```python
class EventBus:
    """统一事件总线，支持订阅/发布和请求/响应模式"""

    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}
        self._handlers: dict[str, Callable] = {}

    def subscribe(self, event_type: str, callback: Callable):
        """订阅事件"""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def publish(self, event_type: str, data: dict):
        """发布事件"""
        for callback in self._subscribers.get(event_type, []):
            callback(event_type, data)

    def handle(self, request_type: str, handler: Callable):
        """注册请求处理器（请求/响应模式）"""
        self._handlers[request_type] = handler

    async def request(self, request_type: str, data: dict) -> Any:
        """发送请求并等待响应"""
        handler = self._handlers.get(request_type)
        if handler:
            return await handler(data)
        raise NoHandlerError(request_type)
```

**事件类型定义：**

| 事件类型 | 触发时机 | 数据 |
|---------|---------|------|
| `task.started` | 任务开始执行 | task_id, agent, goal |
| `task.completed` | 任务成功完成 | task_id, duration, result |
| `task.failed` | 任务执行失败 | task_id, error, retry_count |
| `task.timeout` | 任务超时 | task_id, timeout_seconds |
| `task.retrying` | 任务重试中 | task_id, retry_count |
| `agent.health_changed` | Agent 健康状态变化 | agent, old_status, new_status |
| `agent.recovery_triggered` | 触发恢复动作 | agent, action, reason |
| `skill.activated` | 技能被激活 | skill_id, name |
| `skill.extracted` | 从任务中提取技能 | skill_id, task_id |
| `review.approved` | 审查通过 | review_id, skill_id |
| `review.rejected` | 审查拒绝 | review_id, skill_id, reason |
| `review.auto_approved` | 自动批准 | review_id, skill_id |
| `plugin.registered` | 插件注册 | plugin_id, capabilities |
| `plugin.capability_added` | 新增能力 | plugin_id, capability |
| `system.startup` | 系统启动 | timestamp |
| `system.shutdown` | 系统关闭 | timestamp |

---

### 2. TaskRegistry 任务注册表

参考 OpenHanako 的 `lib/task-registry.js`，实现类型处理器模式。

```python
class TaskHandler(ABC):
    """任务处理器基类"""

    @abstractmethod
    async def execute(self, task_id: str, payload: dict) -> TaskResult:
        """执行任务"""
        pass

    @abstractmethod
    async def abort(self, task_id: str) -> bool:
        """中止任务"""
        pass

    @abstractmethod
    async def query(self, task_id: str) -> dict | None:
        """查询任务状态"""
        pass


class TaskRegistry:
    """任务注册表 — 类型处理器 + 动态任务实例"""

    def __init__(self, event_bus: EventBus):
        self._handlers: dict[str, TaskHandler] = {}
        self._tasks: dict[str, TaskInstance] = {}
        self._event_bus = event_bus

    def register_handler(self, task_type: str, handler: TaskHandler):
        """注册任务类型处理器"""
        self._handlers[task_type] = handler

    def register_task(self, task_id: str, task_type: str, meta: dict):
        """注册任务实例"""
        self._tasks[task_id] = TaskInstance(
            task_id=task_id,
            task_type=task_type,
            meta=meta,
            status="registered",
        )

    async def dispatch(self, task_id: str, payload: dict):
        """分发任务到对应处理器"""
        task = self._tasks.get(task_id)
        if not task:
            raise TaskNotFoundError(task_id)

        handler = self._handlers.get(task.task_type)
        if not handler:
            raise NoHandlerError(task.task_type)

        self._event_bus.publish("task.started", {
            "task_id": task_id,
            "type": task.task_type,
        })

        try:
            result = await handler.execute(task_id, payload)
            self._event_bus.publish("task.completed", {
                "task_id": task_id,
                "result": result,
            })
        except Exception as e:
            self._event_bus.publish("task.failed", {
                "task_id": task_id,
                "error": str(e),
            })
            raise

    async def abort(self, task_id: str) -> bool:
        """中止任务"""
        task = self._tasks.get(task_id)
        if not task:
            return False

        handler = self._handlers.get(task.task_type)
        if handler:
            return await handler.abort(task_id)
        return False
```

**任务类型处理器：**

| 类型 | 处理器 | 说明 |
|------|--------|------|
| `http_task` | HttpTaskHandler | OpenClaw/OpenHanako HTTP 调用 |
| `cli_task` | CliTaskHandler | Hermes CLI 命令执行 |
| `discovery_task` | DiscoveryTaskHandler | 智能发现扫描 |
| `replay_task` | ReplayTaskHandler | 复刻分析任务 |
| `health_check` | HealthCheckTaskHandler | Agent 健康检查 |

---

### 3. 多 Agent 并行执行

```python
class WorkerPool:
    """Worker 池 — 控制并发数和资源"""

    def __init__(self, max_concurrent: int = 5):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running: dict[str, asyncio.Task] = {}

    async def submit(self, task_id: str, worker_func: Callable):
        """提交任务到 Worker 池"""
        async with self._semaphore:
            task = asyncio.create_task(worker_func())
            self._running[task_id] = task
            try:
                result = await task
                return result
            finally:
                self._running.pop(task_id, None)

    async def cancel(self, task_id: str):
        """取消任务"""
        task = self._running.get(task_id)
        if task:
            task.cancel()
            self._running.pop(task_id, None)

    @property
    def active_count(self) -> int:
        return len(self._running)
```

**并行调度流程：**

```python
class ParallelDispatcher:
    """并行调度器 — 非阻塞任务下发"""

    def __init__(self, worker_pool: WorkerPool, event_bus: EventBus):
        self._pool = worker_pool
        self._event_bus = event_bus

    async def dispatch_parallel(self, tasks: list[Task]):
        """并行下发多个任务"""
        coroutines = []
        for task in tasks:
            coroutine = self._pool.submit(
                task.id,
                self._execute_task(task)
            )
            coroutines.append(coroutine)

        # 非阻塞等待所有任务
        results = await asyncio.gather(*coroutines, return_exceptions=True)
        return results

    async def _execute_task(self, task: Task):
        """执行单个任务"""
        worker = self._get_worker(task.agent)
        result = await worker.run_task(task)
        return result
```

---

### 4. 插件贡献能力

参考 OpenHanako 的插件系统，扩展插件贡献模式。

```python
class SkillContributor:
    """技能贡献器 — 插件贡献技能模板"""

    def __init__(self, skill_memory: SkillMemory, event_bus: EventBus):
        self._skill_memory = skill_memory
        self._event_bus = event_bus
        self._contributors: dict[str, list[SkillTemplate]] = {}

    def register_contributor(self, plugin_id: str, skills: list[SkillTemplate]):
        """注册插件贡献的技能"""
        self._contributors[plugin_id] = skills
        for skill in skills:
            self._skill_memory.create_skill(skill)
            self._event_bus.publish("skill.registered", {
                "skill_id": skill.id,
                "plugin_id": plugin_id,
            })

    def unregister_contributor(self, plugin_id: str):
        """取消插件贡献"""
        skills = self._contributors.pop(plugin_id, [])
        for skill in skills:
            self._skill_memory.disable_skill(skill.id)
            self._event_bus.publish("skill.disabled", {
                "skill_id": skill.id,
                "plugin_id": plugin_id,
            })

    def list_contributors(self) -> dict[str, list[str]]:
        """列出所有贡献者及其技能"""
        return {
            pid: [s.name for s in skills]
            for pid, skills in self._contributors.items()
        }
```

**插件目录结构：**

```
my-plugin/
├── manifest.json          # 插件描述
├── tools/                 # 工具（Agent 调用）
│   └── *.py
├── skills/                # 技能模板
│   └── my-skill/
│       └── SKILL.md
├── agents/                # Agent 模板
│   └── *.json
├── commands/              # 用户命令
│   └── *.py
├── routes/                # HTTP 路由
│   └── *.py
└── index.py               # 插件入口
```

---

## 实施计划

### 阶段 A：核心架构升级（2-3 周）

| 任务 | 工作量 | 依赖 |
|------|--------|------|
| 实现 EventBus 核心 | 3 天 | 无 |
| 重构 TaskRegistry | 4 天 | EventBus |
| 迁移现有模块到事件驱动 | 5 天 | EventBus + TaskRegistry |
| 添加 WebSocket 事件推送 | 3 天 | EventBus |
| 单元测试 | 2 天 | 全部 |

### 阶段 B：多 Agent 并行（1-2 周）

| 任务 | 工作量 | 依赖 |
|------|--------|------|
| 实现 WorkerPool | 2 天 | 无 |
| 改造 Dispatcher 为非阻塞 | 3 天 | WorkerPool |
| 并发控制和资源限制 | 2 天 | WorkerPool |
| 集成测试 | 2 天 | 全部 |

### 阶段 C：插件贡献（1-2 周）

| 任务 | 工作量 | 依赖 |
|------|--------|------|
| 实现 SkillContributor | 2 天 | EventBus |
| 插件目录扫描和加载 | 3 天 | SkillContributor |
| Agent 模板贡献 | 2 天 | 无 |
| 插件权限控制 | 2 天 | 无 |

---

## 数据兼容性

### SQLite 迁移

```sql
-- 新增事件日志表
CREATE TABLE IF NOT EXISTS event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    data JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 新增任务类型字段
ALTER TABLE tasks ADD COLUMN task_type TEXT DEFAULT 'http_task';
ALTER TABLE tasks ADD COLUMN handler_id TEXT;
```

### 配置兼容

现有环境变量保持不变，新增可选配置：

```powershell
# EventBus 配置
$env:EVENT_BUS_MAX_SUBSCRIBERS="100"
$env:EVENT_BUS_PERSIST_LOG="true"

# Worker Pool 配置
$env:WORKER_POOL_MAX_CONCURRENT="5"
$env:WORKER_POOL_TIMEOUT_SECONDS="300"

# 插件目录
$env:PLUGINS_DIR="storage/plugins"
```

---

## 参考资源

- OpenHanako EventBus: `hub/event-bus.js`
- OpenHanako TaskRegistry: `lib/task-registry.js`
- OpenHanako PluginManager: `core/plugin-manager.js`
- OpenHanako Scheduler: `hub/scheduler.js`
- OpenHanako AgentManager: `core/agent-manager.js`

---

*All-Agent Manager V2 — Self-Evolving Agent Orchestrator*
