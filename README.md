# All_Agent_Manager

> Unified multi-agent cluster orchestration platform with intelligent routing, parallel execution, and skill memory.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-009688?logo=fastapi&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)
![Status](https://img.shields.io/badge/Status-Active-brightgreen)

## Overview

All_Agent_Manager is a multi-agent cluster orchestration platform that manages multiple specialized agents (OpenClaw, OpenHanako, Hermes) through intelligent task routing, parallel execution, fault recovery, and skill memory. The system evolves from single-agent passive scheduling to a **cluster-aware cooperative调度 architecture** capable of parallel task distribution, load balancing, and autonomous recovery.

The platform introduces a dual-mode dispatcher supporting both legacy synchronous execution and a new cluster-parallel mode. An event-driven architecture built on a publish-subscribe EventBus enables loose coupling between all system components, while a TaskRegistry provides dynamic task type handling through a handler registration pattern. The skill memory system allows the platform to learn from historical task executions and improve routing decisions over time.

All_Agent_Manager is designed as both a practical orchestration tool and a research platform for multi-agent coordination patterns, with supporting documentation for SCI paper framing and patent disclosure.

## Key Features

1. **Cluster Dispatcher** -- Dual-mode scheduler supporting synchronous single-agent execution (legacy compatible) and full parallel cluster execution with configurable parallelism.

2. **EventBus Architecture** -- Publish-subscribe event system enabling loose coupling between modules. Supports task lifecycle events (`task.submitted`, `task.completed`), agent health events (`agent.heartbeat`, `agent.recovered`), and skill events (`skill.matched`).

3. **TaskRegistry with Handler Pattern** -- Dynamic task type registration where handlers define routing rules, priority, timeout, and execution steps for each task category (code review, document writing, data analysis).

4. **Skill Memory System** -- Template-based learning from successful task executions. Matches similar historical tasks, generates reusable skill templates, and tracks hit rates for continuous improvement.

5. **Agent Health Monitoring** -- Heartbeat-based health detection with automatic recovery actions (restart, failover, alert). Tracks healthy/degraded/down states per agent.

6. **Intelligent Routing** -- Multi-factor routing decisions weighted by skill match (35%), load balance (25%), historical success rate (20%), capability coverage (15%), and latency (5%).

7. **WebSocket Real-Time Push** -- Live task status updates, agent health notifications, and skill match events pushed to connected dashboards.

8. **WeChat Bridge Integration** -- iLink protocol adapter for WeChat message routing, enabling task submission and status updates through WeChat.

## Architecture

```
+------------------------------------------------------------------+
|                     All_Agent_Manager v2.0                        |
+------------------------------------------------------------------+
|                                                                  |
|  +----------------+     +-----------------+     +---------------+|
|  |  Dashboard     |---->|   FastAPI       |<----|  WeChat       ||
|  |  Web UI        |     |   app.py        |     |  (iLink)      ||
|  +----------------+     +--------+--------+     +---------------+|
|                                  |                               |
|  +----------------+     +--------v--------+                      |
|  |  EventBus      |<--->|  EventBus V2    |                      |
|  |  (Pub-Sub)     |     |  (Broadcast)    |                      |
|  +-------+--------+     +--------+--------+                      |
|          |                       |                               |
|  +-------v-----------------------v---------------------------+   |
|  |              TaskRegistry (Handler Pattern)               |   |
|  |  +----------+  +----------+  +----------+  +----------+  |   |
|  |  |CodeTask  |  |DocTask   |  |DataTask  |  |  ...     |  |   |
|  |  +----------+  +----------+  +----------+  +----------+  |   |
|  +-----------------------------+-----------------------------+   |
|                                |                                 |
|  +-----------------------------v-----------------------------+   |
|  |           ClusterDispatcher (Dual Mode)                   |   |
|  |  +-----------------+  +-------------------------------+   |   |
|  |  | Sync Mode       |  | Cluster Mode                  |   |   |
|  |  | run_sync()      |  | submit_cluster_task()         |   |   |
|  |  | Single Agent    |  | Full Parallel Execution       |   |   |
|  |  +-----------------+  +-------------------------------+   |   |
|  +-----------------------------+-----------------------------+   |
|                                |                                 |
|  +-----------------------------v-----------------------------+   |
|  |       ClusterOrchestrator + CapabilityRegistry            |   |
|  +-----------------------------+-----------------------------+   |
|                                |                                 |
|          +---------------------+---------------------+          |
|          v                     v                     v          |
|  +--------------+    +--------------+    +--------------+       |
|  |  OpenClaw    |    |  OpenHanako  |    |    Hermes    |       |
|  |  Worker      |    |  Worker      |    |    Worker    |       |
|  +--------------+    +--------------+    +--------------+       |
|                                                                  |
|  +----------------------------------------------------------+   |
|  |              Persistence Layer (SQLite)                   |   |
|  |  TaskRepository | SkillMemory | AgentHealth               |   |
|  +----------------------------------------------------------+   |
+------------------------------------------------------------------+
```

## Tech Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Backend Framework | FastAPI + Uvicorn | REST API with async support |
| Event System | Custom EventBus | Publish-subscribe module communication |
| Database | SQLite | Task, skill, and health persistence |
| Real-Time | WebSocket | Live dashboard updates |
| AI Integration | Anthropic Claude SDK | LLM-powered task execution |
| Document Processing | pdfplumber, python-docx, python-pptx | Multi-format document handling |
| Browser Automation | Playwright | Web-based task execution |
| Data Validation | Pydantic v2 | Request/response schemas |
| Frontend | HTML + JavaScript | Real-time monitoring dashboard |

## Quick Start

### Prerequisites

- Python 3.10 or higher
- pip package manager

### Installation

```bash
git clone <repository-url>
cd All_Agent_Manager

# Install dependencies
pip install -r requirements.txt
```

### Running the Application

```bash
cd backend

# Start in demo mode
python app.py
# Access http://localhost:8000

# For real worker mode, configure .env:
# OPENCLAW_URL=http://localhost:5000
# OPENHANAKO_URL=http://localhost:5001
# HERMES_URL=http://localhost:8080
```

### API Usage

**Sync Mode (Legacy Compatible)**

```bash
# Submit a single task
curl -X POST http://localhost:8000/submit-task \
  -H "Content-Type: application/json" \
  -d '{"goal": "Fix login bug", "requested_agent": "auto"}'

# Query task status
curl http://localhost:8000/task/{task_id}
```

**Cluster Mode (v2.0)**

```bash
# Submit parallel tasks (up to 3 concurrent)
curl -X POST http://localhost:8000/cluster/submit \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Fix login bug, analyze logs, generate test report",
    "max_parallelism": 3,
    "requested_agent": "auto"
  }'

# Query cluster status
curl http://localhost:8000/cluster/{cluster_id}
```

**WebSocket Real-Time Stream**

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/stream');
ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    // msg.type: 'task_update' | 'agent_status' | 'skill_match'
    console.log(`[${msg.type}]`, msg.payload);
};
```

## Project Structure

```
All_Agent_Manager/
+-- backend/
|   +-- app.py                    # FastAPI main application + routes
|   +-- models.py                 # Pydantic models + TaskStatus enum
|   +-- scheduler.py              # Task router (RoutingDecision)
|   +-- cluster_dispatcher.py     # ClusterDispatcher (dual-mode)
|   +-- cluster_orchestrator.py   # ClusterOrchestrator (parallel execution)
|   +-- unified_capability_registry.py  # Agent capability registry
|   +-- storage.py                # SQLite TaskRepository
|   +-- workers.py                # WorkerClient (agent communication)
|   +-- agent_roles.py            # Agent roles + prompt templates
|   +-- task_registry.py          # TaskRegistry (handler pattern)
|   +-- event_bus.py              # EventBus V2 (pub-sub)
|   +-- skill_memory.py           # Skill memory (template learning)
|   +-- agent_health.py           # Agent health monitoring
|   +-- execution_monitor.py      # Execution monitoring (retry/timeout)
|   +-- task_planner.py           # Task decomposition
|   +-- project_discovery.py      # Proactive task discovery
|   +-- plugin_manager.py         # Plugin management
|   +-- replay_engine.py          # Task replay engine
|   +-- evolution_guard.py        # Evolution safety guard
|   +-- bridge_manager.py         # Message bridge management
|   +-- wechat_adapter.py         # WeChat iLink protocol
|   +-- wechat_login.py           # WeChat QR login
|   +-- chat.py                   # AI conversation module
|   +-- context_compressor.py     # Context compression
|   +-- conversation_memory.py    # Conversation memory
|   +-- error_classifier.py       # Error classification
|   +-- knowledge_base.py         # Knowledge base
|   +-- smart_routing.py          # Smart routing logic
|   +-- websocket_events.py       # WebSocket event handling
+-- frontend/
|   +-- index.html                # Real-time monitoring dashboard
+-- docs/
|   +-- HERMES_UPGRADE_SUMMARY.md # Hermes upgrade notes
|   +-- VERIFICATION_REPORT.md    # Verification report
+-- architecture-v2.md            # Architecture documentation
+-- CODE_WIKI.md                  # Code encyclopedia
+-- SCI_FRAMEWORK.md              # SCI paper framework
+-- requirements.txt              # Python dependencies
+-- Dockerfile                    # Container configuration
```

## Agent Capability Matrix

| Agent | Code | Document | Data | Conversation | Search | Plugins |
|-------|------|----------|------|-------------|--------|---------|
| **OpenClaw** | High | Medium | Medium | Low | Medium | Yes |
| **OpenHanako** | Medium | High | Medium | High | Low | Yes |
| **Hermes** | High | High | High | High | High | Yes |

## Task Status Lifecycle

```
                +-------------+
                |   PENDING   |  Task created, awaiting dispatch
                +------+------+
                       |
          +------------+------------+
          v            v            v
    +----------+ +----------+ +----------+
    | WAITING  | | RUNNING  | | RUNNING  |
    | (Resource)| | (Single) | | (Cluster)|
    +----+-----+ +----+-----+ +----+-----+
         |            |            |
         v            +-----+------+
    +----------+           |
    | RUNNING  |<----------+  Resource released
    +----+-----+
         |
    +----+----+
    v         v
+--------+ +--------+
| SUCCESS| | FAILED |
+--------+ +--------+
```

## Configuration

```bash
# .env
OPENCLAW_URL=http://localhost:5000
OPENHANAKO_URL=http://localhost:5001
HERMES_URL=http://localhost:8080

TASK_DB_PATH=data/task.db
SKILL_DB_PATH=data/skills.db

MAX_PARALLELISM=3
HEARTBEAT_INTERVAL=30
MAX_MISSING_HEARTBEATS=3
TASK_TIMEOUT=600

WECHAT_ENABLED=false
ILINK_TOKEN=your_token_here
```

## Benchmarks & Results

Benchmark results pending. Performance targets:

| Metric | Target |
|--------|--------|
| Task routing latency | < 100ms |
| Parallel task throughput | 3 concurrent agents |
| Skill memory hit rate | Improvement over time |
| Agent recovery time | < 30s after failure detection |

## Research & Publications

- **SCI Paper Framework**: Documented in `SCI_FRAMEWORK.md` (56KB)
- **Patent Disclosure**: Documented in patent technical disclosure document
- **Architecture Documentation**: `architecture-v2.md` (15KB)
- **Code Encyclopedia**: `CODE_WIKI.md` (27KB)

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| v1.x Single Agent | Completed | Basic task submission and single-agent execution |
| v2.0 Cluster Mode | Completed | ClusterDispatcher, EventBus, TaskRegistry, SkillMemory |
| v2.1 Enhanced Routing | In Progress | ML-based routing optimization |
| v2.2 Plugin Ecosystem | Planned | Dynamic plugin loading and marketplace |
| v3.0 Distributed Mode | Planned | Multi-node cluster deployment |

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome. Please follow these guidelines:

1. Ensure all existing tests pass
2. Add tests for new functionality
3. Follow the existing code style and architecture patterns
4. Do not commit credentials, `.env` files, or private configuration

## Contact

For questions, collaboration, or research inquiries, please open an issue on the repository.
