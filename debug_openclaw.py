import httpx
import asyncio
import json

TOKEN = "500fd3a215d87c7d0019ed720317aa956a053235a3adb006"
HOST = "127.0.0.1"
PORT = 18789

async def debug_openclaw():
    print("=" * 60)
    print("Debug OpenClaw API")
    print("=" * 60)
    
    # 测试 1: /v1/chat/completions
    print("\n1. 测试 /v1/chat/completions")
    url = f"http://{HOST}:{PORT}/v1/chat/completions"
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "user", "content": "说'成功'，不要多余的话"}
        ],
        "stream": False
    }
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                url, 
                json=payload,
                headers={"Authorization": f"Bearer {TOKEN}"}
            )
            print(f"  Status: {resp.status_code}")
            print(f"  Response: {resp.text[:500]}")
    except Exception as e:
        print(f"  Error: {e}")
    
    # 测试 2: /tools/invoke
    print("\n2. 测试 /tools/invoke")
    url = f"http://{HOST}:{PORT}/tools/invoke"
    payload = {
        "tool": "sessions_send",
        "action": "send",
        "args": {
            "sessionKey": "main",
            "text": "说'成功'，不要多余的话"
        }
    }
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                url, 
                json=payload,
                headers={"Authorization": f"Bearer {TOKEN}"}
            )
            print(f"  Status: {resp.status_code}")
            print(f"  Response: {resp.text[:500]}")
    except Exception as e:
        print(f"  Error: {e}")
    
    # 测试 3: 检查 /v1/models
    print("\n3. 测试 /v1/models")
    url = f"http://{HOST}:{PORT}/v1/models"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {TOKEN}"})
            print(f"  Status: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("data", [])
                print(f"  可用模型: {[m.get('id') for m in models[:5]]}")
            else:
                print(f"  Response: {resp.text[:300]}")
    except Exception as e:
        print(f"  Error: {e}")

if __name__ == "__main__":
    asyncio.run(debug_openclaw())
