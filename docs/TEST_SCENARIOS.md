# Agent Mesh 端到端协作测试场景

> 验证四个 MCP Agent 的真实协作链：code-agent / hermes-agent / openclaw-agent / openhanako-agent

---

## 测试场景 1：文档 → 代码 → 报告

**用户需求**：
> "分析这个 Python 爬虫脚本的代码质量，找出潜在风险，写一个压测脚本模拟并发请求，最后生成一份中文优化报告。"

**预期 Agent 协作链**：
1. `openclaw_coding` — 读取并分析代码质量风险
2. `code-agent execute_code_task` — 根据风险点编写压测脚本
3. `code-agent execute_code_task` — 实际执行压测脚本
4. `hermes_documentation` — 整合所有结果，生成中文报告

**验证点**：
- [ ] 任务拆解 action 是否正确映射到 tool
- [ ] 链式 context 是否正确传递（分析结果 → 压测脚本 → 执行结果）
- [ ] 最终报告是否由 Hermes 生成

---

## 测试场景 2：对话 → 工具 → 总结

**用户需求**：
> "我最近在学习机器学习，能不能给我规划一个四周学习计划，并且查一下最新的 ML 框架动态。"

**预期 Agent 协作链**：
1. `openhanako_chat` — 回应学习动机，陪伴式对话
2. `openclaw_coding` — 查询最新 ML 框架动态（模拟 web search 或 curl）
3. `hermes_reasoning` — 规划四周学习计划
4. `hermes_documentation` — 生成结构化计划文档

**验证点**：
- [ ] 多 Agent 并行执行（chat + tool 同时触发）
- [ ] 各 Agent 返回格式是否被正确解析
- [ ] 最终计划是否整合了 ML 框架调研结果

---

## 测试场景 3：跨轮修改（记忆召回）

**第一轮**：
> "用 Python 写一个图片下载脚本，支持批量下载和重试机制。"

**预期**：code-agent 生成脚本，hermes 生成使用说明

**第二轮**：
> "把刚才的脚本改成异步版本，增加并发下载能力。"

**预期**：
- `memory.retrieve_context()` 召回第一轮对话
- 主控将召回的脚本内容作为 context 注入
- code-agent 在原脚本基础上重写
- hermes 更新使用说明

**验证点**：
- [ ] 召回是否命中第一轮的代码结果
- [ ] 第二轮 task_description 是否携带了历史脚本
- [ ] 跨轮结果是否正确覆盖（而非重复追加）

---

## 测试场景 4：多 Agent 并行争抢

**用户需求**：
> "同时让三个 Agent 各自搜索一个领域的最新资讯：AI Agent、边缘计算、量子计算，最后汇总成三栏对比表。"

**预期**：
- 三个子任务并行（PARALLEL 模式）
- 每个任务分派给不同 Agent（research 能力）
- 主控聚合三个结果

**验证点**：
- [ ] 并行执行时 agent 发现是否正确（每个 task 单独 discover）
- [ ] 三个结果是否都返回（无遗漏）
- [ ] 聚合结果是否完整

---

## 验收标准

| 场景 | 通过条件 | 关键指标 |
|------|---------|---------|
| 场景1 | 最终报告由 Hermes 生成，包含代码分析+压测结果 | tool 映射正确 |
| 场景2 | chat 和 tool 同时触发，最终计划包含实时资讯 | 并行无阻塞 |
| 场景3 | 第二轮召回第一轮代码，修改后脚本可运行 | memory 命中率 |
| 场景4 | 三个 research 并行完成，汇总表完整 | 无任务丢失 |

---

## 执行日志格式

```json
{
  "scenario": 1,
  "goal": "...",
  "decomposed_steps": [...],
  "agent_assignments": [...],
  "results": [...],
  "final_answer": "...",
  "PASS": true/false,
  "errors": []
}
```