# All-Agent Manager V1.0 使用指南

## 📅 版本信息
- **版本号**: V1.0
- **完成日期**: 2026-05-16
- **状态**: 🎉 基础设施完整，可进行 V1.0 演示！

---

## 🎯 已完成的核心功能

### Phase 0 - Phase 15 总结

| 阶段 | 状态 | 说明 |
|------|------|------|
| Phase 0: 系统盘点 | ✅ 完成 | 生成了完整的系统审计文档 |
| Phase 1: 统一协议 | ✅ 已实现 | AgentTask, AgentResult |
| Phase 2: 统一适配器基类 | ✅ 已实现 | BaseAgentAdapter |
| Phase 3: 三个 Agent 适配器 | ✅ 已实现 | OpenClaw, OpenHanoko, Hermes |
| Phase 4: Agent Registry | ✅ 已集成在 Router | 可用的 Agent 注册中心 |
| Phase 5: Agent Router | ✅ 已实现 | 智能路由选择 |
| Phase 6: Dispatch API | ✅ 已实现 | 任务分发接口 |
| Phase 7: Task Store | ✅ 已实现 | 任务持久化存储 |
| Phase 8: 微信入口接入 | ⚠️ 需确认 | 当前代码已接入，建议统一调度 |
| Phase 9: Mock Provider | ✅ 已实现 | 无 API Key 也能运行 |
| Phase 10: 真实 Agent 接入 | ⏳ 暂缓 | 已预留接口 |
| Phase 11: Pipeline 模式 | ✅ 已实现 | 多 Agent 串行编排 |
| Phase 12: Parallel 模式 | ✅ 已实现 | 多 Agent 并行编排 |
| Phase 13: Result Aggregator | ✅ 已实现 | 结果聚合器 |
| Phase 14: Agent MessageBus | ✅ 已实现 | Agent 消息总线 |
| Phase 15: Shared Context | ✅ 已实现 | 共享上下文 |
| Phase 16: 健康监控 | ✅ 已实现 | 完整的健康检查 |
| Phase 17-20: 高级功能 | ⏳ 暂缓 | 可后续迭代 |

---

## 🚀 快速开始

### 1. 启动服务

```bash
# 进入项目目录
cd "d:\ZYY Project\All-Agent Manager"

# 启动服务（Mock 模式，无需配置 API Key）
python -m backend.app
```

服务会在 `http://localhost:8000` 启动

### 2. 访问 Dashboard

打开浏览器访问: `http://localhost:8000`

---

## 📡 API 使用指南

### 1. 基础接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/` | GET | Dashboard 主页 |
| `/ping` | GET | 健康检查 |
| `/api/status` | GET | 系统状态 |

### 2. Agent 相关接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/agents/status` | GET | 查看 Agent 状态 |
| `/router/agents` | GET | 列出所有 Agent |
| `/router/dispatch` | POST | 分发任务 |
| `/router/stats` | GET | 路由统计 |

### 3. 多 Agent 编排接口 (新增)

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/orchestration/execute` | POST | 执行编排任务 |
| `/api/v1/orchestration/create-plan` | POST | 创建执行计划 |
| `/api/v1/orchestration/history` | GET | 编排历史 |
| `/api/v1/orchestration/stats` | GET | 编排统计 |

### 4. 任务相关接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/tasks` | GET | 列出任务 |
| `/tasks/{task_id}` | GET | 获取任务详情 |
| `/tasks/{task_id}/cancel` | POST | 取消任务 |
| `/tasks/{task_id}/retry` | POST | 重试任务 |

---

## 🎬 V1.0 演示场景

### Demo 1: 聊天任务 (Single - OpenHanoko)

**场景**: 用户想找人聊天

**API 请求**:
```bash
curl -X POST http://localhost:8000/api/v1/orchestration/execute \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_001",
    "source": "test",
    "content": "陪我聊聊天，我今天有点焦虑",
    "mode": "single"
  }'
```

**预期流程**:
1. 任务路由到 OpenHanoko
2. OpenHanoko 处理聊天请求
3. 返回友好的回复

---

### Demo 2: 代码任务 (Single - OpenClaw)

**场景**: 想让 OpenClaw 帮着看代码问题

**API 请求**:
```bash
curl -X POST http://localhost:8000/api/v1/orchestration/execute \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_001",
    "source": "test",
    "content": "帮我查看一下 OpenClaw 接口报错的问题",
    "mode": "single"
  }'
```

**预期流程**:
1. 任务路由到 OpenClaw
2. OpenClaw 处理代码问题
3. 返回修复建议

---

### Demo 3: 项目任务 (Single - Hermes)

**场景**: 想要规划项目路线

**API 请求**:
```bash
curl -X POST http://localhost:8000/api/v1/orchestration/execute \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_001",
    "source": "test",
    "content": "规划一下 Phoenix-Evo V1.0 的后续路线",
    "mode": "single"
  }'
```

**预期流程**:
1. 任务路由到 Hermes
2. Hermes 进行项目规划
3. 返回完整的路线图

---

### Demo 4: Pipeline 模式 (Hermes → OpenHanoko)

**场景**: 分析项目并整理成自然友好的表达

**API 请求 (自动创建计划)**:
```bash
curl -X POST http://localhost:8000/api/v1/orchestration/execute \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_001",
    "source": "test",
    "content": "帮我分析一下这个项目，然后整理成我能发给老师的样子",
    "mode": "pipeline"
  }'
```

**或者手动创建计划**:
```bash
curl -X POST http://localhost:8000/api/v1/orchestration/create-plan \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "pipeline",
    "steps": [
      {
        "agent": "hermes",
        "task": "分析项目当前状态和架构"
      },
      {
        "agent": "openhanoko",
        "task": "把分析结果整理成自然友好的表达"
      }
    ],
    "original_task": "帮我分析项目并整理成自然的表达"
  }'
```

**预期流程**:
1. Hermes 分析项目结构
2. OpenHanoko 基于 Hermes 的结果进行优化
3. 返回整理后的最终结果

---

### Demo 5: Parallel 模式 (OpenClaw + Hermes + OpenHanoko)

**场景**: 全面检查项目各方面问题

**API 请求**:
```bash
curl -X POST http://localhost:8000/api/v1/orchestration/execute \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_001",
    "source": "test",
    "content": "全面检查一下这个项目现在缺少什么",
    "mode": "parallel"
  }'
```

**预期流程**:
1. OpenClaw 检查代码结构
2. Hermes 分析项目路线
3. OpenHanoko 整理用户友好的表达
4. ResultAggregator 聚合所有结果
5. 返回完整的检查报告

---

## 🧪 本地测试

### 使用 Demo 测试脚本

项目提供了完整的 Demo 测试脚本，可以运行五个演示场景:

```bash
# 运行所有 Demo
python backend/test_orchestration_demo.py

# 运行单个 Demo
python backend/test_orchestration_demo.py 1  # 聊天任务
python backend/test_orchestration_demo.py 2  # 代码任务
python backend/test_orchestration_demo.py 3  # 项目任务
python backend/test_orchestration_demo.py 4  # Pipeline 模式
python backend/test_orchestration_demo.py 5  # Parallel 模式
```

---

## 📂 文件结构

```
backend/
├── core/
│   ├── task_schema.py     # 统一协议 (AgentTask, AgentResult)
│   ├── base_adapter.py    # 统一适配器基类
│   └── router.py          # Agent Router
├── adapters/
│   ├── openclaw_adapter.py
│   ├── openhanoko_adapter.py
│   └── hermes_adapter.py
├── orchestration/
│   ├── execution_plan.py  # 执行计划
│   ├── orchestrator.py    # 多 Agent 编排器
│   └── aggregator.py      # 结果聚合器
├── bus/
│   ├── message_bus.py     # 消息总线
│   └── shared_context.py  # 共享上下文
├── storage/
│   └── task_store.py      # 增强版任务存储
├── app.py                 # 主应用 (含新增编排 API)
├── wechat_adapter.py
├── wechat_agent.py
└── test_orchestration_demo.py  # Demo 测试脚本
docs/
├── current_system_audit.md       # 系统审计报告
├── agent_integration_inventory.md  # Agent 集成清单
├── PROJECT_PROGRESS_SUMMARY.md  # 项目进度总结
└── V1_0_USAGE_GUIDE.md          # 本文件
```

---

## 🔧 下一步建议

### 短期优先级 (本周)

1. **验证微信入口统一调度**: 确认微信消息完全通过 Agent Router 分发
2. **完善测试覆盖**: 为各模块添加单元测试
3. **错误处理优化**: 增加更多异常处理和降级方案
4. **配置管理**: 增加配置文件支持

### 中期优先级 (2-4周)

1. **真实 Agent 接入**: 接入真实的 OpenClaw, OpenHanoko, Hermes
2. **前端管理面板**: 完善可视化界面
3. **Phoenix-Evo 集成**: 接入经验积累系统
4. **性能优化**: 增加缓存、优化执行流程

### 长期优先级 (1-2个月)

1. **分布式部署**: 支持多节点部署
2. **动态 Agent 注册**: 支持运行时添加/移除 Agent
3. **智能路由优化**: 基于历史数据的路由优化
4. **监控告警**: 完善的监控和告警系统

---

## 📞 联系方式

如有问题，请查看:
1. `docs/current_system_audit.md` - 完整的系统审计
2. `docs/PROJECT_PROGRESS_SUMMARY.md` - 项目进度总结
3. 代码注释 - 各模块均有详细的注释说明

---

🎉 **V1.0 基础设施已就绪，祝你使用愉快！**
