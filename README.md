# All_Agent_Manager — 多Agent集群智能调度平台

> **版本**: v2.0 | **技术栈**: FastAPI + SQLite + WebSocket + EventBus
> **状态**: 🚀 生产就绪 | **核心**: ClusterDispatcher + ClusterOrchestrator

---

## 🎯 项目定位

All_Agent_Manager 是一个**多Agent集群智能调度平台**，管理三个子Agent（OpenClaw、OpenHanako、Hermes），实现任务的智能路由、并行执行、故障恢复与技能记忆。

**核心价值**: 从单Agent被动调度升级为**多Agent集群协同调度**，支持任务并行、负载均衡、技能记忆和自动恢复。

---

## 🔬 核心创新点

| 创新点 | 代码模块 | 技术方案 | 效果 |
|--------|----------|----------|------|
| **集群调度架构** | `cluster_dispatcher.py` | ClusterDispatcher + ClusterOrchestrator | 支持全并行任务执行 |
| **双模式运行** | `ClusterDispatcher` | 同步模式(legacy) + 集群模式(cluster) | 兼容旧API + 新能力 |
| **EventBus事件驱动** | `event_bus.py` | 发布-订阅模式，松耦合 | 模块间无直接依赖 |
| **TaskRegistry** | `task_registry.py` | 类型处理器模式 | 动态任务管理 |
| **技能记忆库** | `skill_memory.py` | 模板匹配 + 统计学习 | 从历史任务中学习 |
| **Agent健康监控** | `agent_health.py` | 心跳检测 + 自动恢复 | 故障自动转移 |
| **微信桥接** | `wechat_adapter.py` | iLink协议 + WebSocket | 微信消息实时推送 |

---

## 🏗️ 系统架构

### 整体架构图

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        All_Agent_Manager v2.0 架构                        │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐     ┌─────────────────┐     ┌──────────────────────┐  │
│  │  Dashboard   │────▶│   FastAPI       │◀────│   WeChat (iLink)     │  │
│  │  Web UI      │     │   app.py        │     │   wechat_adapter     │  │
│  └──────────────┘     └────────┬────────┘     └──────────────────────┘  │
│                               │                                         │
│  ┌──────────────┐     ┌──────▼────────┐     ┌──────────────────────────┐ │
│  │  EventBus    │◀───▶│ EventBus V2   │◀────│   微信消息 / 任务提交    │ │
│  │  事件总线    │     │ (发布-订阅)   │     └──────────────────────────┘ │
│  └──────┬───────┘     └──────┬────────┘                                   │
│         │                    │                                            │
│  ┌──────▼────────────────────▼──────────────────┐                         │
│  │              TaskRegistry 任务注册表         │                         │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  │                         │
│  │  │CodeTask  │  │DocTask  │  │DataTask  │  │  ...动态扩展             │
│  │  └──────────┘  └──────────┘  └──────────┘  │                         │
│  └────────────────────┬───────────────────────┘                         │
│                       │                                                   │
│  ┌────────────────────▼───────────────────────┐                         │
│  │       ClusterDispatcher 集群调度器          │                         │
│  │  ┌────────────────┐  ┌──────────────────┐ │                         │
│  │  │ 同步模式        │  │ 集群模式          │ │                         │
│  │  │ run_sync()     │  │ submit_cluster_task()│                        │
│  │  │ 单Agent执行    │  │ 全并行执行        │ │                         │
│  │  └────────────────┘  └──────────────────┘ │                         │
│  └────────────────────┬───────────────────────┘                         │
│                       │                                                   │
│  ┌────────────────────▼───────────────────────┐                         │
│  │    ClusterOrchestrator 集群编排器           │                         │
│  │    UnifiedCapabilityRegistry 能力注册表      │                         │
│  └────────────────────┬───────────────────────┘                         │
│                       │                                                   │
│         ┌─────────────┼─────────────┐                                    │
│         ▼             ▼             ▼                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                                │
│  │ OpenClaw │  │ OpenHanako│ │  Hermes  │                                │
│  │ Worker   │  │  Worker  │  │  Worker  │                                │
│  └──────────┘  └──────────┘  └──────────┘                                │
│                                                                          │
│  ┌──────────────────────────────────────────────┐                       │
│  │          持久化层 (SQLite task.db)           │                       │
│  │  TaskRepository | SkillMemory | AgentHealth   │                       │
│  └──────────────────────────────────────────────┘                       │
└──────────────────────────────────────────────────────────────────────────┘
```

### EventBus 发布-订阅模型

```
┌──────────────────────────────────────────────────────────────┐
│                      EventBus V2 事件流                        │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  [Publisher]              [EventBus]              [Subscriber] │
│                                                               │
│  ┌─────────┐              ┌─────────┐           ┌──────────┐  │
│  │ app.py  │──event───▶│ EventBus│───dispatch──▶│ scheduler │  │
│  └─────────┘              │  广播   │           └──────────┘  │
│                           │         │           ┌──────────┐  │
│  ┌─────────────┐          │ Topics: │           │ dispatcher│  │
│  │wechat_adapter│──e───▶│         │           └──────────┘  │
│  └─────────────┘          │task.*   │           ┌──────────┐  │
│                           │agent.*  │           │monitor   │  │
│  ┌─────────────┐          │skill.*  │           └──────────┘  │
│  │task_planner │──e───▶│         │                          │
│  └─────────────┘          └─────────┘                          │
│                                                               │
│  Event Types:                                                   │
│    task.submitted | task.started | task.completed | task.failed │
│    agent.registered | agent.heartbeat | agent.recovered        │
│    skill.learned | skill.matched                               │
└──────────────────────────────────────────────────────────────┘
```

---

## 📁 项目结构

```
All_Agent_Manager/
├── backend/
│   ├── app.py                    # FastAPI主应用 + 路由
│   ├── models.py                 # Pydantic模型 + TaskStatus枚举
│   ├── scheduler.py              # 任务路由器(RoutingDecision)
│   ├── cluster_dispatcher.py     # 🚀 v2.0核心: ClusterDispatcher
│   ├── storage.py                # SQLite TaskRepository
│   ├── workers.py                # WorkerClient(OpenClaw/OpenHanako/Hermes)
│   ├── agent_roles.py            # Agent角色 + 提示词模板
│   ├── project_discovery.py       # 主动任务发现
│   ├── task_planner.py            # 任务智能拆解
│   ├── execution_monitor.py      # 执行监控(retry/timeout/heartbeat)
│   ├── agent_health.py           # Agent健康监控 + 自动恢复
│   ├── skill_memory.py           # 技能记忆库
│   ├── plugin_manager.py         # 插件管理器
│   ├── replay_engine.py          # 复刻引擎
│   ├── evolution_guard.py        # 免疫审查
│   ├── bridge_manager.py         # 消息桥接管理
│   ├── wechat_adapter.py         # 微信iLink协议
│   ├── wechat_login.py           # 微信二维码登录
│   ├── openhanako_client.py      # OpenHanako HTTP客户端
│   ├── chat.py                   # AI对话模块
│   ├── event_bus.py              # EventBus V2统一事件总线
│   ├── task_registry.py          # TaskRegistry V2任务注册表
│   └── cluster_orchestrator.py   # ClusterOrchestrator集群编排器
├── frontend/
│   └── index.html                # Web UI实时监控
├── .env                          # 环境配置
├── requirements.txt
├── README.md                     # 本文件
├── architecture-v2.md            # 架构文档(15KB)
├── CODE_WIKI.md                  # 代码百科(27KB)
├── SCI_FRAMEWORK.md              # SCI论文框架(56KB)
├── 专利技术交底书.md              # 专利文档(56KB)
└── docs/
    ├── HERMES_UPGRADE_SUMMARY.md # Hermes升级总结
    └── VERIFICATION_REPORT.md    # 验证报告
```

---

## 🚀 快速启动

### 启动服务

```bash
cd /mnt/d/ZYY Project/All_Agent_Manager/backend

# 安装依赖
pip install fastapi uvicorn pydantic aiohttp websockets

# 启动服务(演示模式)
python app.py
# 访问 http://localhost:8000

# 真实Worker模式(需配置.env)
OPENCLAW_URL=http://localhost:5000
OPENHANAKO_URL=http://localhost:5001
HERMES_URL=http://localhost:8080
```

### 同步模式API(兼容旧版)

```bash
# 提交单个任务
curl -X POST http://localhost:8000/submit-task \
  -H "Content-Type: application/json" \
  -d '{"goal": "修复登录bug", "requested_agent": "auto"}'

# 查询任务状态
curl http://localhost:8000/task/{task_id}

# 获取任务结果
curl http://localhost:8000/task/{task_id}/result
```

### 集群模式API(v2.0新)

```bash
# 提交并行任务(最多3个并行)
curl -X POST http://localhost:8000/cluster/submit \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "修复登录bug、分析日志、生成测试报告",
    "max_parallelism": 3,
    "requested_agent": "auto"
  }'

# 集群任务状态
curl http://localhost:8000/cluster/{cluster_id}

# 广播事件(测试EventBus)
curl -X POST http://localhost:8000/events/broadcast \
  -H "Content-Type: application/json" \
  -d '{"event_type": "test", "payload": {"msg": "hello"}}'
```

---

## 🔧 核心模块详解

### 1. cluster_dispatcher.py — 集群调度器

```python
from backend.cluster_dispatcher import ClusterDispatcher
from backend.models import AgentChoice, TaskStatus
from backend.storage import TaskRepository
from backend.workers import WorkerClient

# ─────────────────────────────────────────────────
# 双模式调度器
# ─────────────────────────────────────────────────

dispatcher = ClusterDispatcher(
    repository=TaskRepository('data/task.db'),
    worker_client=WorkerClient(),
    availability_probe=lambda agent: True,  # 可用性检查
    cluster_orchestrator=ClusterOrchestrator(),
    capability_registry=UnifiedCapabilityRegistry()
)

# ── 模式1: 同步执行(兼容旧API) ──────────────────────────

# 单个任务同步执行
dispatcher.run_sync(task_id='task_001')
# 阻塞等待结果

# ── 模式2: 集群并行执行(v2.0新) ─────────────────────────

# 提交并行任务
cluster_id = await dispatcher.submit_cluster_task(
    goal='修复登录bug + 分析访问日志 + 生成测试报告',
    max_parallelism=3,      # 最多3个并行
    requested_agent=AgentChoice.AUTO  # 自动选择Agent
)
# cluster_id = 'cluster_abc123'

# 查询集群状态
status = await dispatcher.get_cluster_status(cluster_id)
# {
#   'cluster_id': 'cluster_abc123',
#   'total_tasks': 3,
#   'parallelism': 3,
#   'status': 'running',
#   'completed': 1,
#   'failed': 0,
#   'results': [...]
# }
```

### 2. TaskRegistry — 任务注册表

```python
from backend.task_registry import TaskRegistry, task_handler

registry = TaskRegistry()

# ─────────────────────────────────────────────────
# 动态任务注册(类型处理器模式)
# ─────────────────────────────────────────────────

@registry.register('code_review')
async def handle_code_review(task: dict) -> dict:
    """代码审查任务处理器"""
    return {
        'agent': 'openclaw',
        'priority': 'high',
        'timeout': 300,
        'actions': ['git diff', 'static analysis', 'report']
    }

@registry.register('document_write')
async def handle_doc_write(task: dict) -> dict:
    """文档编写任务处理器"""
    return {
        'agent': 'openhanako',
        'priority': 'medium',
        'timeout': 600,
        'actions': ['outline', 'write', 'review']
    }

@registry.register('data_analysis')
async def handle_data_analysis(task: dict) -> dict:
    """数据分析任务处理器"""
    return {
        'agent': 'hermes',
        'priority': 'high',
        'timeout': 900,
        'actions': ['load_data', 'analyze', 'visualize']
    }

# 任务执行时自动路由
handler = registry.get_handler(task_type)
result = await handler(task)
```

### 3. EventBus — 事件总线

```python
from backend.event_bus import EventBus, event_handler

bus = EventBus()

# ─────────────────────────────────────────────────
# 发布-订阅模式
# ─────────────────────────────────────────────────

# 订阅任务事件
@bus.subscribe('task.*')
async def on_task_event(event):
    print(f"[Task Event] {event.type}: {event.payload}")
    # 处理任务状态变更

# 订阅Agent健康事件
@bus.subscribe('agent.heartbeat')
async def on_agent_heartbeat(event):
    agent = event.payload['agent']
    last_seen = event.payload['timestamp']
    await agent_health.update_last_seen(agent, last_seen)

# 订阅技能匹配事件
@bus.subscribe('skill.matched')
async def on_skill_match(event):
    skill = event.payload['skill']
    task = event.payload['task']
    print(f"技能 {skill} 匹配任务 {task['id']}")

# 发布事件
await bus.publish('task.submitted', {
    'task_id': 'task_001',
    'goal': '修复登录bug',
    'timestamp': '2026-05-17T14:30:00Z'
})

# 广播到所有订阅者
await bus.broadcast('system.maintenance', {
    'start': '2026-05-18T02:00:00Z',
    'duration': 3600
})
```

### 4. SkillMemory — 技能记忆库

```python
from backend.skill_memory import SkillMemory, SkillTemplate

memory = SkillMemory('data/skills.db')

# ─────────────────────────────────────────────────
# 从历史任务中学习技能
# ─────────────────────────────────────────────────

# 记录成功任务
await memory.record_success(
    goal='修复XX支付接口超时问题',
    agent='openclaw',
    steps=['分析日志', '定位瓶颈', '优化SQL', '上线验证'],
    duration=1800
)

# 匹配相似任务
similar = await memory.match_similar(
    goal='修复用户登录超时报错',
    top_k=3
)
# [{
#   'goal': '修复XX支付接口超时问题',
#   'similarity': 0.82,
#   'steps': ['分析日志', '定位瓶颈', '优化SQL', '上线验证'],
#   'success_rate': 0.95
# }]

# 生成技能模板
template = await memory.generate_template(
    task_type='bug_fix',
    historical_tasks=similar
)
# SkillTemplate(
#   name='API超时问题修复流程',
#   steps=['分析日志→定位瓶颈→优化DB→性能测试→灰度上线'],
#   avg_duration=1800,
#   success_rate=0.92
# )

# 统计技能命中率
stats = await memory.get_skill_stats(agent='openclaw')
# {'total_tasks': 150, 'skill_hits': 120, 'hit_rate': 0.80}
```

### 5. AgentHealth — 健康监控

```python
from backend.agent_health import AgentHealthMonitor

monitor = AgentHealthMonitor(
    heartbeat_interval=30,   # 30秒心跳
    max_missing=3,            # 最多3次丢失
    auto_recover=True         # 自动恢复
)

# ─────────────────────────────────────────────────
# Agent健康状态
# ─────────────────────────────────────────────────

# 记录心跳
await monitor.record_heartbeat('openclaw', pid=12345)
await monitor.record_heartbeat('hermes', pid=67890)

# 检查健康状态
health = await monitor.check_health('openclaw')
# {
#   'agent': 'openclaw',
#   'status': 'healthy',       # healthy | degraded | down
#   'pid': 12345,
#   'last_seen': '2026-05-17T14:30:00Z',
#   'missed_heartbeats': 0,
#   'consecutive_failures': 0
# }

# 获取所有Agent状态
all_health = await monitor.get_all_health()
# [{
#   'agent': 'openclaw', 'status': 'healthy', ...},
#   {'agent': 'openhanako', 'status': 'degraded', ...},
#   {'agent': 'hermes', 'status': 'down', ...}
# ]

# 故障自动转移
if health['status'] == 'down':
    await monitor.trigger_recovery('openclaw')
    # 1. 重启Agent进程
    # 2. 更新Worker注册表
    # 3. 重新分配pending任务
```

---

## 📊 路由决策模型

### RoutingDecision 数据结构

```python
from backend.models import AgentChoice, RoutingDecision

# 每次路由决策的详细信息
decision = RoutingDecision(
    requested_agent=AgentChoice.AUTO,    # 用户请求的Agent
    selected_agent=AgentChoice.OPENCLAW,  # 最终选择的Agent
    routing_reason='skill_match:code_task > openclaw',  # 路由原因
    scheduler_mode='rules',               # rules | ml | cluster
)

# 决策因素权重
ROUTE_WEIGHTS = {
    'skill_match': 0.35,      # 技能匹配度
    'load_balance': 0.25,     # 负载均衡
    'success_rate': 0.20,      # 历史成功率
    'capability': 0.15,       # 能力覆盖度
    'latency': 0.05           # 响应延迟
}
```

### Agent能力矩阵

| Agent | 代码 | 文档 | 数据 | 对话 | 搜索 | 插件 |
|-------|------|------|------|------|------|------|
| **OpenClaw** | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ | ✅ |
| **OpenHanako** | ⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐ | ✅ |
| **Hermes** | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ✅ |

---

## 🧪 TaskStatus 状态机

```
                    ┌─────────────┐
                    │   PENDING   │  任务创建，等待调度
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ WAITING  │ │ RUNNING  │ │ RUNNING  │
        │(等待资源)│ │(执行中)  │ │(集群模式)│
        └────┬─────┘ └────┬─────┘ └────┬─────┘
             │           │            │
             ▼           └─────┬──────┘
        ┌──────────┐           │
        │ RUNNING  │◀──────────┘  资源释放
        └────┬─────┘
             │
    ┌────────┴────────┐
    ▼                 ▼
┌────────┐        ┌────────┐
│ SUCCESS│        │ FAILED │
└────────┘        └────────┘
```

---

## 📡 WebSocket 实时推送

```javascript
// 前端连接
const ws = new WebSocket('ws://localhost:8000/ws/stream');

ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    // msg.type: 'task_update' | 'agent_status' | 'skill_match' | ...
    // msg.payload: {...}
    console.log(`[${msg.type}]`, msg.payload);
};

// 订阅任务事件
ws.send(JSON.stringify({
    action: 'subscribe',
    events: ['task.*', 'agent.heartbeat']
}));
```

---

## 🔧 配置说明

```bash
# .env 配置
# Agent URLs
OPENCLAW_URL=http://localhost:5000
OPENHANAKO_URL=http://localhost:5001
HERMES_URL=http://localhost:8080

# 数据库
TASK_DB_PATH=data/task.db
SKILL_DB_PATH=data/skills.db

# 调度参数
MAX_PARALLELISM=3
HEARTBEAT_INTERVAL=30
MAX_MISSING_HEARTBEATS=3
TASK_TIMEOUT=600

# 微信桥接
WECHAT_ENABLED=false
ILINK_TOKEN=your_token_here
```

---

## 📈 与旧版(v1.x)对比

| 能力 | v1.x | v2.0 |
|------|------|------|
| 单Agent执行 | ✅ | ✅ |
| 多Agent并行 | ❌ | ✅ |
| 集群模式 | ❌ | ✅ |
| EventBus | ❌ | ✅ |
| TaskRegistry | ❌ | ✅ |
| 技能记忆 | ⚠️ 基础 | ✅ 增强 |
| Agent健康监控 | ⚠️ 手动 | ✅ 自动 |
| 微信桥接 | ✅ | ✅ |

---

## 🔗 相关文档

- 📄 [architecture-v2.md](architecture-v2.md) — 架构文档(15KB)
- 📄 [CODE_WIKI.md](CODE_WIKI.md) — 代码百科(27KB)
- 📄 [SCI_FRAMEWORK.md](SCI_FRAMEWORK.md) — SCI论文框架(56KB)
- 📄 [专利技术交底书.md](专利技术交底书.md) — 专利文档(56KB)
- 💻 [backend/app.py](backend/app.py) — FastAPI主应用
- 💻 [backend/cluster_dispatcher.py](backend/cluster_dispatcher.py) — 集群调度器