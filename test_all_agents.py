#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试三个 Agent 的连接状态"""

import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.workers import build_worker_client_from_env
from backend.models import AgentChoice

async def test_agents():
    print("=" * 60)
    print("测试三个 Agent 的连接状态")
    print("=" * 60)
    
    # 构建 worker client
    worker = build_worker_client_from_env()
    
    test_cases = [
        (AgentChoice.OPENCLAW, "说'OpenClaw连接成功'，不要多余的话"),
        (AgentChoice.HERMES, "说'Hermes连接成功'，不要多余的话"),
        (AgentChoice.OPENHANAKO, "说'OpenHanako连接成功'，不要多余的话"),
    ]
    
    for agent, test_message in test_cases:
        print(f"\n{'='*60}")
        print(f"测试 {agent.value}...")
        print(f"{'='*60}")
        
        try:
            print(f"发送测试消息: {test_message}")
            result = await worker.run_task(agent, "test-001", test_message)
            
            if result.ok:
                print(f"✅ {agent.value} 连接成功!")
                print(f"响应内容: {result.payload[:200] if len(result.payload or '') > 200 else result.payload}")
            else:
                print(f"❌ {agent.value} 连接失败!")
                print(f"错误信息: {result.error_message}")
        except Exception as e:
            print(f"❌ {agent.value} 异常: {e}")
    
    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_agents())
