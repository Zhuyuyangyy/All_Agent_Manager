import os, httpx, asyncio

# Load .env
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
    print(f'Key length: {len(api_key)}')
    print(f'Key prefix: {api_key[:15]}')
    print(f'Key suffix: ...{api_key[-10:]}')

    # Try different models/endpoints
    tests = [
        ('MiniMax-Text-01', 'https://api.minimaxi.chat/v1/text/chatcompletion_v2'),
        ('abab6.5s-chat', 'https://api.minimaxi.chat/v1/text/chatcompletion_v2'),
        ('MiniMax-Text-01', 'https://api.minimax.chat/v1/text/chatcompletion_v2'),
    ]

    for model, url in tests:
        print(f'\n--- Testing model={model} url={url} ---')
        try:
            r = await httpx.AsyncClient(timeout=15).post(
                url,
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={'model': model, 'messages': [{'role': 'user', 'content': 'say hello'}], 'max_tokens': 20},
            )
            print(f'Status: {r.status_code}, Body: {r.text[:300]}')
        except Exception as e:
            print(f'Error: {type(e).__name__}: {e}')

asyncio.run(test())