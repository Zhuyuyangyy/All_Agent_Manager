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

    models_to_test = ['MiniMax-M2.7', 'MiniMax-M2.7-highspeed', 'MiniMax-M2.5', 'MiniMax-M2.5-highspeed']
    url = 'https://api.minimax.chat/v1/text/chatcompletion_v2'

    for model in models_to_test:
        print('')
        print('--- Testing', model, '---')
        try:
            r = await httpx.AsyncClient(timeout=20).post(
                url,
                headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'},
                json={
                    'model': model,
                    'messages': [{'role': 'user', 'content': 'Say hello in 5 words. Only output the words.'}],
                    'max_tokens': 30,
                },
            )
            data = r.json()
            choices = data.get('choices')
            if choices:
                content = choices[0].get('message', {}).get('content', '')
                print('Status:', r.status_code, '| Response:', content)
            else:
                base = data.get('base_resp', {})
                err_msg = base.get('status_msg', str(data))
                print('Status:', r.status_code, '| Error:', err_msg)
        except Exception as e:
            print('Error:', e)

asyncio.run(test())