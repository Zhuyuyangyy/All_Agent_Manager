import json
import os

config_path = os.path.expanduser("~/.openclaw/openclaw.json")
with open(config_path, "r", encoding="utf-8") as f:
    cfg = json.load(f)

gw = cfg.setdefault("gateway", {})

if "tools" not in gw:
    gw["tools"] = {}
if "allow" not in gw["tools"]:
    gw["tools"]["allow"] = []

allow_list = gw["tools"]["allow"]
for tool in ["sessions_send", "sessions_list", "sessions_history", "session_status", "agents_list"]:
    if tool not in allow_list:
        allow_list.append(tool)

with open(config_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)

print("Config updated!")
print(f"  gateway.tools.allow = {gw['tools']['allow']}")
print(f"  gateway.http.endpoints.chatCompletions.enabled = {gw.get('http', {}).get('endpoints', {}).get('chatCompletions', {}).get('enabled')}")
