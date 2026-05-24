import httpx
import asyncio

async def main():
    print("Testing OpenClaw health...")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("http://127.0.0.1:18789/health", timeout=5)
            print(f"  Health: {r.status_code}")
            print(f"  Response: {r.text}")
    except Exception as e:
        print(f"  Error: {e}")
    
    print("\nTesting various POST endpoints...")
    
    endpoints = [
        "http://127.0.0.1:18789/run-task",
        "http://127.0.0.1:18789/api/task",
        "http://127.0.0.1:18789/task",
    ]
    
    payloads = [
        {"task_id": "test1", "task_content": "写个简单的Python脚本"},
        {"task": "写个简单的Python脚本", "task_type": "coding"},
    ]
    
    for url in endpoints:
        for payload in payloads:
            try:
                print(f"\nPOST {url}")
                print(f"  Payload: {payload}")
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.post(url, json=payload, timeout=10)
                    print(f"  Status: {r.status_code}")
                    if r.status_code != 404:
                        print(f"  Response: {r.text}")
            except Exception as e:
                print(f"  Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
