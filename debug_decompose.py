import os, httpx, asyncio, json

_env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(_env_path):
    for line in open(_env_path, encoding='utf-8'):
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value

async def test():
    api_key = os.environ.get('MINIMAX_API_KEY', '')
    prompt = """将以下用户需求分解为步骤。每个步骤指定：
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

需求: 分析这个 Python 爬虫脚本的代码质量，找出潜在风险，写一个压测脚本模拟并发请求，最后生成一份中文优化报告。

输出 JSON 数组，不要有其他文字。例如：
[{"step": 1, "action": "research", "detail": "搜索最新 AI Agent 框架对比", "capabilities": ["research", "web_search"]}, {"step": 2, "action": "documentation", "detail": "生成对比报告", "capabilities": ["documentation"]}]"""

    messages = [{"role": "user", "content": prompt}]

    print('Sending to MiniMax-M2.7...')
    r = await httpx.AsyncClient(timeout=60).post(
        'https://api.minimax.chat/v1/text/chatcompletion_v2',
        headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'},
        json={'model': 'MiniMax-M2.7', 'messages': messages, 'max_tokens': 1024},
    )
    print('Status:', r.status_code)
    data = r.json()
    print('Keys:', list(data.keys()))
    choices = data.get('choices')
    print('Choices:', choices)
    if choices:
        content = choices[0].get('message', {}).get('content', '')
        print('Content:', content[:500])
        print('---')
        print('Parsed JSON attempt:')
        try:
            parsed = json.loads(content)
            print(json.dumps(parsed, indent=2, ensure_ascii=False))
        except Exception as e:
            print('JSON parse failed:', e)
            print('Raw content repr:', repr(content[:200]))
    else:
        print('No choices - full response:')
        print(json.dumps(data, indent=2, ensure_ascii=False)[:1000])

asyncio.run(test())