import asyncio
import json
import websockets

TOKEN = "500fd3a215d87c7d0019ed720317aa956a053235a3adb006"
URL = "ws://127.0.0.1:18789/ws"

async def test_ws_cli():
    async with websockets.connect(URL) as ws:
        print("WebSocket connected (no origin, cli client)!")

        while True:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(msg)

            if data.get("type") == "event" and data.get("event") == "connect.challenge":
                print("Got challenge, sending connect as CLI client...")
                connect_req = {
                    "type": "req",
                    "id": "1",
                    "method": "connect",
                    "params": {
                        "minProtocol": 3,
                        "maxProtocol": 3,
                        "client": {
                            "id": "cli",
                            "displayName": "Agent Manager",
                            "version": "1.0.0",
                            "platform": "win32",
                            "mode": "cli",
                        },
                        "caps": [],
                        "auth": {"token": TOKEN},
                        "role": "operator",
                        "scopes": ["operator.admin"],
                    },
                }
                await ws.send(json.dumps(connect_req))
                print("--> Sent connect request")

                resp = await asyncio.wait_for(ws.recv(), timeout=10)
                resp_data = json.loads(resp)
                ok = resp_data.get("ok")
                auth_info = resp_data.get("payload", {}).get("auth", {})
                print(f"<-- Connect ok={ok}, auth.scopes={auth_info.get('scopes')}")

                if ok:
                    print("=== CLI CONNECTION SUCCESSFUL! ===")

                    chat_req = {
                        "type": "req",
                        "id": "2",
                        "method": "chat.send",
                        "params": {
                            "sessionKey": "main",
                            "message": "say hi in one word",
                            "idempotencyKey": "test-cli-004",
                        },
                    }
                    await ws.send(json.dumps(chat_req))
                    print("--> Sent chat.send request")

                    for i in range(20):
                        try:
                            resp2 = await asyncio.wait_for(ws.recv(), timeout=15)
                            resp2_data = json.loads(resp2)
                            rtype = resp2_data.get("type")
                            event = resp2_data.get("event", "")
                            rid = resp2_data.get("id", "")

                            if rtype == "res" and rid == "2":
                                print(f"<-- chat.send response: ok={resp2_data.get('ok')}")
                                if resp2_data.get("error"):
                                    print(f"    error: {resp2_data['error']}")
                            elif rtype == "event" and event == "chat":
                                payload = resp2_data.get("payload", {})
                                role = payload.get("role", "")
                                text = str(payload.get("text", ""))[:200]
                                print(f"<-- chat event: role={role}, text={text}")
                            else:
                                print(f"<-- [{i}] type={rtype} event={event}")
                        except asyncio.TimeoutError:
                            print(f"No more messages after {i} responses")
                            break
                else:
                    print("=== CLI CONNECTION FAILED ===")
                    err = resp_data.get("error")
                    if err:
                        print(f"Error: {json.dumps(err, indent=2)}")
                break

        await ws.close()
        print("Connection closed.")

asyncio.run(test_ws_cli())
