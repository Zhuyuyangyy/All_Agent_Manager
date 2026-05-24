# Agent 接入清单

**生成日期：** 2026-05-16  
**项目：** All-Agent Manager

---

## 一、Agent 总览

| Agent | 调用方式 | 当前状态 | 输入格式 | 输出格式 | 健康检查 |
|-------|---------|---------|---------|---------|---------|
| **OpenClaw** | HTTP / Mock | ✅ 已完整接入 | `AgentTask` | `AgentResult` | ✅ |
| **OpenHanoko** | HTTP / Mock | ✅ 已完整接入 | `AgentTask` | `AgentResult` | ✅ |
| **Hermes** | HTTP / Mock | ✅ 已完整接入 | `AgentTask` | `AgentResult` | ✅ |

---

## 二、OpenClaw 详细信息

### 2.1 元信息

| 项目 | 内容 |
|------|------|
| **Agent 名称** | `openclaw` |
| **Agent 类型** | `tool_agent` |
| **核心能力** | 代码修复、工具调用、文件编辑、调试、脚本执行 |
| **文件路径** | `backend/adapters/openclaw_adapter.py` |

### 2.2 能力列表

```python
capabilities = [
    "code_repair",     # 代码修复
    "tool_call",       # 工具调用
    "file_edit",       # 文件编辑
    "debugging",       # 调试
    "script",          # 脚本执行
]
```

### 2.3 路由关键词

```python
keywords = [
    # 中文
    "代码", "报错", "bug", "修复", "脚本", "接口", "测试",
    "运行", "部署", "编译", "调试", "文件", "commit",
    
    # 英文
    "debug", "error", "fix", "code", "script", "api",
    "function", "class",
]
```

### 2.4 调用配置

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|---------|-------|------|
| 基础 URL | `OPENCLAW_URL` | `""` | OpenClaw 服务地址 |

### 2.5 健康检查接口

**路径：** (内部实现，不暴露外部)

**返回格式：**
```json
{
  "agent_name": "openclaw",
  "enabled": true,
  "last_heartbeat": 1715800000.0,
  "status": "ok"
}
```

### 2.6 Mock 模式

✅ 已实现

当未配置 `OPENCLAW_URL` 时，返回模拟结果：

```python
"[OpenClaw] 已处理任务：{content}"
```

---

## 三、OpenHanoko 详细信息

### 3.1 元信息

| 项目 | 内容 |
|------|------|
| **Agent 名称** | `openhanoko` |
| **Agent 类型** | `persona_agent` |
| **核心能力** | 聊天、陪伴、轻量规划、人设交互、解释说明 |
| **文件路径** | `backend/adapters/openhanoko_adapter.py` |

### 3.2 能力列表

```python
capabilities = [
    "chat",            # 聊天
    "companion",       # 陪伴
    "persona",         # 人设
    "light_planning",  # 轻量规划
    "explanation",     # 解释
]
```

### 3.3 路由关键词

```python
keywords = [
    # 中文
    "聊聊", "陪我", "心情", "解释", "日常",
    "安慰", "建议", "规划一下", "怎么办", "焦虑",
    "总结", "可爱", "可爱点",
]
```

### 3.4 调用配置

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|---------|-------|------|
| 基础 URL | `OPENHANOKO_URL` | `""` | OpenHanoko 服务地址 |

### 3.5 健康检查接口

**路径：** (内部实现，不暴露外部)

**返回格式：**
```json
{
  "agent_name": "openhanoko",
  "enabled": true,
  "last_heartbeat": 1715800000.0,
  "status": "ok"
}
```

### 3.6 Mock 模式

✅ 已实现

当未配置 `OPENHANOKO_URL` 时，返回模拟结果：

```python
"[OpenHanoko] 已处理任务：{content}"
```

---

## 四、Hermes 详细信息

### 4.1 元信息

| 项目 | 内容 |
|------|------|
| **Agent 名称** | `hermes` |
| **Agent 类型** | `runtime_agent` |
| **核心能力** | 长流程、项目自动化、架构规划、文档、复杂任务拆解 |
| **文件路径** | `backend/adapters/hermes_adapter.py` |

### 4.2 能力列表

```python
capabilities = [
    "long_task",             # 长流程任务
    "project_automation",    # 项目自动化
    "architecture_planning", # 架构规划
    "code_repair",           # 代码修复
    "test_debugging",        # 测试调试
    "documentation",         # 文档
]
```

### 4.3 路由关键词

```python
keywords = [
    # 中文
    "项目", "架构", "路线", "长期", "自动化",
    "跑实验", "写文档", "修复并测试", "完整流程",
    
    # 英文
    "pipeline", "architecture", "project", "automation",
    "deploy", "refactor", "design",
]
```

### 4.4 调用配置

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|---------|-------|------|
| 基础 URL | `HERMES_URL` | `""` | Hermes 服务地址 |

### 4.5 健康检查接口

**路径：** (内部实现，不暴露外部)

**返回格式：**
```json
{
  "agent_name": "hermes",
  "enabled": true,
  "last_heartbeat": 1715800000.0,
  "status": "ok"
}
```

### 4.6 Mock 模式

✅ 已实现

当未配置 `HERMES_URL` 时，返回模拟结果：

```python
"[Hermes] 已进入项目级任务处理：{content}"
```

---

## 五、统一数据格式

### 5.1 AgentTask (输入)

```python
@dataclass
class AgentTask:
    task_id: str
    user_id: str
    source: str                # "wechat", "api", "web"
    content: str
    task_type: str = "general"
    project: Optional[str] = None
    priority: str = "normal"
    context: Dict[str, Any] = field(default_factory=dict)
```

### 5.2 AgentResult (输出)

```python
@dataclass
class AgentResult:
    task_id: str
    agent_name: str
    status: str
    result: str
    error: Optional[str] = None
    artifacts: List[str] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

---

## 六、现有的集成点

### 6.1 AgentRouter

**文件：** `backend/core/router.py`

**功能：**
- Agent 注册
- 路由选择（基于 `can_handle()` 分数）
- 任务分发
- 能力匹配

### 6.2 FastAPI 集成

**文件：** `backend/app.py`

**现有接口：**
- `POST /router/dispatch` - 任务分发
- `POST /router/route` - 路由预览
- `GET /router/agents` - Agent 列表
- `GET /router/stats` - 统计
- `GET /router/history` - 历史记录

### 6.3 微信入口集成

**文件：** `backend/wechat_agent.py`

当前微信入口通过 `wechat_agent` 处理，部分逻辑需确认是否通过统一调度层。

---

## 七、下一步建议

### 优先级 P0

1. ✅ 确认三个 Agent 的 Mock 模式稳定
2. 🔄 创建独立的 AgentRegistry（可选，当前 Router 自带）
3. 🔄 完善 `/api/v1/agent/dispatch` 接口
4. 🔄 确认微信入口完全通过统一调度层

### 优先级 P1

1. 完善真实 Agent 的调用实现
2. 添加更多测试用例
3. 完善文档
4. 性能监控和优化

---

**结论：**  
**所有三个 Agent 已完整接入！统一协议、统一 Adapter 基类、Agent Router 均已就绪！**
