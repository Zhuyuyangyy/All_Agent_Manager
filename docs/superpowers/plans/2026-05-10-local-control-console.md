# Local Control Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local FastAPI control console with SQLite-backed task history, background asynchronous execution, and a simple HTML dashboard for routing tasks to `OpenClaw` or `Hermes`.

**Architecture:** The app stores tasks in SQLite, routes them through a scheduler boundary that currently uses deterministic rules, dispatches worker execution in the background, and exposes both API endpoints and a simple polling dashboard. The scheduler boundary is designed to be replaced later by a real scheduling AI without changing the task submission contract.

**Tech Stack:** Python 3.12, FastAPI, SQLite, pytest, plain HTML/CSS/JavaScript

---

### Task 1: Scaffold the project structure

**Files:**
- Create: `requirements.txt`
- Create: `backend/__init__.py`
- Create: `backend/app.py`
- Create: `backend/models.py`
- Create: `backend/storage.py`
- Create: `backend/scheduler.py`
- Create: `backend/dispatcher.py`
- Create: `backend/workers.py`
- Create: `frontend/templates/index.html`
- Create: `frontend/static/app.js`
- Create: `frontend/static/styles.css`
- Create: `tests/__init__.py`

- [ ] Step 1: Create the minimal dependency manifest with FastAPI, uvicorn, httpx, pytest
- [ ] Step 2: Create the package directories and empty module files
- [ ] Step 3: Create the frontend directories and empty assets

### Task 2: Define task routing behavior with tests first

**Files:**
- Create: `tests/test_scheduler.py`
- Modify: `backend/models.py`
- Modify: `backend/scheduler.py`

- [ ] Step 1: Write a failing test for explicit agent selection being preserved
- [ ] Step 2: Run the single scheduler test and verify it fails
- [ ] Step 3: Implement the minimal routing function and enums
- [ ] Step 4: Run the scheduler test and verify it passes
- [ ] Step 5: Add a failing test for auto-routing heuristics
- [ ] Step 6: Run the scheduler test file and verify the new test fails
- [ ] Step 7: Implement keyword-based auto-routing and routing reason text
- [ ] Step 8: Run the scheduler test file and verify all scheduler tests pass

### Task 3: Add SQLite persistence with tests first

**Files:**
- Create: `tests/test_storage.py`
- Modify: `backend/storage.py`
- Modify: `backend/models.py`

- [ ] Step 1: Write a failing test for inserting and reading back a task
- [ ] Step 2: Run the storage test and verify it fails
- [ ] Step 3: Implement schema creation plus insert/get/list operations
- [ ] Step 4: Run the storage test and verify it passes
- [ ] Step 5: Add a failing test for task status updates
- [ ] Step 6: Run the storage test file and verify the new test fails
- [ ] Step 7: Implement update operations for running/success/failed transitions
- [ ] Step 8: Run the storage test file and verify all storage tests pass

### Task 4: Add dispatcher execution flow with tests first

**Files:**
- Create: `tests/test_dispatcher.py`
- Modify: `backend/dispatcher.py`
- Modify: `backend/workers.py`

- [ ] Step 1: Write a failing test for successful task execution updating status and result
- [ ] Step 2: Run the dispatcher test and verify it fails
- [ ] Step 3: Implement a worker client abstraction and dispatcher execution function
- [ ] Step 4: Run the dispatcher test and verify it passes
- [ ] Step 5: Add a failing test for worker failure updating task status to failed
- [ ] Step 6: Run the dispatcher test file and verify the new test fails
- [ ] Step 7: Implement failure handling and error persistence
- [ ] Step 8: Run the dispatcher test file and verify all dispatcher tests pass

### Task 5: Add API endpoints and HTML dashboard with tests first

**Files:**
- Create: `tests/test_app.py`
- Modify: `backend/app.py`
- Modify: `frontend/templates/index.html`
- Modify: `frontend/static/app.js`
- Modify: `frontend/static/styles.css`

- [ ] Step 1: Write a failing API test for submitting a task and fetching it back
- [ ] Step 2: Run the API test and verify it fails
- [ ] Step 3: Implement the FastAPI app, startup DB init, routes, and template/static serving
- [ ] Step 4: Run the API test and verify it passes
- [ ] Step 5: Add a failing API test for listing tasks with latest status
- [ ] Step 6: Run the app test file and verify the new test fails
- [ ] Step 7: Implement list behavior and the dashboard assets
- [ ] Step 8: Run the app test file and verify all app tests pass

### Task 6: Verify the full project

**Files:**
- Modify: any touched files from earlier tasks if verification exposes issues

- [ ] Step 1: Run `pytest -q`
- [ ] Step 2: Fix any failing tests using root-cause analysis before changing code
- [ ] Step 3: Run `pytest -q` again and confirm all tests pass
- [ ] Step 4: Summarize the delivered endpoints, UI, and extension points
