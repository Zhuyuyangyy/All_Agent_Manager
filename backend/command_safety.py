"""
command_safety.py — 命令执行安全策略

统一管理命令黑名单和安全检测逻辑，供 IliyaAdapter、WeChatAgent、MCP Server 共用。
"""

BLOCKED_COMMANDS = frozenset({
    "rm", "rmdir", "del", "format", "mkfs", "fdisk",
    "shutdown", "reboot", "halt", "poweroff",
    "reg", "regedit", "regsvr32",
    "net user", "net localgroup",
    "taskkill", "kill",
})


def is_command_safe(command: str) -> tuple[bool, str]:
    cmd_lower = command.lower().strip()
    for blocked in BLOCKED_COMMANDS:
        if (cmd_lower.startswith(blocked)
                or f" {blocked}" in cmd_lower
                or f"/{blocked}" in cmd_lower
                or f"\\{blocked}" in cmd_lower):
            return False, f"命令包含被禁止的操作: {blocked}"
    return True, ""
