"""
test_scenarios.py - Agent Mesh 端到端协作测试执行器

用法：
  python test_scenarios.py                  # 执行所有场景
  python test_scenarios.py --scenario 1     # 仅执行场景1
  python test_scenarios.py --mock           # 使用 mock 模式（不调用真实 API）
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

# 确保 backend 可导入
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.orchestrator_agent import OrchestratorAgent, ExecutionMode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ── 测试场景定义 ────────────────────────────────────────────

SCENARIOS = [
    {
        "id": 1,
        "name": "文档 → 代码 → 报告",
        "goal": "分析这个 Python 爬虫脚本的代码质量，找出潜在风险，写一个压测脚本模拟并发请求，最后生成一份中文优化报告。",
        "mode": ExecutionMode.SYNC,
        "expected_actions": ["code", "coding", "documentation"],
        "expected_agents": ["openclaw-agent", "code-agent", "hermes-agent"],
        "validation": lambda r: (
            len(r.get("sub_tasks", [])) >= 3 and
            any("hermes" in (st.get("agent") or "").lower() for st in r.get("sub_tasks", []))
        ),
    },
    {
        "id": 2,
        "name": "对话 → 工具 → 总结",
        "goal": "我最近在学习机器学习，能不能给我规划一个四周学习计划，并且查一下最新的 ML 框架动态。",
        "mode": ExecutionMode.PARALLEL,
        "expected_actions": ["chat", "reasoning", "documentation"],
        "expected_agents": ["openhanako-agent", "hermes-agent"],
        "validation": lambda r: (
            len(r.get("sub_tasks", [])) >= 2
        ),
    },
    {
        "id": 3,
        "name": "跨轮修改（记忆召回）",
        "goal_first": "用 Python 写一个图片下载脚本，支持批量下载和重试机制。",
        "goal_second": "把刚才的脚本改成异步版本，增加并发下载能力。",
        "mode": ExecutionMode.SYNC,
        "expected_actions": ["code", "documentation"],
        "validation": lambda r: (
            len(r.get("sub_tasks", [])) >= 1 and
            r.get("memory_used", False) is True
        ),
    },
    {
        "id": 4,
        "name": "多 Agent 并行争抢",
        "goal": "同时让三个 Agent 各自搜索一个领域的最新资讯：AI Agent、边缘计算、量子计算，最后汇总成三栏对比表。",
        "mode": ExecutionMode.PARALLEL,
        "expected_actions": ["research", "research", "documentation"],
        "expected_agents": ["code-agent", "hermes-agent"],
        "validation": lambda r: (
            len(r.get("sub_tasks", [])) >= 3
        ),
    },
]


# ── 测试执行器 ──────────────────────────────────────────────

class TestRunner:
    def __init__(self, mcp_bus_url: str = "", mock: bool = False):
        self.mock = mock
        self.orch = OrchestratorAgent(mcp_bus_url=mcp_bus_url)
        self.results = []

    async def run_scenario(self, scenario: dict) -> dict:
        """执行单个测试场景，返回结果字典"""
        sid = scenario["id"]
        name = scenario["name"]
        print(f"\n{'='*60}")
        print(f"场景 {sid}: {name}")
        print(f"{'='*60}")

        start = time.time()
        result = {
            "id": sid,
            "name": name,
            "success": False,
            "error": None,
            "steps": [],
            "final_answer": "",
            "duration_ms": 0,
        }

        try:
            # 场景3需要两轮
            if sid == 3:
                print(f"\n  [第一轮] {scenario['goal_first']}")
                r1 = await self.orch.execute(scenario["goal_first"], mode=scenario["mode"])
                print(f"  第一轮完成: {len(r1['sub_tasks'])} subtasks, memory_used={r1.get('memory_used')}")

                print(f"\n  [第二轮] {scenario['goal_second']}")
                r2 = await self.orch.execute(scenario["goal_second"], mode=scenario["mode"])

                result["steps"] = r1["sub_tasks"] + r2["sub_tasks"]
                result["final_answer"] = r2.get("final_answer", "")
                result["duration_ms"] = (time.time() - start) * 1000
                result["success"] = scenario["validation"](r2)
                if not result["success"]:
                    result["error"] = f"validation failed: expected memory_used=True, got {r2.get('memory_used')}"
            else:
                print(f"\n  [执行] {scenario['goal'][:60]}...")
                r = await self.orch.execute(scenario["goal"], mode=scenario["mode"])

                result["steps"] = r["sub_tasks"]
                result["final_answer"] = r.get("final_answer", "")
                result["duration_ms"] = r.get("duration_ms", 0)
                result["memory_used"] = r.get("memory_used", False)
                result["success"] = scenario["validation"](r)

                if not result["success"]:
                    result["error"] = f"validation failed for scenario {sid}"

        except Exception as e:
            logger.exception(f"场景 {sid} 执行异常")
            result["error"] = str(e)

        duration = (time.time() - start) * 1000
        result["total_duration_ms"] = duration

        # 打印结果摘要
        print(f"\n  结果:")
        print(f"    耗时: {duration:.0f}ms")
        print(f"    子任务: {len(result['steps'])}")
        for st in result["steps"]:
            agent_name = st.get("agent", "N/A")
            action = st.get("action", "?")
            has_result = bool(st.get("result"))
            has_error = bool(st.get("error"))
            status = "OK" if has_result and not has_error else ("ERR" if has_error else "EMPTY")
            print(f"    - [{action}] {agent_name}: {status}")
            if has_error:
                print(f"      ERROR: {st['error']}")

        if result["success"]:
            print(f"\n  [PASS] 场景 {sid} 通过")
        else:
            print(f"\n  [FAIL] 场景 {sid} 未通过: {result.get('error')}")

        return result

    async def run_all(self) -> list:
        """执行所有场景"""
        print("\n" + "=" * 60)
        print("Agent Mesh 端到端测试")
        print("=" * 60)

        # 检查总线
        print("\n[0] 检查 MCP 总线...")
        try:
            resp = await self.orch._http.get(f"{self.orch.bus_url}/mcp/health", timeout=5.0)
            data = resp.json()
            print(f"    总线: online_agents={data['online_agents']}, capabilities={data['capabilities']}")
        except Exception as e:
            print(f"    WARNING: 总线连接失败: {e}")
            print("    部分测试可能无法执行")

        # 检查 Agent
        print("\n[0b] 发现已注册 Agent...")
        agents = await self.orch.discover_all_agents()
        if agents:
            for a in agents:
                print(f"    - {a['name']} ({a['agent_id']}): {a['capabilities']}")
        else:
            print("    -- 暂无已注册 Agent")

        print(f"\n[0c] 记忆系统: {'enabled' if self.orch.memory else 'disabled'}")

        results = []
        for scenario in SCENARIOS:
            r = await self.run_scenario(scenario)
            results.append(r)

        # 汇总
        passed = sum(1 for r in results if r["success"])
        total = len(results)
        print(f"\n{'='*60}")
        print(f"测试汇总: {passed}/{total} 通过")
        print(f"{'='*60}")

        for r in results:
            status = "PASS" if r["success"] else "FAIL"
            print(f"  场景 {r['id']}: {status} | {r.get('total_duration_ms', 0):.0f}ms | {r.get('error', '')}")

        return results

    async def close(self):
        await self.orch.close()


# ── CLI 入口 ───────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Agent Mesh 端到端测试")
    parser.add_argument("--scenario", type=int, choices=[1, 2, 3, 4], help="仅运行指定场景")
    parser.add_argument("--mock", action="store_true", help="Mock 模式（不调用真实 API）")
    parser.add_argument("--mcp-bus-url", type=str, default="", help="MCP 总线 URL")
    args = parser.parse_args()

    mcp_bus_url = args.mcp_bus_url or os.environ.get("MCP_BUS_URL", "http://localhost:8000/bus")

    runner = TestRunner(mcp_bus_url=mcp_bus_url, mock=args.mock)

    if args.scenario:
        scenario = SCENARIOS[args.scenario - 1]
        await runner.run_scenario(scenario)
    else:
        await runner.run_all()

    await runner.close()


if __name__ == "__main__":
    asyncio.run(main())