"""
orchestrator_agent.py - 自研主控 Agent（MCP 统一调度中枢）

核心能力：
  1. 任务拆分（LLM 分解 + action 类型标注）
  2. 记忆管理（ChromaDB 向量存储，跨会话上下文）
  3. 链式流转（将上一步结果注入下一步 context）
  4. 结果聚合（LLM 整合 -> 最终回复）
  5. MCP 统一调度（所有子 Agent 均通过 MCP 总线调度，彻底解耦）

设计原则：
  - 所有子 Agent 统一走 MCP 总线，可随时插拔
  - 主控是纯调度器，不持有任何 Agent 状态
  - 记忆系统可选（ChromaDB），无 API Key 时降级
"""

import os as _os
from pathlib import Path as _Path

def _load_env_file(env_path: _Path) -> None:
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
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            if key and key not in _os.environ:
                _os.environ[key] = value
    except Exception as e:
        print(f"[env] Warning: failed to load {env_path}: {e}")

_env_path = _Path(__file__).resolve().parent.parent / ".env"
_load_env_file(_env_path)

import asyncio
import json
import logging
import os
import time
import uuid
from enum import StrEnum
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

try:
    from backend.conversation_memory import ConversationMemory
    HAS_MEMORY = True
except ImportError:
    HAS_MEMORY = False

MCP_BUS_URL_ENV = "MCP_BUS_URL"
DEFAULT_MCP_BUS_URL = "http://localhost:8000/bus"


class ExecutionMode(StrEnum):
    SYNC = "sync"
    PARALLEL = "parallel"


class OrchestratorAgent:
    """
    自研主控 Agent - MCP 统一调度 + 记忆管理核心

    调度架构（已归一）：
        orchestrator_agent（主控，唯一调度入口）
                |
        MCP Bus（统一协议总线）
                |
        +--------+--------+--------+--------+
        |        |        |        |        |
    code-   hermes-  openclaw- openhanako-
    agent    agent    agent    agent

    记忆层：
        ConversationMemory (ChromaDB)
        add() -> retrieve_context() -> 注入任务拆分提示词
    """

    def __init__(
        self,
        mcp_bus_url: str = "",
        llm_model: str = "minimax/MiniMax-M2.7",
        session_id: str = "",
    ):
        self.bus_url = (mcp_bus_url or os.environ.get(MCP_BUS_URL_ENV) or DEFAULT_MCP_BUS_URL).rstrip("/")
        self.llm_model = llm_model
        self.session_id = session_id or f"sess_{uuid.uuid4().hex[:8]}"
        self._http = httpx.AsyncClient(timeout=120.0)

        if HAS_MEMORY:
            persist_dir = os.environ.get("MEMORY_PERSIST_DIR", "")
            try:
                self.memory = ConversationMemory(
                    persist_dir=persist_dir if persist_dir else ""
                )
                logger.info("[Orchestrator] Memory enabled (ChromaDB)")
            except Exception as e:
                logger.warning(f"[Orchestrator] Memory init failed: {e}, running without memory")
                self.memory = None
        else:
            self.memory = None

        logger.info(
            f"[Orchestrator] session={self.session_id} | "
            f"MCP Bus: {self.bus_url} | "
            f"Memory: {'yes' if self.memory else 'no'}"
        )

    # --- 记忆：存入 / 检索 ---

    async def _remember(self, user_input: str, final_answer: str):
        if self.memory:
            try:
                self.memory.add(
                    session_id=self.session_id,
                    user_message=user_input,
                    assistant_message=final_answer,
                    metadata={"step_count": len(user_input)},
                )
            except Exception as e:
                logger.warning(f"[Orchestrator] memory.add failed: {e}")

    async def _recall(self, user_input: str, k: int = 3) -> str:
        if not self.memory:
            return ""
        try:
            memories = self.memory.retrieve_context(self.session_id, user_input, k=k)
            if memories:
                context = "\n\n[相关历史上下文]\n" + "\n---\n".join(memories)
                logger.debug(f"[Orchestrator] Retrieved {len(memories)} memory records")
                return context
        except Exception as e:
            logger.warning(f"[Orchestrator] memory.retrieve failed: {e}")
        return ""

    # --- 任务拆分 ---

    async def decompose_task(self, user_input: str, memory_context: str = "") -> list[dict]:
        """
        使用 LLM 将用户指令分解为多步骤计划。
        每个步骤的 action 直接对应某个 MCP Agent 的 tool。
        """
        memory_block = f"\n\n[相关历史上下文]\n{memory_context}\n" if memory_context else ""

        prompt = f"""将以下用户需求分解为步骤。每个步骤指定：
  - action: 动作类型（coding | reasoning | documentation | planning | code | script | chat | analysis | research | tool_use | creative）
  - detail: 该步骤的详细描述
  - capabilities: 该步骤需要的核心能力列表（用于 MCP 总线发现）

可用能力：coding, reasoning, documentation, planning, code, script, chat, analysis, research, tool_use, creative, web_search, file_operations

action 映射规则：
  - 复杂推理、架构规划用 reasoning（对应 Hermes）
  - 技术文档、README 生成用 documentation（对应 Hermes）
  - 代码编写、修复、调试用 code（对应 OpenClaw）
  - 脚本执行用 script（对应 OpenClaw）
  - 聊天陪伴、轻规划用 chat（对应 OpenHanako）
  - 联网搜索用 research
  - 文件操作、工具调用用 tool_use
  - 通用分析用 analysis

需求: {user_input}{memory_block}

输出 JSON 数组，不要有其他文字。例如：
[{{"step": 1, "action": "research", "detail": "搜索最新 AI Agent 框架对比", "capabilities": ["research", "web_search"]}}, {{"step": 2, "action": "documentation", "detail": "生成对比报告", "capabilities": ["documentation"]}}]"""

        try:
            resp = await self._call_llm(prompt)
            # MiniMax sometimes wraps JSON in markdown code blocks
            resp_clean = resp.strip()
            if resp_clean.startswith("```"):
                lines = resp_clean.split("\n")
                resp_clean = "\n".join(lines[1:])  # drop first line (```json)
                if resp_clean.endswith("```"):
                    resp_clean = resp_clean[:-3]  # drop last line (```)
                resp_clean = resp_clean.strip()
            result = json.loads(resp_clean)
            if isinstance(result, list) and len(result) > 0:
                return result
        except Exception as e:
            logger.warning(f"[Orchestrator] decompose_task LLM failed: {e}, resp={resp[:200] if 'resp' in dir() else 'N/A'}")

        # Fallback: use keyword heuristics to decompose the task
        return self._fallback_decompose(user_input)

    def _fallback_decompose(self, user_input: str) -> list[dict]:
        """Heuristic decomposition when LLM is unavailable."""
        text = user_input.lower()
        tasks = []
        step = 1

        # Check for coding/scripting tasks
        if any(k in text for k in ["爬虫", "脚本", "代码", "python", "写代码", "异步", "并发", "下载", "脚本"]):
            tasks.append({
                "step": step, "action": "code",
                "detail": f"编写{user_input[:50]}的代码实现",
                "capabilities": ["code", "coding"]
            })
            step += 1

        # Check for analysis tasks
        if any(k in text for k in ["分析", "评估", "质量", "风险", "优化", "检测"]):
            tasks.append({
                "step": step, "action": "analysis",
                "detail": f"分析评估：{user_input[:50]}",
                "capabilities": ["analysis"]
            })
            step += 1

        # Check for documentation tasks
        if any(k in text for k in ["报告", "文档", "总结", "优化报告", "技术文档"]):
            tasks.append({
                "step": step, "action": "documentation",
                "detail": f"生成文档：{user_input[:50]}",
                "capabilities": ["documentation"]
            })
            step += 1

        # Check for reasoning/planning tasks
        if any(k in text for k in ["规划", "计划", "学习", "推理", "研究"]):
            tasks.append({
                "step": step, "action": "reasoning",
                "detail": f"制定计划：{user_input[:50]}",
                "capabilities": ["reasoning", "planning"]
            })
            step += 1

        # Check for chat/companion tasks
        if any(k in text for k in ["学习", "聊天", "陪伴", "规划", "四周"]):
            tasks.append({
                "step": step, "action": "chat",
                "detail": f"聊天陪伴：{user_input[:50]}",
                "capabilities": ["chat", "companion"]
            })
            step += 1

        # Check for research/web tasks
        if any(k in text for k in ["搜索", "查询", "最新", "动态", "资讯", "调研", "对比", "汇总"]):
            # Check for multiple domains (AI Agent, 边缘计算, 量子计算 etc.)
            domains = []
            if "AI" in text or "agent" in text.lower():
                domains.append("AI Agent")
            if "边缘" in text or "edge" in text.lower():
                domains.append("边缘计算")
            if "量子" in text or "quantum" in text.lower():
                domains.append("量子计算")
            if "机器学习" in text or "ML" in text or "machine learning" in text.lower():
                domains.append("机器学习")

            if len(domains) >= 2:
                # Multiple domains: create one research task per domain
                for d in domains:
                    tasks.append({
                        "step": step, "action": "research",
                        "detail": f"搜索调研{d}最新资讯",
                        "capabilities": ["research", "web_search"]
                    })
                    step += 1
                # Add documentation task for the summary table
                tasks.append({
                    "step": step, "action": "documentation",
                    "detail": "汇总成对比表",
                    "capabilities": ["documentation"]
                })
                step += 1
            else:
                tasks.append({
                    "step": step, "action": "research",
                    "detail": f"搜索调研：{user_input[:50]}",
                    "capabilities": ["research", "web_search"]
                })
                step += 1

        # Check for testing tasks
        if any(k in text for k in ["测试", "压测", "模拟并发", " benchmark"]):
            tasks.append({
                "step": step, "action": "code",
                "detail": f"测试脚本：{user_input[:50]}",
                "capabilities": ["code", "testing"]
            })
            step += 1

        # Always add at least one task
        if not tasks:
            tasks.append({
                "step": 1, "action": "reasoning",
                "detail": user_input[:100],
                "capabilities": ["reasoning"]
            })

        # Re-number steps sequentially
        for i, t in enumerate(tasks):
            t["step"] = i + 1
        return tasks

    async def _call_llm(self, prompt: str, system: str = "") -> str:
        api_key = os.environ.get("MINIMAX_API_KEY", "")
        if api_key:
            try:
                return await self._call_minimax(prompt, system)
            except Exception as e:
                logger.warning(f"[Orchestrator] MiniMax LLM call failed: {e}")

        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if openai_key:
            try:
                return await self._call_openai(prompt, system)
            except Exception as e:
                logger.warning(f"[Orchestrator] OpenAI LLM call failed: {e}")

        return f"[Mock] Received: {prompt[:100]}"

    async def _call_minimax(self, prompt: str, system: str = "") -> str:
        api_key = os.environ.get("MINIMAX_API_KEY", "")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = await self._http.post(
            "https://api.minimax.chat/v1/text/chatcompletion_v2",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "MiniMax-M2.7", "messages": messages, "max_tokens": 1024},
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices")
        if not choices or not choices[0].get("message"):
            base = data.get("base_resp", {})
            raise Exception(f"MiniMax API error: {base.get('status_code')} {base.get('status_msg', data)}")
        return choices[0]["message"]["content"]

    async def _call_openai(self, prompt: str, system: str = "") -> str:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = await self._http.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "gpt-4o-mini", "messages": messages, "max_tokens": 1024},
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    # --- MCP 总线交互 ---

    async def discover_agent(self, capability: str) -> Optional[dict]:
        """通过 MCP 总线发现匹配能力的 Agent（返回第一个在线的）"""
        try:
            resp = await self._http.get(
                f"{self.bus_url}/mcp/discover",
                params={"capability": capability},
                timeout=10.0,
            )
            resp.raise_for_status()
            agents = resp.json().get("agents", [])
            for a in agents:
                if a.get("status") == "online":
                    logger.info(f"[Orchestrator] Discovered MCP agent for '{capability}': {a['name']}")
                    return a
        except Exception as e:
            logger.warning(f"[Orchestrator] discover_agent failed for '{capability}': {e}")
        return None

    async def discover_all_agents(self) -> list:
        """获取所有已注册 MCP Agent"""
        try:
            resp = await self._http.get(f"{self.bus_url}/mcp/agents", timeout=10.0)
            resp.raise_for_status()
            return resp.json().get("agents", [])
        except Exception as e:
            logger.warning(f"[Orchestrator] discover_all_agents failed: {e}")
            return []

    async def _invoke_agent(
        self,
        step: dict,
        agent: dict,
        context: str,
    ) -> str:
        """
        通过 MCP 总线调用子 Agent（MCP JSON-RPC 2.0 格式）
        action -> tool 映射由主控根据子 Agent 能力动态决定。
        """
        agent_id = agent.get("agent_id")
        if not agent_id:
            return f"Error: No agent_id for {agent.get('name', 'unknown')}"

        action = step.get("action", "analysis")
        tool_name = self._action_to_tool(action, agent)

        rpc_request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": {
                    "task_description": step.get("detail", ""),
                    "context": context,
                },
            },
            "id": int(time.time() * 1000),
        }

        try:
            resp = await self._http.post(
                f"{self.bus_url}/mcp/invoke/{agent_id}",
                json=rpc_request,
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()

            if "result" in data:
                result = data["result"]
                if isinstance(result, dict):
                    content = result.get("content", [])
                    if content and isinstance(content, list):
                        return content[0].get("text", str(result))
                    return str(result)
                elif isinstance(result, list):
                    return result[0].get("text", str(result)) if result else "Empty response"
                return str(result)
            if "error" in data:
                return f"Error: {data['error']}"
        except httpx.TimeoutException:
            return f"Error: Agent {agent_id} timed out"
        except Exception as e:
            return f"Error: {str(e)}"

        return "No response"

    def _action_to_tool(self, action: str, agent: dict) -> str:
        """
        根据 action 和目标 Agent 的 capability 动态映射到正确的 tool 名。
        每个 MCP Agent 注册时会携带 capabilities，总线可查询。
        """
        # 通用 action -> 基础 tool 映射
        base_map = {
            "coding":        "execute_code_task",
            "tool_use":      "run_shell",
            "creative":      "generate_copy",
            "analysis":       "analyze_data",
            "research":       "web_scrape",
            "reasoning":      "hermes_reasoning",
            "documentation":  "hermes_documentation",
            "planning":       "hermes_reasoning",
            "code":           "openclaw_coding",
            "script":         "openclaw_script",
            "file_edit":      "openclaw_file_edit",
            "chat":           "openhanako_chat",
            "companion":      "openhanako_chat",
            "planning_light": "openhanako_light_planning",
            "intent_recognition":  "iliya_route",
            "task_decomposition":  "iliya_route",
            "agent_routing":       "iliya_route",
            "command_execution":   "iliya_execute",
            "file_read":           "iliya_file_read",
            "file_write":          "iliya_file_write",
            "file_list":           "iliya_file_list",
            "file_operation":      "iliya_file_read",
            "skill_management":    "iliya_skill_list",
            "plugin_management":   "iliya_plugin_list",
        }

        tool = base_map.get(action)
        if tool:
            return tool

        # 兜底：如果 action 不在映射表，从 agent capabilities 推断
        caps = agent.get("capabilities", [])
        for cap in caps:
            if cap in base_map:
                return base_map[cap]

        # 最终兜底
        return "execute_code_task"

    # --- 主执行入口 ---

    async def execute(
        self,
        user_input: str,
        mode: ExecutionMode = ExecutionMode.SYNC,
    ) -> dict:
        """
        1. 检索相关记忆（注入上下文）
        2. LLM 任务拆分
        3. MCP 总线发现 Agent（每个子任务单独发现）
        4. 执行（同步串行 or 并行，链式 context 流）
        5. 聚合结果 -> 存入记忆
        """
        logger.info(f"[Orchestrator] execute(mode={mode}): {user_input[:100]}")
        start = time.time()

        memory_context = await self._recall(user_input, k=3)
        sub_tasks = await self.decompose_task(user_input, memory_context=memory_context)
        logger.info(f"[Orchestrator] Decomposed into {len(sub_tasks)} subtasks")

        # 为每个子任务预分配 MCP Agent
        for st in sub_tasks:
            cap = st.get("capabilities", ["analysis"])[0]
            agent = await self.discover_agent(cap)
            st["_agent"] = agent
            st["_agent_id"] = agent["agent_id"] if agent else None
            if not agent:
                logger.warning(f"[Orchestrator] No MCP agent for capability: {cap}")

        # 执行
        if mode == ExecutionMode.PARALLEL:
            results = await self._execute_parallel(sub_tasks)
        else:
            results = await self._execute_sync(sub_tasks)

        # 聚合
        final = await self._summarize(results, user_input)

        # 存入记忆
        await self._remember(user_input, final)

        duration_ms = (time.time() - start) * 1000
        logger.info(f"[Orchestrator] execute done in {duration_ms:.0f}ms")

        return {
            "original_query": user_input,
            "sub_tasks": [
                {
                    "step": st["step"],
                    "action": st["action"],
                    "detail": st["detail"],
                    "agent": st["_agent"]["name"] if st.get("_agent") else "N/A",
                    "result": (st.get("_result") or "")[:500],
                    "error": st.get("_error"),
                }
                for st in sub_tasks
            ],
            "final_answer": final,
            "duration_ms": duration_ms,
            "memory_used": bool(memory_context),
        }

    async def _execute_sync(self, sub_tasks: list[dict]) -> list[str]:
        """同步串行执行，链式 context 流（结果注入下一步）"""
        results = []
        for st in sub_tasks:
            context = "\n".join(results[-3:]) if results else ""
            agent_id = st.get("_agent_id")

            if not agent_id:
                st["_error"] = "No MCP agent available"
                results.append(f"[{st['action']}] No agent found")
                continue

            result = await self._invoke_agent(st, st["_agent"], context)
            st["_result"] = result
            results.append(result)

        return results

    async def _execute_parallel(self, sub_tasks: list[dict]) -> list[str]:
        """并行执行（结果按 subtask 顺序返回，无 context 链式依赖）"""
        async def exec_one(st: dict):
            if not st.get("_agent_id"):
                st["_error"] = "No MCP agent"
                return f"[{st['action']}] No agent found"
            return await self._invoke_agent(st, st["_agent"], "")

        coros = [exec_one(st) for st in sub_tasks]
        results_raw = await asyncio.gather(*coros, return_exceptions=True)

        results = []
        for st, r in zip(sub_tasks, results_raw):
            if isinstance(r, Exception):
                st["_error"] = str(r)
                st["_result"] = ""
                results.append(f"Error: {str(r)}")
            else:
                st["_result"] = r
                results.append(str(r))

        return results

    # --- 结果聚合 ---

    async def _summarize(self, step_results: list[str], original_query: str) -> str:
        combined = "\n".join(
            f"[Step {i+1}]: {r[:300]}{'...' if len(r) > 300 else ''}"
            for i, r in enumerate(step_results)
        )

        prompt = f"""根据以下执行结果，回答用户原始问题。

原始问题：{original_query}

执行结果：
{combined}

请用简洁清晰的语言总结结果，直接回答用户问题。"""

        try:
            return await self._call_llm(prompt)
        except Exception as e:
            logger.warning(f"[Orchestrator] summarize LLM failed: {e}")
            return combined

    # --- 生命周期 ---

    async def close(self):
        await self._http.aclose()
        logger.info("[Orchestrator] Closed")


# --- 独立运行入口 ---

async def demo():
    print("=" * 60)
    print("Orchestrator Agent - MCP 统一调度 + 记忆演示")
    print("=" * 60)

    orch = OrchestratorAgent()

    print("\n[1] MCP 总线健康状态...")
    try:
        resp = await orch._http.get(f"{orch.bus_url}/mcp/health", timeout=5.0)
        data = resp.json()
        print(f"    online_agents={data['online_agents']}, capabilities={data['capabilities']}")
    except Exception as e:
        print(f"    总线连接失败: {e}")
        print("    启动总线: uvicorn backend.mcp_bus.bus_server:app --port 8000")

    print("\n[2] 记忆系统...")
    if orch.memory:
        print(f"    ChromaDB enabled, records={orch.memory.count()}")
    else:
        print("    未启用")

    print("\n[3] 已注册 MCP Agent...")
    agents = await orch.discover_all_agents()
    for a in agents:
        print(f"    - {a['name']} ({a['agent_id']}): {a['capabilities']}")
    if not agents:
        print("    暂无已注册 Agent")

    print("\n[4] 任务拆分演示...")
    test_goals = [
        "分析这个 GitHub 项目的代码质量并生成修复补丁",
        "搜索最新的 AI Agent 框架并整理对比报告",
        "帮我写一个 Python 图片下载脚本并生成使用说明",
    ]
    for goal in test_goals:
        steps = await orch.decompose_task(goal)
        print(f"\n    需求: {goal}")
        for s in steps:
            print(f"      Step {s['step']}: [{s['action']}] {s['detail'][:60]}...")

    if agents:
        print("\n[5] 执行示例（并行）...")
        result = await orch.execute(
            "搜索 AI Agent 框架对比并生成报告",
            mode=ExecutionMode.PARALLEL,
        )
        print(f"    最终回复: {result['final_answer'][:200]}")
        print(f"    耗时: {result['duration_ms']:.0f}ms | 子任务: {len(result['sub_tasks'])}")

    await orch.close()
    print("\n演示完成")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    asyncio.run(demo())