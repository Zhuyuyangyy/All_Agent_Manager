#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试 @agent 格式识别功能"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.wechat_agent import DispatchInfo, AgentChoice
import re

def test_parse_dispatch():
    """测试 _parse_dispatch 函数"""
    # 模拟 _parse_dispatch 函数
    def _parse_dispatch(text: str):
        """解析分发指令"""
        text = text.strip()
        
        # 格式1: @openclaw 任务描述
        match = re.match(r'@\s*(\w+)\s+(.+)', text, re.DOTALL)
        if match:
            agent_name = match.group(1).lower()
            task_text = match.group(2).strip()
            agent_map = {
                "openclaw": AgentChoice.OPENCLAW,
                "openhanako": AgentChoice.OPENHANAKO,
                "hanako": AgentChoice.OPENHANAKO,
                "hermes": AgentChoice.HERMES,
                "iliya": AgentChoice.ILIYA,
            }
            agent = agent_map.get(agent_name)
            if agent and task_text:
                return DispatchInfo(agent=agent, task_text=task_text)
        
        return None
    
    # 测试用例
    test_cases = [
        "@openclaw 写一个简单的Python脚本",
        "@hermes 帮我分析一下这个问题",
        "@openhanako 上网搜点资料",
        "普通聊天内容",
        "没有@符号",
        " @openclaw 前面有空格",
    ]
    
    print("=" * 60)
    print("测试 @agent 格式识别")
    print("=" * 60)
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n测试 {i}: {test}")
        result = _parse_dispatch(test)
        if result:
            print(f"  ✓ 识别成功! Agent: {result.agent.value}, 任务: {result.task_text}")
        else:
            print(f"  ✗ 未识别为分发指令")
    
    print("\n" + "=" * 60)
    print("测试完成！")

if __name__ == "__main__":
    test_parse_dispatch()
