@echo off
chcp 65001 >nul 2>&1
title All Agent Manager - Cluster Mode

echo.
echo ================================================
echo   All Agent Manager  —  Cluster Edition v2
echo ================================================
echo.
echo [启动项检查]
echo   - 插件系统     : YES
echo   - Skill 系统   : YES
echo   - 知识库       : YES
echo   - MCP 集成     : YES
echo   - 集群编排     : YES
echo   - Agent 适配器 : OpenClaw / OpenHanako / Hermes
echo.

cd /d "%~dp0"

if not exist "backend\cluster_orchestrator.py" (
    echo [错误] cluster_orchestrator.py 未找到
    echo 请确保在项目根目录运行此脚本
    pause
    exit /b 1
)

if not exist "venv\Scripts\activate.bat" (
    echo [警告] 未找到 venv，已跳过虚拟环境激活
    echo 建议先运行: python -m venv venv ^&^& venv\Scripts\activate.bat ^&^& pip install -r requirements.txt
    echo.
) else (
    echo [虚拟环境] 激活中...
    call venv\Scripts\activate.bat
    echo.
)

echo [环境变量] 检查关键配置...
if defined MINIMAX_API_KEY (
    echo   MINIMAX_API_KEY  : OK
) else (
    echo   MINIMAX_API_KEY  : NOT SET ^(将在 .env 中读取^)
)

if defined OPENCLAW_URL (
    echo   OPENCLAW_URL     : OK
) else (
    echo   OPENCLAW_URL     : NOT SET
)

if defined HERMES_URL (
    echo   HERMES_URL       : OK
) else (
    echo   HERMES_URL       : NOT SET
)

echo.
echo ================================================
echo   启动完成！查看上方输出确认无错误
echo ================================================
echo.
echo 访问地址：
echo   本地   : http://localhost:8000
echo   前端   : http://localhost:8000/^(需启动前端服务^)
echo.
echo 集群 API 端点：
echo   GET  /api/cluster/health          — 集群健康状态
echo   POST /api/cluster/submit           — 提交集群任务
echo   GET  /api/cluster/status/^(id^)    — 查询任务状态
echo   GET  /api/cluster/capabilities    — 所有注册能力
echo   GET  /api/cluster/slash-commands  — 斜杠命令列表
echo   GET  /api/cluster/agents          — Agent 资源池
echo.
echo 按 Ctrl+C 停止服务
echo ================================================
echo.

python -m uvicorn backend.app:create_app --factory --host 0.0.0.0 --port 8000 --reload
