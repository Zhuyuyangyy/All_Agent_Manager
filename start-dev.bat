@echo off
chcp 65001 >nul 2>&1
title All Agent Manager - Dev Mode

echo.
echo ================================================
echo   All Agent Manager  —  Dev Mode
echo ================================================
echo.

cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo [警告] 未找到 venv
    echo.
) else (
    call venv\Scripts\activate.bat
)

echo.
echo 启动开发服务器...
python -m uvicorn backend.app:create_app --factory --host 0.0.0.0 --port 8000 --reload
