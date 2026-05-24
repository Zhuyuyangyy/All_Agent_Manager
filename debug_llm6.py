import os, httpx, asyncio

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

    url = 'https://api.minimax.chat/v1/text/chatcompletion_v2'

    print('--- Testing MiniMax-M2.7 ---')
    r = await httpx.AsyncClient(timeout=20).post(
        url,
        headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'},
        json={
            'model': 'MiniMax-M2.7',
            'messages': [{'role': 'user', 'content': 'Say hello in 5 words. Only output the words.'}],
            'max_tokens': 30,
        },
    )
    data = r.json()
    print('Full response:')
    import json
    print(json.dumps(data, indent=2, ensure_ascii=False))

    print('')
    print('--- Testing with more output ---')
    r2 = await httpx.AsyncClient(timeout=20).post(
        url,
        headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'},
        json={
            'model': 'MiniMax-M2.7',
            'messages': [{'role': 'user', 'content': 'What is 2+2? Give a short answer.'}],
            'max_tokens': 100,
        },
    )
    data2 = r2.json()
    print(json.dumps(data2, indent=2, ensure_ascii=False))

asyncio.run(test())