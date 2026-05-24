import os, httpx, asyncio
from pathlib import Path

# Load .env manually (same logic as orchestrator_agent)
def _load_env_file(env_path):
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            continue
        key, _, value = line.partition('=')
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value

_env = Path('D:/ZYY Project/All_Agent_Manager/.env')
_load_env_file(_env)

async def test():
    api_key = os.environ.get('MINIMAX_API_KEY', '')
    print(f'API key present: {bool(api_key)}, first 10 chars: {api_key[:10] if api_key else "NONE"}')

    if not api_key:
        print('ERROR: No API key found')
        return

    try:
        r = await httpx.AsyncClient(timeout=15).post(
            'https://api.minimaxi.chat/v1/text/chatcompletion_v2',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={'model': 'MiniMax-Text-01', 'messages': [{'role': 'user', 'content': 'Say hello in 5 words'}], 'max_tokens': 50},
        )
        print('HTTP Status:', r.status_code)
        print('Raw response:', r.text[:800])
        if r.status_code == 200:
            data = r.json()
            print('Parsed keys:', list(data.keys()))
            print('Full parsed:', data)
    except Exception as e:
        print('Error:', type(e).__name__, str(e)[:300])

asyncio.run(test())