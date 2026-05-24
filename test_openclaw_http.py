import http.client
import json
import time

TOKEN = "500fd3a215d87c7d0019ed720317aa956a053235a3adb006"
HOST = "127.0.0.1"
PORT = 18789

def http_req(path, method="GET", data=None, timeout=120):
    conn = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    body = None
    if data is not None:
        body = json.dumps(data)
        headers["Content-Type"] = "application/json"
    start = time.time()
    try:
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        elapsed = time.time() - start
        resp_body = resp.read().decode("utf-8")
        return resp.status, resp_body, elapsed
    except Exception as e:
        elapsed = time.time() - start
        return -1, str(e), elapsed
    finally:
        conn.close()

print("=== Test: /tools/invoke with 'message' action=send ===")
status, body, elapsed = http_req("/tools/invoke", method="POST", data={
    "tool": "message",
    "action": "send",
    "args": {
        "text": "say hi in one word"
    }
}, timeout=180)
print(f"Status: {status}, Time: {elapsed:.1f}s")
try:
    j = json.loads(body)
    print(f"ok={j.get('ok')}")
    if j.get("error"):
        print(f"error: {j['error']}")
    if j.get("result"):
        result = j["result"]
        if isinstance(result, dict):
            content = result.get("content", [])
            for c in content:
                if isinstance(c, dict):
                    print(f"  content type={c.get('type')}, text={str(c.get('text',''))[:300]}")
        else:
            print(f"  result: {str(result)[:300]}")
except:
    print(f"Body: {body[:500]}")
