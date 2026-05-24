# All-Agent Manager × Hermes-Agent 升级总结

## 概述

参照 hermes-agent 的架构设计，为 All-Agent Manager 新增了三大核心能力模块，显著提升了系统的稳定性、效率和智能化水平。

## 新增模块

### 1. 上下文压缩器 (`backend/context_compressor.py`)

**借鉴来源**: hermes-agent 的 `agent/context_compressor.py`

**核心功能**:
- **自动检测**: 当对话 token 数接近模型上下文窗口的 70% 时自动触发压缩
- **智能剪枝**: 预剪枝旧工具输出（无需 LLM 调用），节省大量 token
- **结构化摘要**: 用 LLM 生成包含"活跃任务"、"已完成操作"、"关键决策"等字段的结构化摘要
- **迭代更新**: 多次压缩时迭代更新摘要，避免信息丢失
- **反抖动保护**: 如果连续两次压缩节省不到 10%，自动暂停避免无限循环

**核心类**:
```python
ContextCompressor(
    context_length=128000,      # 模型上下文窗口
    threshold_percent=0.70,     # 触发压缩的阈值
    protect_first_n=3,          # 保护头部消息数
    tail_token_budget=20000,    # 尾部保护 token 预算
    summary_model="",           # 压缩用模型（空=主模型）
    call_llm_fn=async_fn,       # LLM 调用函数
)
```

**使用方式**: 自动集成到 `ChatManager.send_message()`，无需手动调用。

---

### 2. 错误分类器与智能重试 (`backend/error_classifier.py`)

**借鉴来源**: hermes-agent 的 `agent/error_classifier.py` 和 `agent/retry_utils.py`

**核心功能**:
- **结构化错误分类**: 将 API 错误分为 10 种类型（认证、限流、上下文溢出、服务器错误等）
- **智能恢复策略**: 根据错误类型自动决定重试、压缩上下文、切换模型或放弃
- **抖动退避**: 指数退避 + 随机抖动，防止并发重试风暴（雷群效应）
- **Retry-After 支持**: 自动解析 429 响应的 Retry-After 头

**错误分类枚举**:
```python
class FailoverReason(enum.Enum):
    auth              # 认证失败 → 切换凭证/供应商
    billing           # 额度耗尽 → 立即切换
    rate_limit        # 限流 → 退避后重试
    overloaded        # 服务过载 → 退避后重试
    server_error      # 服务器错误 → 重试
    timeout           # 超时 → 重建连接重试
    context_overflow  # 上下文溢出 → 压缩后重试
    model_not_found   # 模型不存在 → 切换模型
    format_error      # 请求格式错误 → 放弃
    unknown           # 未知 → 退避重试
```

**使用方式**: 自动集成到 `ChatManager.send_message()` 的异常处理中。

---

### 3. 智能模型路由 (`backend/smart_routing.py`)

**借鉴来源**: hermes-agent 的 `agent/smart_model_routing.py`

**核心功能**:
- **复杂度分析**: 根据消息长度、词数、换行数、代码块、URL、关键词等因素计算复杂度分数 (0.0-1.0)
- **自动路由**: 简单消息（问候、短问题）自动走便宜模型，节省成本
- **快速过滤**: 超过字符/词数限制、包含代码/URL 的消息直接走强力模型

**路由决策**:
```python
RoutingDecision(
    use_cheap_model=True,       # 是否使用便宜模型
    reason="简单消息 (复杂度 0.15)",  # 决策原因
    cheap_provider_id="deepseek",    # 廉价供应商 ID
    cheap_model="deepseek-chat",     # 廉价模型名称
)
```

**推荐的廉价模型组合**:
| 组合 | 供应商 | 模型 | 说明 |
|------|--------|------|------|
| deepseek | DeepSeek | deepseek-chat | 性价比极高的中文模型 |
| dashscope_turbo | DashScope | qwen-turbo | 阿里通义千问轻量版 |
| siliconflow | SiliconFlow | deepseek-ai/DeepSeek-V3 | SiliconFlow 上的 DeepSeek V3 |
| groq | Groq | llama-3.3-70b-versatile | 超快推理 |
| ollama_local | Ollama | qwen2.5:7b | 本地零成本 |

---

## 集成到现有系统

### ChatManager 的改进

`backend/chat.py` 的 `ChatManager` 类已全面升级：

1. **初始化**: 自动加载路由配置、初始化压缩器和重试执行器
2. **send_message()**: 集成了智能路由 → 上下文压缩 → 带重试的模型调用
3. **异常处理**: 自动分类错误，上下文溢出时自动压缩后重试

### 新增 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/chat/routing/config` | GET | 获取智能路由配置 |
| `/chat/routing/config` | POST | 更新智能路由配置 |
| `/chat/routing/recommended` | GET | 获取推荐的廉价模型组合 |

### 配置示例

启用智能路由并配置廉价模型：
```json
{
  "enabled": true,
  "cheap_provider_id": "provider_abc123",
  "cheap_model": "deepseek-chat",
  "complexity_threshold": 0.3,
  "max_simple_chars": 160,
  "max_simple_words": 28
}
```

---

## 与 hermes-agent 的对比

| 特性 | hermes-agent | All-Agent Manager (升级后) |
|------|--------------|---------------------------|
| 上下文压缩 | ✅ 完整实现 | ✅ 核心实现 |
| 错误分类 | ✅ 完整实现（含 provider-specific） | ✅ 通用实现 |
| 智能路由 | ✅ 完整实现 | ✅ 核心实现 |
| 抖动退避 | ✅ 完整实现 | ✅ 完整实现 |
| 记忆系统 | ✅ 多 Provider 架构 | ❌ 未实现（计划中） |
| 技能系统 | ✅ 完整实现 | ❌ 未实现（计划中） |
| 提示词安全扫描 | ✅ 完整实现 | ❌ 未实现（计划中） |
| 轨迹记录 | ✅ 完整实现 | ❌ 未实现（计划中） |

---

## 文件清单

新增文件：
- `backend/context_compressor.py` — 上下文压缩器
- `backend/error_classifier.py` — 错误分类器与智能重试
- `backend/smart_routing.py` — 智能模型路由
- `HERMES_UPGRADE_SUMMARY.md` — 本文件

修改文件：
- `backend/chat.py` — 集成三大模块
- `backend/app.py` — 新增路由配置 API 端点

---

## 后续计划

1. **记忆系统**: 借鉴 hermes-agent 的 MemoryManager，实现跨会话记忆
2. **技能系统**: 借鉴 hermes-agent 的 Skill 系统，实现可复用的任务模板
3. **提示词安全扫描**: 借鉴 hermes-agent 的 context file scanning，检测注入攻击
4. **轨迹记录**: 借鉴 hermes-agent 的 trajectory，保存对话轨迹用于训练

---

## 注意事项

1. 所有新模块都设计为**向后兼容** — 如果模块导入失败，系统会以基础模式运行
2. 智能路由默认**关闭**，需要手动启用并配置廉价模型
3. 上下文压缩和错误分类**自动生效**，无需额外配置
4. 压缩器的 LLM 调用会消耗少量 token，但相比节省的 token 是值得的
