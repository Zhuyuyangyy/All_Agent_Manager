import os, sys, asyncio

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

import httpx, json

async def test():
    api_key = os.environ.get('MINIMAX_API_KEY', '')
    print('API key present:', bool(api_key), 'prefix:', api_key[:10] if api_key else 'NONE')

    # Test 1: Simple prompt
    print('\n=== Test 1: Simple JSON ===')
    messages = [{"role": "user", "content": "Return JSON array with one item: {\"step\": 1, \"action\": \"code\"}. Only output JSON."}]
    r = await httpx.AsyncClient(timeout=30).post(
        'https://api.minimax.chat/v1/text/chatcompletion_v2',
        headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'},
        json={'model': 'MiniMax-M2.7', 'messages': messages, 'max_tokens': 256},
    )
    data = r.json()
    choices = data.get('choices', [])
    content = choices[0]['message']['content'] if choices else ''
    print('Content repr:', repr(content))
    print('Content:', content[:200])

    # Test 2: The actual prompt from orchestrator (truncated)
    print('\n=== Test 2: Orchestrator prompt ===')
    prompt = """将以下用户需求分解为步骤。每个步骤指定：
  - action: 动作类型（coding | reasoning | documentation | planning | code | script | chat | analysis | research | tool_use | creative）
  - capabilities: 该步骤需要的核心能力列表

可用能力：coding, reasoning, documentation, planning, code, script, chat, analysis, research, tool_use, creative

需求: 写一个Python图片下载脚本，支持批量下载和重试机制

输出 JSON 数组，不要有其他文字。例如：
[{"step": 1, "action": "code", "capabilities": ["code"]}]"""

    messages2 = [{"role": "user", "content": prompt}]
    r2 = await httpx.AsyncClient(timeout=30).post(
        'https://api.minimax.chat/v1/text/chatcompletion_v2',
        headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'},
        json={'model': 'MiniMax-M2.7', 'messages': messages2, 'max_tokens': 1024},
    )
    data2 = r2.json()
    choices2 = data2.get('choices', [])
    content2 = choices2[0]['message']['content'] if choices2 else ''
    print('Content repr:', repr(content2[:300]))
    print('Content:', content2[:300])

    # Test 3: Try parsing
    if content2.strip():
        try:
            parsed = json.loads(content2.strip())
            print('Parsed successfully:', len(parsed), 'items')
        except Exception as e:
            print('Parse failed:', e)
            # Try stripping markdown
            c = content2.strip()
            if c.startswith('```'):
                lines = c.split('\n')
                c = '\n'.join(lines[1:])
            if c.endswith('```'):
                c = c[:-3]
            print('After strip repr:', repr(c[:200]))
            try:
                parsed = json.loads(c.strip())
                print('Parsed after strip:', len(parsed), 'items')
            except Exception as e2:
                print('Still failed:', e2)

asyncio.run(test())