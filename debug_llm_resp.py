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

import httpx

async def test():
    api_key = os.environ.get('MINIMAX_API_KEY', '')
    messages = [{"role": "user", "content": "将以下任务分解为步骤，输出JSON：写一个Python图片下载脚本，支持批量下载和重试机制。只输出JSON不要其他内容。"}]

    r = await httpx.AsyncClient(timeout=30).post(
        'https://api.minimax.chat/v1/text/chatcompletion_v2',
        headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'},
        json={'model': 'MiniMax-M2.7', 'messages': messages, 'max_tokens': 1024},
    )
    data = r.json()
    choices = data.get('choices', [])
    if choices:
        content = choices[0]['message']['content']
        print('Raw content:')
        print(repr(content[:300]))
        print()
        print('Content:')
        print(content[:300])
    else:
        print('No choices:', data)

asyncio.run(test())