# Local Control Console Design

## Goal

Build a local control console that accepts a user goal, stores a task record, routes the task to `OpenClaw` or `Hermes`, executes it asynchronously, and exposes task history and status in a simple web UI.

## Scope

This first version is intentionally narrow:

- Local-only deployment
- FastAPI backend
- SQLite persistence
- Background asynchronous execution
- HTML status dashboard
- Rule-based routing designed to be replaced later by a scheduler AI

Out of scope for this version:

- Feishu integration
- Real scheduler LLM calls
- Multi-user auth
- Distributed queue infrastructure
- Worker auto-scaling

## Architecture

The system has four focused layers.

### 1. Web Layer

FastAPI provides:

- `GET /` for the HTML dashboard
- `POST /submit-task` to create a task
- `GET /tasks` to list tasks
- `GET /tasks/{id}` to inspect a task

The UI stays thin. It submits tasks and polls for updated state.

### 2. Scheduler Layer

The scheduler layer acts as the future control brain boundary. In this version it does not call an LLM. Instead, it:

- accepts a user goal
- creates a normalized execution plan placeholder
- chooses a target agent using deterministic routing rules
- records scheduling metadata so a real AI scheduler can replace the rule engine later

This keeps the API and storage format stable when we upgrade to automatic decomposition.

### 3. Execution Layer

The execution layer owns:

- background task launching
- worker adapter invocation
- status transitions
- retry-safe result persistence

Worker adapters are HTTP clients with one uniform contract. In this version they may run against stub endpoints or future real `OpenClaw` and `Hermes` services.

### 4. Storage Layer

SQLite stores task metadata, status, scheduler fields, timestamps, target agent, raw result, and error message. The schema is simple and append-friendly so we can later add retry records and audit logs without redesigning the core task table.

## Data Model

One `tasks` table is enough for V0.1/V0.2:

- `id`
- `goal`
- `status`
- `requested_agent`
- `selected_agent`
- `routing_reason`
- `scheduler_mode`
- `plan_summary`
- `result_payload`
- `error_message`
- `created_at`
- `updated_at`

Status values:

- `pending`
- `running`
- `success`
- `failed`

## Routing Rules

The request supports both direct selection and future scheduler flow.

- If the user explicitly picks `openclaw` or `hermes`, respect it.
- If the user picks `auto`, route by lightweight heuristics:
  - keywords like `research`, `summary`, `analysis` prefer `hermes`
  - keywords like `code`, `build`, `fix`, `implement` prefer `openclaw`
  - otherwise default to `hermes`

The response stores the route and reason so later we can compare rule routing against AI routing.

## Background Execution

Task submission should return quickly with a generated `task_id`.

Execution then continues in the background:

1. insert task as `pending`
2. resolve selected agent
3. mark `running`
4. call worker adapter
5. store result and mark `success`, or store error and mark `failed`

This avoids blocking the web request and gives the dashboard stable polling behavior.

## UI Design

The first UI should include:

- a textarea for the user goal
- an agent mode selector with `auto`, `openclaw`, `hermes`
- a submit button
- a task list with status badges
- a detail panel showing route, timestamps, and latest result/error

No framework is needed yet. Plain HTML, CSS, and a little JavaScript are enough.

## Error Handling

- invalid input returns `400`
- missing task returns `404`
- worker adapter exceptions mark the task `failed`
- database initialization runs on app startup and is idempotent

## Testing Strategy

Use TDD for the backend core.

The first tests should cover:

- routing rule selection
- task creation persistence
- status transitions during execution
- API behavior for submit and fetch

UI behavior can stay lightly tested in this first pass; backend correctness matters more.

## File Boundaries

- `backend/app.py`: FastAPI app factory and routes
- `backend/models.py`: request/response models and enums
- `backend/storage.py`: SQLite access and schema setup
- `backend/scheduler.py`: rule-based routing and scheduler metadata generation
- `backend/dispatcher.py`: background execution orchestration
- `backend/workers.py`: worker adapter interface and HTTP invocation
- `frontend/templates/index.html`: dashboard markup
- `frontend/static/app.js`: polling and submit logic
- `frontend/static/styles.css`: dashboard styling
- `tests/`: backend tests

## Evolution Path

This design cleanly upgrades in later versions:

1. replace rule routing with scheduler AI
2. add Feishu webhook input
3. add retries and timeout control
4. add audit logs and richer execution history

The key decision is already baked in: `OpenClaw` and `Hermes` remain executors, while scheduling logic lives above them.
