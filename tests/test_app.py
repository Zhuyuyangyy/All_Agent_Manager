from pathlib import Path
import time
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.models import AgentChoice
from backend.workers import DemoWorkerClient


def test_submit_task_and_fetch_task_details():
    app = create_app(database_path=_test_database_path("app-submit"))
    client = TestClient(app)

    submit_response = client.post(
        "/submit-task",
        json={"goal": "Implement the dashboard API", "requested_agent": AgentChoice.AUTO.value},
    )

    assert submit_response.status_code == 200
    submitted = submit_response.json()
    task_id = submitted["task_id"]

    detail_response = client.get(f"/tasks/{task_id}")

    assert detail_response.status_code == 200
    task = detail_response.json()
    assert task["id"] == task_id
    assert task["status"] in {"pending", "running", "success"}
    assert task["selected_agent"] == AgentChoice.OPENCLAW.value


def test_list_tasks_returns_latest_tasks_first():
    app = create_app(database_path=_test_database_path("app-list"))
    client = TestClient(app)

    client.post("/submit-task", json={"goal": "Research orchestration patterns", "requested_agent": "auto"})
    client.post("/submit-task", json={"goal": "Implement API wiring", "requested_agent": "auto"})

    response = client.get("/tasks")

    assert response.status_code == 200
    tasks = response.json()
    assert len(tasks) == 2
    assert tasks[0]["goal"] == "Implement API wiring"
    assert tasks[1]["goal"] == "Research orchestration patterns"


def test_submit_task_marks_hermes_task_waiting_when_probe_reports_busy():
    app = create_app(
        database_path=_test_database_path("app-hermes-busy"),
        worker_client=DemoWorkerClient(),
        availability_probe=lambda agent: agent != AgentChoice.HERMES,
    )
    client = TestClient(app)

    submit_response = client.post(
        "/submit-task",
        json={"goal": "Research orchestration patterns", "requested_agent": AgentChoice.HERMES.value},
    )
    task_id = submit_response.json()["task_id"]

    detail_response = client.get(f"/tasks/{task_id}")
    task = detail_response.json()

    assert detail_response.status_code == 200
    assert task["status"] == "waiting"
    assert task["error_message"] == "Hermes is busy; task is waiting for availability"


def test_waiting_hermes_task_resumes_automatically_when_probe_turns_available():
    state = {"hermes_busy": True}

    def probe(agent: AgentChoice) -> bool:
        return agent != AgentChoice.HERMES or not state["hermes_busy"]

    app = create_app(
        database_path=_test_database_path("app-hermes-resume"),
        worker_client=DemoWorkerClient(),
        availability_probe=probe,
        waiting_scheduler_interval=0.01,
    )

    with TestClient(app) as client:
        submit_response = client.post(
            "/submit-task",
            json={"goal": "Research orchestration patterns", "requested_agent": AgentChoice.HERMES.value},
        )
        task_id = submit_response.json()["task_id"]

        first_detail = client.get(f"/tasks/{task_id}").json()
        assert first_detail["status"] == "waiting"

        state["hermes_busy"] = False

        deadline = time.time() + 1.0
        final_detail = first_detail
        while time.time() < deadline:
            final_detail = client.get(f"/tasks/{task_id}").json()
            if final_detail["status"] == "success":
                break
            time.sleep(0.05)

        assert final_detail["status"] == "success"


def _test_database_path(prefix: str) -> Path:
    temp_dir = Path("tests/.tmp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir / f"{prefix}-{uuid4().hex}.db"
