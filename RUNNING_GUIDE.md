# All Agent Manager - 快速运行指南

## 问题诊断

根据检查，你的系统缺少以下必要组件：

### 1. Python 环境未安装
```
错误：`python` command not found
```

### 2. 没有虚拟环境
```
项目根目录下没有 venv 目录
```

## 解决方案

### 方案 1：使用系统 Python（推荐）

如果你已经安装了 Python（通过 python.org 或 Anaconda），直接运行：

```powershell
# 进入项目目录
cd "d:\ZYY Project\All_Agent_Manager"

# 安装依赖
python -m pip install -r requirements.txt

# 启动服务器
python -m uvicorn backend.app:create_app --factory --host 0.0.0.0 --port 8000 --reload
```

### 方案 2：创建虚拟环境

```powershell
# 进入项目目录
cd "d:\ZYY Project\All_Agent_Manager"

# 创建虚拟环境
python -m venv venv

# 激活虚拟环境（Windows）
.\venv\Scripts\activate

# 安装依赖
python -m pip install -r requirements.txt

# 启动服务器
python -m uvicorn backend.app:create_app --factory --host 0.0.0.0 --port 8000 --reload
```

### 方案 3：使用现有 .bat 脚本

```powershell
# 直接双击或运行
start-dev.bat
```

## 前置条件检查清单

在运行项目前，请确保：

- [ ] Python 3.9+ 已安装
- [ ] pip 可用（`python -m pip --version`）
- [ ] 所有环境变量已配置（.env 文件）
- [ ] 端口 8000 可用（未被占用）

## 验证安装

安装完依赖后，运行以下命令验证：

```powershell
# 检查 Python 版本
python --version

# 检查依赖
python -m pip list | grep -E "(fastapi|uvicorn|httpx)"

# 启动服务器（开发模式）
python -m uvicorn backend.app:create_app --factory --reload
```

## 访问 Dashboard

服务器启动后，打开浏览器访问：

- **本地访问**: http://localhost:8000
- **仪表盘**: http://localhost:8000/dashboard
- **API 文档**: http://localhost:8000/docs

## 常见问题

### Q1: 端口 8000 被占用
```powershell
# 查找占用端口的进程
netstat -ano | findstr :8000

# 或者使用其他端口
python -m uvicorn backend.app:create_app --factory --port 8001
```

### Q2: 缺少依赖
```powershell
# 升级 pip
python -m pip install --upgrade pip

# 安装依赖
python -m pip install -r requirements.txt
```

### Q3: .env 文件缺失
复制 `.env.example` 为 `.env` 并填入配置：
```powershell
copy .env.example .env
```

### Q4: 需要 MiniMax API Key
在 `.env` 文件中配置：
```
MINIMAX_API_KEY=your_api_key_here
```

## Agent 状态要求

项目启动后，Agent 的连接状态取决于：

- **OpenClaw**: 需要运行在 http://127.0.0.1:18789
- **OpenHanako**: 需要运行在配置的端口
- **Hermes**: 需要运行在 http://127.0.0.1:8102

如果 Agent 未运行，系统会自动降级到演示模式（Mock mode）。

## 日志查看

查看服务器日志：
```powershell
# 实时查看日志
Get-Content server.log -Wait -Tail 50

# 或在启动时重定向输出
python -m uvicorn backend.app:create_app --factory --reload 2>&1 | Tee-Object -FilePath server.log
```
