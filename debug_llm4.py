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

    # Check API key validity via auth endpoint
    print('\n--- Checking API key validity ---')
    try:
        r = await httpx.AsyncClient(timeout=15).get(
            'https://api.minimax.chat/v1/models',
            headers={'Authorization': f'Bearer {api_key}'},
        )
        print(f'Models status: {r.status_code}')
        print(f'Models: {r.text[:500]}')
    except Exception as e:
        print(f'Error: {e}')

    # Try with a different prompt format - maybe they need role completions
    print('\n--- Testing with role=assistant prompt ---')
    try:
        r = await httpx.AsyncClient(timeout=20).post(
            'https://api.minimax.chat/v1/text/chatcompletion_v2',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={
                'model': 'MiniMax-Text-01',
                'messages': [
                    {'role': 'user', 'content': 'What is 2+2? Answer with just the number.'}
                ],
                'max_tokens': 10,
                'role_info': [{'role': 'user', 'content': 'You are a math assistant.'}]
            },
        )
        print(f'Status: {r.status_code}')
        data = r.json()
        print(f'Keys: {list(data.keys())}')
        print(f'Data: {data}')
    except Exception as e:
        print(f'Error: {e}')

    # Try the embeddings endpoint to verify key works
    print('\n--- Testing embeddings (alt endpoint) ---')
    try:
        r = await httpx.AsyncClient(timeout=20).post(
            'https://api.minimax.chat/v1/text/embeddings',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={'model': 'embo-01', 'text': 'hello'},
        )
        print(f'Embeddings status: {r.status_code}, body: {r.text[:300]}')
    except Exception as e:
        print(f'Error: {e}')

asyncio.run(test())