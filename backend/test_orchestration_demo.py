#!/usr/bin/env python3
"""
All-Agent Manager V1.0 演示测试脚本

使用此脚本测试五个演示场景：
1. Demo 1: 聊天任务 (OpenHanoko)
2. Demo 2: 代码任务 (OpenClaw)
3. Demo 3: 项目任务 (Hermes)
4. Demo 4: Pipeline 模式 (Hermes → OpenHanoko)
5. Demo 5: Parallel 模式 (OpenClaw + Hermes + OpenHanoko)
"""

import asyncio
import json
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import os
os.chdir(str(project_root))

async def test_demo_1_single_chat():
    """Demo 1: 聊天任务 (Single)"""
    print("\n" + "="*80)
    print("🎯 Demo 1: 聊天任务 (OpenHanoko)")
    print("="*80)
    
    from backend.orchestration.execution_plan import ExecutionPlan, ExecutionMode
    from backend.orchestration.orchestrator import MultiAgentOrchestrator
    from backend.orchestration.aggregator import ResultAggregator
    from backend.core.router import AgentRouter
    from backend.adapters.openclaw_adapter import OpenClawAdapter
    from backend.adapters.openhanoko_adapter import OpenHanokoAdapter
    from backend.adapters.hermes_adapter import HermesAdapter
    
    # 初始化
    agent_router = AgentRouter()
    agent_router.register(OpenClawAdapter())
    agent_router.register(OpenHanokoAdapter())
    agent_router.register(HermesAdapter())
    
    aggregator = ResultAggregator()
    orchestrator = MultiAgentOrchestrator(agent_router, aggregator)
    
    # 执行
    plan = ExecutionPlan.single(
        plan_id="demo_1_chat",
        agent="hanako",
        task="陪我聊聊天，我今天有点焦虑"
    )
    
    result = await orchestrator.execute(plan)
    
    print(f"\n✅ 状态: {result.status}")
    print(f"📊 最终结果:")
    print(result.final_result)
    
    return result


async def test_demo_2_single_code():
    """Demo 2: 代码任务 (Single)"""
    print("\n" + "="*80)
    print("🔧 Demo 2: 代码任务 (OpenClaw)")
    print("="*80)
    
    from backend.orchestration.execution_plan import ExecutionPlan, ExecutionMode
    from backend.orchestration.orchestrator import MultiAgentOrchestrator
    from backend.orchestration.aggregator import ResultAggregator
    from backend.core.router import AgentRouter
    from backend.adapters.openclaw_adapter import OpenClawAdapter
    from backend.adapters.openhanoko_adapter import OpenHanokoAdapter
    from backend.adapters.hermes_adapter import HermesAdapter
    
    # 初始化
    agent_router = AgentRouter()
    agent_router.register(OpenClawAdapter())
    agent_router.register(OpenHanokoAdapter())
    agent_router.register(HermesAdapter())
    
    aggregator = ResultAggregator()
    orchestrator = MultiAgentOrchestrator(agent_router, aggregator)
    
    # 执行
    plan = ExecutionPlan.single(
        plan_id="demo_2_code",
        agent="openclaw",
        task="帮我查看一下 OpenClaw 接口报错的问题"
    )
    
    result = await orchestrator.execute(plan)
    
    print(f"\n✅ 状态: {result.status}")
    print(f"📊 最终结果:")
    print(result.final_result)
    
    return result


async def test_demo_3_single_project():
    """Demo 3: 项目任务 (Single)"""
    print("\n" + "="*80)
    print("📋 Demo 3: 项目任务 (Hermes)")
    print("="*80)
    
    from backend.orchestration.execution_plan import ExecutionPlan, ExecutionMode
    from backend.orchestration.orchestrator import MultiAgentOrchestrator
    from backend.orchestration.aggregator import ResultAggregator
    from backend.core.router import AgentRouter
    from backend.adapters.openclaw_adapter import OpenClawAdapter
    from backend.adapters.openhanoko_adapter import OpenHanokoAdapter
    from backend.adapters.hermes_adapter import HermesAdapter
    
    # 初始化
    agent_router = AgentRouter()
    agent_router.register(OpenClawAdapter())
    agent_router.register(OpenHanokoAdapter())
    agent_router.register(HermesAdapter())
    
    aggregator = ResultAggregator()
    orchestrator = MultiAgentOrchestrator(agent_router, aggregator)
    
    # 执行
    plan = ExecutionPlan.single(
        plan_id="demo_3_project",
        agent="hermes",
        task="规划一下 Phoenix-Evo V1.0 的后续路线"
    )
    
    result = await orchestrator.execute(plan)
    
    print(f"\n✅ 状态: {result.status}")
    print(f"📊 最终结果:")
    print(result.final_result)
    
    return result


async def test_demo_4_pipeline():
    """Demo 4: Pipeline 模式 (Hermes → OpenHanoko)"""
    print("\n" + "="*80)
    print("🔄 Demo 4: Pipeline 模式 (Hermes → OpenHanoko)")
    print("="*80)
    
    from backend.orchestration.execution_plan import ExecutionPlan, ExecutionMode
    from backend.orchestration.orchestrator import MultiAgentOrchestrator
    from backend.orchestration.aggregator import ResultAggregator
    from backend.core.router import AgentRouter
    from backend.adapters.openclaw_adapter import OpenClawAdapter
    from backend.adapters.openhanoko_adapter import OpenHanokoAdapter
    from backend.adapters.hermes_adapter import HermesAdapter
    
    # 初始化
    agent_router = AgentRouter()
    agent_router.register(OpenClawAdapter())
    agent_router.register(OpenHanokoAdapter())
    agent_router.register(HermesAdapter())
    
    aggregator = ResultAggregator()
    orchestrator = MultiAgentOrchestrator(agent_router, aggregator)
    
    # 执行
    plan = ExecutionPlan.pipeline(
        plan_id="demo_4_pipeline",
        task="帮我分析一下这个项目，然后整理成我能发给老师的样子",
        steps=[
            ("hermes", "分析项目当前状态和架构"),
            ("hanako", "把分析结果整理成自然友好的表达")
        ]
    )
    
    result = await orchestrator.execute(plan)
    
    print(f"\n✅ 状态: {result.status}")
    print(f"📊 最终结果:")
    print(result.final_result)
    
    return result


async def test_demo_5_parallel():
    """Demo 5: Parallel 模式 (OpenClaw + Hermes + OpenHanoko)"""
    print("\n" + "="*80)
    print("⚡ Demo 5: Parallel 模式 (OpenClaw + Hermes + OpenHanoko)")
    print("="*80)
    
    from backend.orchestration.execution_plan import ExecutionPlan, ExecutionMode
    from backend.orchestration.orchestrator import MultiAgentOrchestrator
    from backend.orchestration.aggregator import ResultAggregator
    from backend.core.router import AgentRouter
    from backend.adapters.openclaw_adapter import OpenClawAdapter
    from backend.adapters.openhanoko_adapter import OpenHanokoAdapter
    from backend.adapters.hermes_adapter import HermesAdapter
    
    # 初始化
    agent_router = AgentRouter()
    agent_router.register(OpenClawAdapter())
    agent_router.register(OpenHanokoAdapter())
    agent_router.register(HermesAdapter())
    
    aggregator = ResultAggregator()
    orchestrator = MultiAgentOrchestrator(agent_router, aggregator)
    
    # 执行
    plan = ExecutionPlan.parallel(
        plan_id="demo_5_parallel",
        task="全面检查一下这个项目现在缺少什么",
        steps=[
            ("openclaw", "检查代码结构和接口"),
            ("hermes", "分析项目架构和长期规划"),
            ("hanako", "整理成用户容易理解的表达")
        ]
    )
    
    result = await orchestrator.execute(plan)
    
    print(f"\n✅ 状态: {result.status}")
    print(f"📊 最终结果:")
    print(result.final_result)
    
    return result


async def test_all_demos():
    """运行所有 Demo 测试"""
    print("\n" + "="*80)
    print("🚀 All-Agent Manager V1.0 演示测试")
    print("="*80)
    
    results = []
    
    # 运行所有 Demo
    try:
        results.append(("Demo 1", await test_demo_1_single_chat()))
        results.append(("Demo 2", await test_demo_2_single_code()))
        results.append(("Demo 3", await test_demo_3_single_project()))
        results.append(("Demo 4", await test_demo_4_pipeline()))
        results.append(("Demo 5", await test_demo_5_parallel()))
    except Exception as e:
        print(f"\n❌ 测试过程中出错: {e}")
        import traceback
        traceback.print_exc()
    
    # 总结
    print("\n" + "="*80)
    print("📊 测试总结")
    print("="*80)
    
    for name, result in results:
        status_str = "✅ 通过" if result.success else "❌ 失败"
        print(f"{name}: {status_str}")
    
    print("\n🎉 所有演示测试完成！")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="All-Agent Manager 演示测试")
    parser.add_argument("demo", nargs="?", type=int, choices=[1, 2, 3, 4, 5],
                        help="运行特定 Demo (1-5)")
    
    args = parser.parse_args()
    
    # 运行特定 Demo 或全部
    if args.demo == 1:
        asyncio.run(test_demo_1_single_chat())
    elif args.demo == 2:
        asyncio.run(test_demo_2_single_code())
    elif args.demo == 3:
        asyncio.run(test_demo_3_single_project())
    elif args.demo == 4:
        asyncio.run(test_demo_4_pipeline())
    elif args.demo == 5:
        asyncio.run(test_demo_5_parallel())
    else:
        asyncio.run(test_all_demos())
