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
    print(f'Key: {api_key[:20]}...')

    # Try with additional parameters
    url = 'https://api.minimax.chat/v1/text/chatcompletion_v2'

    # Test 1: With system prompt
    print('\n--- Test 1: System + user prompt ---')
    try:
        r = await httpx.AsyncClient(timeout=20).post(
            url,
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={
                'model': 'MiniMax-Text-01',
                'messages': [
                    {'role': 'system', 'content': 'You are a helpful assistant.'},
                    {'role': 'user', 'content': '将以下任务分解为JSON数组：写一个Python脚本下载图片。只输出JSON不要其他文字。'}
                ],
                'max_tokens': 512,
                'temperature': 0.3,
            },
        )
        print(f'Status: {r.status_code}')
        data = r.json()
        print(f'Keys: {list(data.keys())}')
        print(f'Choices: {data.get("choices")}')
        if data.get('choices'):
            print(f'First choice: {data["choices"][0]}')
    except Exception as e:
        print(f'Error: {e}')

    # Test 2: With proper stream mode off
    print('\n--- Test 2: No system prompt ---')
    try:
        r = await httpx.AsyncClient(timeout=20).post(
            url,
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={
                'model': 'MiniMax-Text-01',
                'messages': [{'role': 'user', 'content': 'List 3 colors. Output only the colors separated by commas.'}],
                'max_tokens': 50,
            },
        )
        print(f'Status: {r.status_code}')
        data = r.json()
        print(f'Choices: {data.get("choices")}')
    except Exception as e:
        print(f'Error: {e}')

    # Test 3: Check if there's a different param needed
    print('\n--- Test 3: With tools/n ---')
    try:
        r = await httpx.AsyncClient(timeout=20).post(
            url,
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={
                'model': 'abab6.5s-chat',
                'messages': [{'role': 'user', 'content': 'Hi'}],
                'max_tokens': 10,
            },
        )
        print(f'Status: {r.status_code}')
        data = r.json()
        print(f'Choices: {data.get("choices")}')
        print(f'Full response: {data}')
    except Exception as e:
        print(f'Error: {e}')

asyncio.run(test())