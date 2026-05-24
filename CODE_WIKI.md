# All Agent Manager - Code Wiki

## 目录

1. [项目概述](#项目概述)
2. [系统架构](#系统架构)
3. [核心模块详解](#核心模块详解)
4. [API 接口文档](#api-接口文档)
5. [配置与部署](#配置与部署)
6. [开发指南](#开发指南)
7. [测试指南](#测试指南)

---

## 项目概述

### 项目简介

All Agent Manager 是一个智能任务调度中枢系统，用于管理多个子 Agent（OpenClaw、OpenHanako、Hermes）的任务分配和执行。系统具备被动调度、主动发现、智能拆解、执行监控、健康监控、技能记忆、插件管理、复刻引擎、免疫审查、微信桥接等核心功能。

### 核心特性

- **被动调度**: 从 Dashboard 或微信提交任务，智能路由到合适的 Agent
- **主动发现**: 自动扫描项目、文件、API，发现待处理任务
- **智能拆解**: 分析复杂目标，拆解为子任务并分配给最合适的 Agent
- **执行监控**: 任务执行自动重试、超时检测、心跳监控
- **健康监控**: Agent 健康状态检测、连续失败告警、自动恢复
- **技能记忆**: 从成功任务中提炼可复用技能，自动匹配和复用
- **插件管理**: 管理 Agent 可用插件，支持能力查询和 fallback 链
- **复刻引擎**: 自动分析任务历史，生成技能提案
- **免疫审查**: 审查新技能的安全性，防止危险技能自动激活
- **微信桥接**: 通过 iLink 协议连接微信，支持 Token 和二维码登录
- **事件驱动架构**: 统一事件总线，松耦合模块通信
- **WebSocket 实时推送**: 事件实时推送到前端

### 技术栈

- **后端**: Python, FastAPI
- **前端**: HTML, JavaScript, CSS
- **数据库**: SQLite
- **消息队列**: 内置事件总线
- **其他**: httpx, jinja2, pytest, cryptography, qrcode

---

## 系统架构

### 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend 层                              │
│  Dashboard · WebSocket Client · Event Subscriber              │
└───────────────────────────────┬─────────────────────────────────┘
                                │ REST + WebSocket
┌───────────────────────────────┴─────────────────────────────────┐
│                        API 层                                    │
│  FastAPI · Event WS Handler · Auth Middleware                  │
└───────────────────────────────┬─────────────────────────────────┘
                                │
┌───────────────────────────────┴─────────────────────────────────┐
│              ⚡ EventBus — 统一事件总线                          │
│  松耦合通信 · 请求/响应 · 按类型/来源过滤                       │
└───────────────────────────────┬─────────────────────────────────┘
                                │
┌───────────────────────────────┴─────────────────────────────────┐
│                    Core 层 — 业务逻辑                           │
│  TaskRegistry · MasterScheduler · TaskDispatcher              │
│  WaitingScheduler · ExecutionMonitor · HealthMonitor           │
└───────────────────────────────┬─────────────────────────────────┘
                                │
┌───────────────────────────────┴─────────────────────────────────┐
│               Self-Evolution 层 — 自进化闭环                    │
│  SkillMemory · ReplayEngine · EvolutionGuard                   │
│  PluginManager · SkillSynchronizer                            │
└───────────────────────────────┬─────────────────────────────────┘
                                │
┌───────────────────────────────┴─────────────────────────────────┐
│                   Infrastructure 层                            │
│  SQLite Storage · Config Manager · Event Log Persistence       │
│  Skill Store · Knowledge Base                                  │
└───────────────────────────────┬─────────────────────────────────┘
                                │
┌───────────────────────────────┴─────────────────────────────────┐
│                   Worker 层 — 执行引擎                          │
│  OpenClaw Worker · OpenHanako Worker · Hermes Worker           │
│  Worker Pool · Sandbox Manager                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 目录结构

```
All_Agent_Manager/
├── backend/                  # 后端代码
│   ├── adapters/            # Agent 适配器
│   │   ├── __init__.py
│   │   ├── hermes_adapter.py
│   │   ├── openclaw_adapter.py
│   │   └── openhanako_adapter.py
│   ├── core/               # 核心模块
│   │   ├── __init__.py
│   │   ├── base_adapter.py
│   │   ├── router.py
│   │   └── task_schema.py
│   ├── mcp_bus/            # MCP 总线
│   │   ├── __init__.py
│   │   ├── bus_server.py
│   │   ├── code_agent_server.py
│   │   ├── hermes_agent_server.py
│   │   ├── models.py
│   │   ├── openclaw_agent_server.py
│   │   ├── openhanako_agent_server.py
│   │   ├── registry.py
│   │   ├── task_queue.py
│   │   └── tool_agent_server.py
│   ├── __init__.py
│   ├── app.py               # FastAPI 主应用
│   ├── models.py            # 数据模型
│   ├── scheduler.py         # 任务路由
│   ├── dispatcher.py        # 任务执行调度
│   ├── storage.py           # SQLite 持久化
│   ├── workers.py           # Worker 客户端
│   ├── agent_roles.py       # Agent 角色定义
│   ├── project_discovery.py # 主动任务发现模块
│   ├── task_planner.py      # 智能任务拆解模块
│   ├── execution_monitor.py # 执行监控（retry、timeout）
│   ├── agent_health.py      # Agent 健康监控与自动恢复
│   ├── skill_memory.py      # 技能记忆库
│   ├── plugin_manager.py    # 插件管理器
│   ├── replay_engine.py     # 复刻引擎
│   ├── evolution_guard.py   # 免疫审查
│   ├── bridge_manager.py    # 消息桥接管理
│   ├── wechat_adapter.py    # 微信 iLink 协议
│   ├── wechat_login.py      # 微信二维码登录
│   ├── wechat_agent.py      # 微信 Agent
│   ├── openhanako_client.py # OpenHanako 客户端
│   ├── chat.py              # AI 对话模块
│   ├── event_bus.py         # 统一事件总线
│   ├── task_registry.py     # 任务注册表
│   ├── task_handlers.py     # 任务处理器
│   ├── websocket_events.py  # WebSocket 事件推送
│   ├── cluster_api.py       # 集群 API
│   ├── cluster_dispatcher.py# 集群调度器
│   ├── cluster_orchestrator.py # 集群编排器
│   ├── unified_capability_registry.py # 统一能力注册
│   ├── skill_loader.py      # 技能加载器
│   ├── mcp_client.py        # MCP 客户端
│   ├── knowledge_base.py    # 知识库
│   ├── context_compressor.py # 上下文压缩
│   ├── conversation_memory.py # 对话记忆
│   ├── error_classifier.py  # 错误分类
│   └── waiting_scheduler.py # 等待任务调度器
├── frontend/                # 前端代码
│   ├── templates/
│   │   └── index.html       # Dashboard 页面
│   └── static/
│       ├── app.js           # 前端交互逻辑
│       └── styles.css       # 设计系统
├── storage/                 # SQLite 数据库 + 提示词配置
├── tests/                   # 后端测试
├── docs/                    # 文档
├── .env                     # 环境配置
├── .env.example             # 环境配置示例
├── requirements.txt         # 依赖列表
├── README.md                # 项目说明
├── architecture-v2.md       # 架构设计文档
├── start-cluster.bat        # 集群启动脚本
└── start-dev.bat            # 开发启动脚本
```

---

## 核心模块详解

### 1. EventBus - 事件总线

**文件**: `backend/event_bus.py`

**职责**:
- 提供松耦合的模块间通信机制
- 支持订阅/发布模式
- 支持请求/响应模式
- 按事件类型和来源过滤
- 事件日志持久化

**核心类**:

```python
class EventBus:
    def __init__(self, max_subscribers: int = 100, persist_log: bool = False)
    def subscribe(self, callback, filter_types=None, filter_source=None)
    def publish(self, event_type: str, data=None, source: str = "")
    async def publish_async(self, event_type: str, data=None, source: str = "")
    def handle(self, request_type: str, handler: Callable)
    async def request(self, request_type: str, data=None, timeout_ms: int = 30000)
    def get_event_log(self, event_type=None, limit: int = 100)
    def list_subscribers(self)
    def list_handlers(self)
```

**预定义事件类型**:

| 事件类型 | 触发时机 | 数据 |
|---------|---------|------|
| `task.started` | 任务开始执行 | task_id, agent, goal |
| `task.completed` | 任务成功完成 | task_id, duration, result |
| `task.failed` | 任务执行失败 | task_id, error, retry_count |
| `task.timeout` | 任务超时 | task_id, timeout_seconds |
| `agent.health_changed` | Agent 健康状态变化 | agent, old_status, new_status |
| `skill.activated` | 技能被激活 | skill_id, name |
| `review.approved` | 审查通过 | review_id, skill_id |

---

### 2. Storage - 数据持久化

**文件**: `backend/storage.py`

**职责**:
- SQLite 数据库管理
- 任务 CRUD 操作
- 任务状态更新
- 任务查询（按状态、ID 等）

**核心类**:

```python
class TaskRepository:
    def __init__(self, database_path: str | Path)
    def initialize(self) -> None
    def create_task(self, task: TaskCreate, *, selected_agent: AgentChoice,
                   routing_reason: str, scheduler_mode: str,
                   plan_summary: str) -> TaskRecord
    def get_task(self, task_id: str) -> TaskRecord | None
    def list_tasks(self) -> list[TaskRecord]
    def list_tasks_by_status(self, status: TaskStatus) -> list[TaskRecord]
    def update_task_state(self, task_id: str, status: TaskStatus) -> None
    def set_waiting(self, task_id: str, *, reason: str) -> None
    def complete_task(self, task_id: str, *, result_payload: str) -> None
    def fail_task(self, task_id: str, *, error_message: str) -> None
```

**数据库表结构**:

```sql
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    goal TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_agent TEXT NOT NULL,
    selected_agent TEXT NOT NULL,
    routing_reason TEXT NOT NULL,
    scheduler_mode TEXT NOT NULL,
    plan_summary TEXT NOT NULL,
    result_payload TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_dispatch_attempt_at TEXT
)
```

---

### 3. Scheduler - 任务路由

**文件**: `backend/scheduler.py`

**职责**:
- 基于关键词的任务智能路由
- 支持显式指定 Agent
- 自动选择最合适的 Agent

**核心函数**:

```python
def route_task(goal: str, requested_agent: AgentChoice) -> RoutingDecision
```

**路由关键词**:

| Agent | 关键词 |
|-------|-------|
| OpenHanako | wechat, 微信, bridge, 桥接, desktop, 桌面, chat, 聊天 |
| Hermes | research, summary, summarize, analysis |
| OpenClaw | implement, code, fix, build |

---

### 4. Dispatcher - 任务调度执行

**文件**: `backend/dispatcher.py`

**职责**:
- 任务执行状态管理
- Worker 调用
- 可用性检测
- 执行监控集成

**核心类**:

```python
class TaskDispatcher:
    def __init__(self, repository: TaskRepository, worker_client: WorkerClient,
                 availability_probe=None, execution_monitor=None)
    def run_sync(self, task_id: str) -> None
    async def run_task(self, task_id: str) -> None
```

---

### 5. SkillMemory - 技能记忆库

**文件**: `backend/skill_memory.py`

**职责**:
- 技能模板存储与管理
- 技能匹配
- 使用统计记录
- 技能激活/禁用

**核心类**:

```python
@dataclass
class SkillTemplate:
    id: str
    name: str
    description: str
    status: SkillStatus
    source: SkillSource
    trigger_keywords: list[str]
    steps: list[SkillStep]
    preferred_agents: list[str]
    total_uses: int
    success_count: int
    fail_count: int
    avg_duration: float

class SkillMemory:
    def create_skill(self, template: SkillTemplate) -> SkillTemplate
    def get_skill(self, skill_id: str) -> SkillTemplate | None
    def list_skills(self, status=None) -> list[SkillTemplate]
    def match_skill(self, goal: str) -> SkillTemplate | None
    def activate_skill(self, skill_id: str) -> bool
    def disable_skill(self, skill_id: str) -> bool
    def delete_skill(self, skill_id: str) -> bool
```

---

### 6. ExecutionMonitor - 执行监控

**文件**: `backend/execution_monitor.py`

**职责**:
- 任务执行跟踪
- 超时检测
- 重试管理
- 执行历史记录
- 统计分析

**核心功能**:
- 开始执行监控
- 完成执行记录
- 失败执行记录
- 获取状态摘要
- 获取 Agent 统计
- 清理历史记录

---

### 7. AgentHealth - 健康监控

**文件**: `backend/agent_health.py`

**职责**:
- Agent 健康状态检测
- 连续失败监控
- 自动恢复动作
- 健康历史记录

**健康状态**:
- `healthy`: 健康
- `degraded`: 降级
- `unhealthy`: 不健康
- `unknown`: 未知

---

### 8. PluginManager - 插件管理

**文件**: `backend/plugin_manager.py`

**职责**:
- 插件注册与管理
- 能力图谱维护
- 插件启用/禁用
- 插件查询

---

### 9. ReplayEngine - 复刻引擎

**文件**: `backend/replay_engine.py`

**职责**:
- 任务历史分析
- 模式识别
- 技能提案生成
- 置信度计算

---

### 10. EvolutionGuard - 免疫审查

**文件**: `backend/evolution_guard.py`

**职责**:
- 技能安全性审查
- 审查规则管理
- 审查流程控制
- 批量审查支持

---

### 11. ProjectDiscovery - 主动发现

**文件**: `backend/project_discovery.py`

**职责**:
- 文件系统扫描
- Git 仓库检测
- API 轮询
- 配置任务加载
- 待处理任务管理

---

### 12. BridgeManager - 消息桥接

**文件**: `backend/bridge_manager.py`

**职责**:
- 微信连接管理
- 消息收发
- Token 登录
- 二维码登录
- 消息历史记录

---

### 13. WeChatAgent - 微信 Agent

**文件**: `backend/wechat_agent.py`

**职责**:
- 微信消息处理
- 总调度 Agent（iliya）
- 亲密度系统
- 定时消息
- 技能调用

---

### 14. Core/Router - Agent 路由器

**文件**: `backend/core/router.py`

**职责**:
- 统一适配器管理
- Agent 能力查询
- 任务分发
- 能力注册表集成

---

### 15. Adapters - Agent 适配器

**文件**:
- `backend/adapters/openclaw_adapter.py`
- `backend/adapters/openhanako_adapter.py`
- `backend/adapters/hermes_adapter.py`

**职责**:
- 各 Agent 的统一接口
- HTTP/CLI 调用封装
- 错误处理

---

### 16. MCP Bus - MCP 总线

**文件**: `backend/mcp_bus/`

**职责**:
- MCP Server 管理
- 工具调用
- Agent 服务集成

---

## 核心数据模型

### AgentChoice

```python
class AgentChoice(StrEnum):
    AUTO = "auto"
    OPENCLAW = "openclaw"
    HERMES = "hermes"
    OPENHANAKO = "openhanako"
```

### TaskStatus

```python
class TaskStatus(StrEnum):
    PENDING = "pending"
    WAITING = "waiting"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
```

### TaskRecord

```python
@dataclass
class TaskRecord:
    id: str
    goal: str
    status: TaskStatus
    requested_agent: AgentChoice
    selected_agent: AgentChoice
    routing_reason: str
    scheduler_mode: str
    plan_summary: str
    result_payload: Optional[str]
    error_message: Optional[str]
    created_at: str
    updated_at: str
    retry_count: int = 0
```

---

## API 接口文档

### 任务管理

#### POST /submit-task
提交新任务

**请求体**:
```json
{
  "goal": "任务描述",
  "requested_agent": "auto|openclaw|hermes|openhanako"
}
```

**响应**:
```json
{
  "task_id": "uuid",
  "status": "pending",
  "selected_agent": "openclaw",
  "routing_reason": "..."
}
```

#### GET /tasks
获取任务列表

**查询参数**:
- `status`: 可选，按状态过滤

#### GET /tasks/{task_id}
获取任务详情

#### POST /tasks/{task_id}/cancel
取消任务

#### POST /tasks/{task_id}/retry
重试任务

---

### 微信桥接

#### GET /bridge/status
获取桥接状态

#### POST /bridge/wechat/connect
连接微信（Token 方式）

**请求体**:
```json
{
  "bot_token": "...",
  "agent_id": "..."
}
```

#### POST /bridge/wechat/disconnect
断开微信连接

#### GET /bridge/wechat/qrcode
获取二维码

#### POST /bridge/wechat/qrcode/poll
轮询扫码状态

#### GET /bridge/messages
获取消息历史

#### GET /bridge/iliya-status
获取 iliya 状态

#### GET /bridge/intimacy/{user_id}
获取用户亲密度

#### GET /bridge/skills/{user_id}
获取用户技能

---

### Agent 管理

#### GET /agents/status
获取 Agent 状态

#### GET /agents/roles
获取 Agent 角色

#### GET /agents/prompt
获取提示词

#### POST /agents/prompt
更新提示词

#### POST /agents/prompt/reset
重置提示词

---

### 路由器

#### GET /router/agents
列出已注册 Agent

#### GET /router/stats
获取路由器统计

#### GET /router/history
获取分发历史

#### POST /router/dispatch
分发任务

#### POST /router/route
预览路由（不执行）

---

### 智能发现

#### GET /discovery/sources
获取任务来源

#### POST /discovery/scan
手动触发扫描

#### GET /discovery/pending
获取待处理任务

#### POST /discovery/take/{task_id}
认领任务

#### POST /discovery/clear
清空待处理任务

#### GET /discovery/history
获取扫描历史

---

### 执行监控

#### GET /monitor/status
获取监控状态

#### GET /monitor/execution-stats
获取执行统计

#### GET /monitor/agent-stats
获取 Agent 统计

#### GET /monitor/history
获取执行历史

#### POST /monitor/cleanup
清理历史记录

---

### 健康监控

#### GET /health/summary
获取健康摘要

#### GET /health/detail
获取详细状态

#### GET /health/status
获取健康状态

#### POST /health/check
执行健康检查

#### GET /health/history
获取恢复历史

---

### 技能库

#### GET /skills
获取技能列表

#### GET /skills/stats
获取技能统计

#### GET /skills/match?goal=...
匹配技能

#### GET /skills/{skill_id}
获取技能详情

#### POST /skills
创建技能

#### POST /skills/{skill_id}/activate
激活技能

#### POST /skills/{skill_id}/disable
禁用技能

#### DELETE /skills/{skill_id}
删除技能

#### POST /skills/upload
上传技能 ZIP

#### GET /skills/files
列出已上传文件

#### DELETE /skills/files/{name}
删除技能文件

---

### 插件管理

#### GET /plugins
获取插件列表

#### GET /plugins/stats
获取插件统计

#### GET /plugins/capabilities
获取能力图谱

#### GET /plugins/{plugin_id}
获取插件详情

#### POST /plugins
注册插件

#### POST /plugins/{plugin_id}/enable
启用插件

#### POST /plugins/{plugin_id}/disable
禁用插件

#### POST /plugins/upload
上传插件 ZIP

#### GET /plugins/files
列出已上传文件

#### DELETE /plugins/files/{name}
删除插件文件

---

### 复刻引擎

#### POST /replay/analyze
分析任务历史

#### POST /replay/generate
生成技能提案

#### POST /replay/submit/{proposal_id}
提交审查

#### GET /replay/config
获取配置

#### POST /replay/config
更新配置

---

### 进化审查

#### GET /evolution/reviews
获取审查列表

#### GET /evolution/pending
获取待审查

#### GET /evolution/stats
获取审查统计

#### GET /evolution/reviews/{review_id}
获取审查详情

#### POST /evolution/reviews/{review_id}/approve
批准审查

#### POST /evolution/reviews/{review_id}/reject
拒绝审查

#### POST /evolution/batch/approve
批量批准

#### POST /evolution/batch/reject
批量拒绝

#### POST /evolution/auto-approve
自动批准

#### GET /evolution/rules
获取审查规则

---

### 事件总线

#### GET /eventbus/stats
获取统计

#### GET /eventbus/events
获取事件日志

---

### 任务注册表

#### GET /registry/stats
获取统计

#### GET /registry/tasks
获取任务实例

#### GET /registry/types
获取已注册类型

---

### WebSocket

#### WS /ws/events
WebSocket 事件流

#### GET /ws/status
获取连接状态

---

### AI 对话

#### GET /chat/history
获取对话历史

#### POST /chat/send
发送消息

#### POST /chat/clear
清空历史

---

### 模型供应商

#### GET /model/providers
列出供应商

#### GET /model/providers/{id}
获取供应商详情

#### POST /model/providers
添加供应商

#### PUT /model/providers/{id}
更新供应商

#### DELETE /model/providers/{id}
删除供应商

#### POST /model/active
设置活跃供应商

#### GET /model/active
获取活跃供应商

---

## 配置与部署

### 环境变量

#### Agent 配置

```env
# OpenClaw
OPENCLAW_URL=http://127.0.0.1:18789/run-task

# OpenHanako
OPENHANAKO_HOST=localhost
OPENHANAKO_PORT=12306

# Hermes
HERMES_URL=http://127.0.0.1:8102/run-task
HERMES_CLI_COMMAND=python D:/Hermes/main.py run-task
HERMES_BUSY_FILE=D:/Hermes/runtime/hermes.busy
HERMES_BUSY_STALE_SECONDS=120
```

#### 调度配置

```env
WAITING_TASK_SCAN_SECONDS=3
```

#### 任务发现

```env
DISCOVERY_SCAN_DIRS=D:/Project1,D:/Project2
DISCOVERY_GIT_REPOS=D:/Repo1,D:/Repo2
DISCOVERY_CONFIG_PATH=D:/tasks.json
DISCOVERY_API_URL=https://api.example.com/tasks
DISCOVERY_API_POLL_INTERVAL=60
DISCOVERY_SCAN_INTERVAL=300
```

#### 任务规划器

```env
PLANNER_MODE=rules|llm|hybrid
```

#### 复刻引擎

```env
REPLAY_CONFIDENCE_THRESHOLD=0.3
REPLAY_MIN_OCCURRENCES=2
```

#### 执行监控

```env
TASK_TIMEOUT_SECONDS=300
TASK_MAX_RETRIES=3
TIMEOUT_CHECK_INTERVAL=10
```

#### 健康监控

```env
HEALTH_CHECK_INTERVAL=60
HEALTH_FAILURE_THRESHOLD=3
```

#### MCP 存储

```env
MCP_STORAGE_DIR=storage
```

#### MiniMax（可选）

```env
MINIMAX_API_KEY=...
```

### 运行方式

#### 开发模式

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
uvicorn backend.app:app --reload
```

或使用提供的脚本：

```bash
# Windows
start-dev.bat
```

#### 集群模式

```bash
# Windows
start-cluster.bat
```

### 访问地址

启动后访问：
- Dashboard: `http://127.0.0.1:8000/`
- API 文档: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

---

## 开发指南

### 代码风格

- 遵循 PEP 8 规范
- 使用类型注解
- 文档字符串使用 Google 风格

### 添加新的 Agent

1. 创建适配器: `backend/adapters/my_agent_adapter.py`
2. 继承 `BaseAdapter`
3. 实现 `can_handle()` 和 `execute()` 方法
4. 在 `app.py` 中注册到 `AgentRouter`

### 添加新的事件类型

在 `backend/event_bus.py` 的 `EventTypes` 类中添加：

```python
class EventTypes:
    MY_NEW_EVENT = "my.new.event"
```

### 添加新的 API 端点

在 `backend/app.py` 中添加 FastAPI 路由。

### 前端开发

前端文件位于 `frontend/` 目录：
- `templates/index.html`: 主页面
- `static/app.js`: 交互逻辑
- `static/styles.css`: 样式

---

## 测试指南

### 运行测试

```bash
pytest -q
```

### 测试文件

测试文件位于 `tests/` 目录：

- `test_app.py`: 主应用测试
- `test_dispatcher.py`: 调度器测试
- `test_scheduler.py`: 路由测试
- `test_storage.py`: 存储测试
- `test_workers.py`: Worker 测试
- `test_skill_memory.py`: 技能记忆测试
- `test_plugin_manager.py`: 插件管理测试
- `test_execution_monitor.py`: 执行监控测试
- `test_agent_health.py`: 健康监控测试
- `test_event_bus.py`: 事件总线测试
- `test_task_registry.py`: 任务注册表测试
- `test_waiting_scheduler.py`: 等待调度测试
- `test_evolution_guard.py`: 进化审查测试
- `test_planner.py`: 规划器测试
- `test_discovery.py`: 发现模块测试

---

## 版本历史

### V2.0 - 事件驱动架构
- EventBus 统一事件总线
- TaskRegistry 任务注册表
- WebSocket 实时推送
- 集群编排支持
- MCP 总线集成

### V1.0 - 工业常驻版
- 后台保活
- 自动重试
- 插件白名单
- 技能库
- 审计日志

### V0.6 - Phoenix-Evo 接入版
- 技能提取
- 免疫审查
- 草稿库
- 人工确认

### V0.5 - 技能复刻版
- 成功任务分析
- 自动总结流程
- 生成草稿技能
- 自动复用

### V0.4 - 插件管理版
- 插件注册
- 能力查询
- Fallback 链

### V0.3 - 调度 AI 版
- 目标分析
- 任务拆解
- 自动分配

### V0.2 - 状态追踪版
- 任务状态
- 历史记录

### V0.1 - 本地派活控制台
- 任务提交
- Agent 选择

---

## 附录

### Worker 契约

#### HTTP Worker

请求:
```json
{
  "task_id": "uuid",
  "task_content": "任务描述",
  "priority": "normal"
}
```

响应: 任何 2xx 状态码，返回 JSON 结果。

#### CLI Worker

命令:
```bash
python D:/Hermes/main.py run-task --task '{"task_id": "...", "task_content": "...", "priority": "normal"}'
```

输出: 标准输出的 JSON 对象。

---

*本文档最后更新: 2026-05-14*
