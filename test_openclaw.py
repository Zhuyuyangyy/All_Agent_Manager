import httpx
import asyncio
import json

async def main():
    base = "http://127.0.0.1:18789"
    
    test_cases = [
        ("/run-task", {"task_id": "test", "task_content": "写个简单的Python脚本"}),
        ("/api/task", {"task": "写个简单的Python脚本", "task_type": "coding"}),
        ("/api/tasks", {"task": "写个简单的Python脚本"}),
        ("/task", {"task": "写个简单的Python脚本"}),
    ]
    
    print("=" * 60)
    print("Testing OpenClaw APIs")
    print("=" * 60)
    for path, payload in test_cases:
        url = base + path
        try:
            print(f"\nPOST {url}")
            print(f"  Payload: {json.dumps(payload, ensure_ascii=False)}")
            
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload, timeout=10)
                print(f"  Status: {resp.status_code}")
                print(f"  Response: {resp.text[:300]}")
                
        except Exception as e:
            print(f"  Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
