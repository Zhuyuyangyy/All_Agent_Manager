# REPRODUCE.md - All_Agent_Manager

## Prerequisites

- **Python**: 3.10+
- **OS**: Linux / Windows
- **GPU**: Not required
- **Node.js**: For frontend (optional)

## Install

```bash
cd All_Agent_Manager
pip install -r requirements.txt
```

Dependencies: anthropic, fastapi, uvicorn, httpx, websockets, numpy, pydantic, pyyaml, openpyxl, pdfplumber, pypdf, Pillow, and more.

## Environment Setup

Copy `.env.example` to `.env` and configure:
```bash
cp .env.example .env
```

**WARNING**: The `.env` file contains a real MiniMax API key. Do NOT commit it. The key should be rotated immediately.

## Smoke Test

```bash
python -m pytest tests/ -v
```

Expected: Tests in `tests/test_app.py`, `tests/test_agent_health.py`, `tests/test_discovery.py`, `tests/test_dispatcher.py`, `tests/test_workers.py` pass.

## Run Server

```bash
cd backend
python app.py
```

Or with uvicorn:
```bash
uvicorn backend.app:app --reload --port 8000
```

## Expected Outputs

- Multi-agent cluster scheduling platform
- Three sub-agents: OpenClaw, OpenHanako, Hermes
- EventBus-driven task routing
- WebSocket real-time updates

## Known Issues

- **SECURITY**: `.env` contains leaked MiniMax API key (`sk-cp-K-...`) - must rotate
- `.env` references local paths: `D:/GITHUB/hermes-agent-2026.4.16/`, `D:/GITHUB/mmx-mcp-server`, `D:/GITHUB/openhanako-main`
- Frontend requires separate `npm install` in `frontend/` directory
- External agent dependencies (OpenClaw, OpenHanako, Hermes) must be running
- Storage directory contains runtime state (chat history, skills)
