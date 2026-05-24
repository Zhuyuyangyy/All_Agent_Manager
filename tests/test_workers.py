import asyncio
import json
import os
from pathlib import Path

import httpx

from backend.models import AgentChoice
from backend.workers import (
    DemoWorkerClient,
    HttpWorkerClient,
    LocalCliWorkerClient,
    RoutingWorkerClient,
    build_availability_probe_from_env,
    build_worker_client_from_env,
)


def test_http_worker_client_posts_to_agent_specific_endpoint():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "running_status": "success",
                "result": {"summary": "ok"},
            },
        )

    transport = httpx.MockTransport(handler)
    client = HttpWorkerClient(
        {
            AgentChoice.OPENCLAW: "http://openclaw.local/run-task",
            AgentChoice.HERMES: "http://hermes.local/run-task",
        },
        transport=transport,
    )

    result = asyncio.run(
        client.run_task(
            AgentChoice.OPENCLAW,
            task_id="task-123",
            goal="Implement the worker adapter",
        )
    )

    assert result.ok is True
    assert captured["url"] == "http://openclaw.local/run-task"
    assert captured["body"] == {
        "task_id": "task-123",
        "task_content": "Implement the worker adapter",
        "priority": "normal",
    }
    assert '"summary": "ok"' in result.payload


def test_http_worker_client_returns_failure_for_remote_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "worker unavailable"})

    transport = httpx.MockTransport(handler)
    client = HttpWorkerClient(
        {
            AgentChoice.OPENCLAW: "http://openclaw.local/run-task",
            AgentChoice.HERMES: "http://hermes.local/run-task",
        },
        transport=transport,
    )

    result = asyncio.run(
        client.run_task(
            AgentChoice.HERMES,
            task_id="task-456",
            goal="Research scheduler patterns",
        )
    )

    assert result.ok is False
    assert "503" in result.error_message


def test_build_worker_client_from_env_uses_demo_when_endpoints_missing():
    previous_openclaw = os.environ.pop("OPENCLAW_URL", None)
    previous_hermes = os.environ.pop("HERMES_URL", None)

    try:
        client = build_worker_client_from_env()
    finally:
        if previous_openclaw is not None:
            os.environ["OPENCLAW_URL"] = previous_openclaw
        if previous_hermes is not None:
            os.environ["HERMES_URL"] = previous_hermes

    assert isinstance(client, DemoWorkerClient)


def test_build_worker_client_from_env_uses_http_client_when_endpoints_present():
    previous_openclaw = os.environ.get("OPENCLAW_URL")
    previous_hermes = os.environ.get("HERMES_URL")
    os.environ["OPENCLAW_URL"] = "http://openclaw.local/run-task"
    os.environ["HERMES_URL"] = "http://hermes.local/run-task"

    try:
        client = build_worker_client_from_env()
    finally:
        if previous_openclaw is None:
            os.environ.pop("OPENCLAW_URL", None)
        else:
            os.environ["OPENCLAW_URL"] = previous_openclaw
        if previous_hermes is None:
            os.environ.pop("HERMES_URL", None)
        else:
            os.environ["HERMES_URL"] = previous_hermes

    assert isinstance(client, HttpWorkerClient)


def test_local_cli_worker_client_runs_command_and_parses_json_result():
    captured = {}

    async def fake_runner(command, payload_json: str):
        captured["command"] = command
        captured["payload"] = json.loads(payload_json)
        return 0, json.dumps({"success": True, "result": "cli-ok"}), ""

    client = LocalCliWorkerClient(
        "python D:/Hermes/main.py run-task",
        runner=fake_runner,
    )

    result = asyncio.run(
        client.run_task(
            AgentChoice.HERMES,
            task_id="task-cli-1",
            goal="Research scheduler patterns",
        )
    )

    assert result.ok is True
    assert captured["command"] == "python D:/Hermes/main.py run-task"
    assert captured["payload"] == {
        "task_id": "task-cli-1",
        "task_content": "Research scheduler patterns",
        "priority": "normal",
    }
    assert '"result": "cli-ok"' in result.payload


def test_local_cli_worker_client_returns_failure_for_bad_exit_code():
    async def fake_runner(command, payload_json: str):
        return 1, "", "boom"

    client = LocalCliWorkerClient(
        "python D:/Hermes/main.py run-task",
        runner=fake_runner,
    )

    result = asyncio.run(
        client.run_task(
            AgentChoice.HERMES,
            task_id="task-cli-2",
            goal="Research scheduler patterns",
        )
    )

    assert result.ok is False
    assert "exit code 1" in result.error_message.lower()
    assert "boom" in result.error_message


def test_routing_worker_client_sends_agent_to_mixed_backends():
    calls = []

    class StubWorker:
        def __init__(self, name: str):
            self.name = name

        async def run_task(self, agent: AgentChoice, task_id: str, goal: str):
            calls.append((self.name, agent, task_id, goal))
            return type("Result", (), {"ok": True, "payload": self.name, "error_message": None})()

    client = RoutingWorkerClient(
        {
            AgentChoice.OPENCLAW: StubWorker("http"),
            AgentChoice.HERMES: StubWorker("cli"),
        }
    )

    openclaw_result = asyncio.run(client.run_task(AgentChoice.OPENCLAW, "task-a", "Implement API"))
    hermes_result = asyncio.run(client.run_task(AgentChoice.HERMES, "task-b", "Research docs"))

    assert openclaw_result.payload == "http"
    assert hermes_result.payload == "cli"
    assert calls == [
        ("http", AgentChoice.OPENCLAW, "task-a", "Implement API"),
        ("cli", AgentChoice.HERMES, "task-b", "Research docs"),
    ]


def test_build_worker_client_from_env_uses_mixed_http_and_cli_mode():
    previous_openclaw = os.environ.get("OPENCLAW_URL")
    previous_hermes_url = os.environ.get("HERMES_URL")
    previous_hermes_cli = os.environ.get("HERMES_CLI_COMMAND")
    os.environ["OPENCLAW_URL"] = "http://openclaw.local/run-task"
    os.environ.pop("HERMES_URL", None)
    os.environ["HERMES_CLI_COMMAND"] = "python D:/Hermes/main.py run-task"

    try:
        client = build_worker_client_from_env()
    finally:
        if previous_openclaw is None:
            os.environ.pop("OPENCLAW_URL", None)
        else:
            os.environ["OPENCLAW_URL"] = previous_openclaw
        if previous_hermes_url is None:
            os.environ.pop("HERMES_URL", None)
        else:
            os.environ["HERMES_URL"] = previous_hermes_url
        if previous_hermes_cli is None:
            os.environ.pop("HERMES_CLI_COMMAND", None)
        else:
            os.environ["HERMES_CLI_COMMAND"] = previous_hermes_cli

    assert isinstance(client, RoutingWorkerClient)
    assert isinstance(client.clients[AgentChoice.OPENCLAW], HttpWorkerClient)
    assert isinstance(client.clients[AgentChoice.HERMES], LocalCliWorkerClient)


def test_build_worker_client_from_env_prefers_cli_for_hermes_when_both_are_present():
    previous_openclaw = os.environ.get("OPENCLAW_URL")
    previous_hermes_url = os.environ.get("HERMES_URL")
    previous_hermes_cli = os.environ.get("HERMES_CLI_COMMAND")
    os.environ["OPENCLAW_URL"] = "http://openclaw.local/run-task"
    os.environ["HERMES_URL"] = "http://hermes.local/run-task"
    os.environ["HERMES_CLI_COMMAND"] = "python D:/Hermes/main.py run-task"

    try:
        client = build_worker_client_from_env()
    finally:
        if previous_openclaw is None:
            os.environ.pop("OPENCLAW_URL", None)
        else:
            os.environ["OPENCLAW_URL"] = previous_openclaw
        if previous_hermes_url is None:
            os.environ.pop("HERMES_URL", None)
        else:
            os.environ["HERMES_URL"] = previous_hermes_url
        if previous_hermes_cli is None:
            os.environ.pop("HERMES_CLI_COMMAND", None)
        else:
            os.environ["HERMES_CLI_COMMAND"] = previous_hermes_cli

    assert isinstance(client, RoutingWorkerClient)
    assert isinstance(client.clients[AgentChoice.HERMES], LocalCliWorkerClient)


def test_build_availability_probe_from_env_blocks_hermes_when_busy_file_exists():
    busy_file = Path("tests/.tmp/hermes.busy")
    busy_file.parent.mkdir(parents=True, exist_ok=True)
    busy_file.write_text(
        json.dumps(
            {
                "agent": "Hermes",
                "pid": 12345,
                "task_id": "task-busy",
                "started_at": "2026-05-10T10:30:00+00:00",
                "heartbeat_at": "2026-05-10T10:31:00+00:00",
                "command": "python D:/Hermes/main.py run-task",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    previous_busy_file = os.environ.get("HERMES_BUSY_FILE")
    os.environ["HERMES_BUSY_FILE"] = str(busy_file)

    try:
        probe = build_availability_probe_from_env(
            process_exists=lambda pid: True,
            now_iso=lambda: "2026-05-10T10:31:30+00:00",
        )
        assert probe(AgentChoice.OPENCLAW) is True
        assert probe(AgentChoice.HERMES) is False
    finally:
        if previous_busy_file is None:
            os.environ.pop("HERMES_BUSY_FILE", None)
        else:
            os.environ["HERMES_BUSY_FILE"] = previous_busy_file
        busy_file.unlink(missing_ok=True)


def test_local_cli_worker_client_creates_and_removes_busy_file():
    busy_file = Path("tests/.tmp/hermes-cli.busy")
    busy_file.parent.mkdir(parents=True, exist_ok=True)
    observations = []

    async def fake_runner(command, payload_json: str):
        observations.append(busy_file.exists())
        return 0, json.dumps({"success": True}), ""

    client = LocalCliWorkerClient(
        "python D:/Hermes/main.py run-task",
        busy_file_path=busy_file,
        runner=fake_runner,
    )

    result = asyncio.run(
        client.run_task(
            AgentChoice.HERMES,
            task_id="task-cli-3",
            goal="Research scheduler patterns",
        )
    )

    assert result.ok is True
    assert observations == [True]
    assert busy_file.exists() is False


def test_local_cli_worker_client_writes_json_busy_state():
    busy_file = Path("tests/.tmp/hermes-cli-json.busy")
    snapshots = []

    async def fake_runner(command, payload_json: str):
        snapshots.append(json.loads(busy_file.read_text(encoding="utf-8")))
        return 0, json.dumps({"success": True}), ""

    client = LocalCliWorkerClient(
        "python D:/Hermes/main.py run-task",
        busy_file_path=busy_file,
        runner=fake_runner,
        now_iso=lambda: "2026-05-10T10:31:00+00:00",
        pid_getter=lambda: 4242,
    )

    result = asyncio.run(
        client.run_task(
            AgentChoice.HERMES,
            task_id="task-cli-4",
            goal="Research scheduler patterns",
        )
    )

    assert result.ok is True
    assert snapshots == [
        {
            "agent": "Hermes",
            "pid": 4242,
            "task_id": "task-cli-4",
            "started_at": "2026-05-10T10:31:00+00:00",
            "heartbeat_at": "2026-05-10T10:31:00+00:00",
            "command": "python D:/Hermes/main.py run-task",
        }
    ]
    assert busy_file.exists() is False


def test_build_availability_probe_from_env_cleans_stale_busy_file():
    busy_file = Path("tests/.tmp/hermes-stale.busy")
    busy_file.parent.mkdir(parents=True, exist_ok=True)
    busy_file.write_text(
        json.dumps(
            {
                "agent": "Hermes",
                "pid": 99999,
                "task_id": "task-stale",
                "started_at": "2026-05-10T10:30:00+00:00",
                "heartbeat_at": "2026-05-10T10:30:00+00:00",
                "command": "python D:/Hermes/main.py run-task",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    previous_busy_file = os.environ.get("HERMES_BUSY_FILE")
    previous_stale_seconds = os.environ.get("HERMES_BUSY_STALE_SECONDS")
    os.environ["HERMES_BUSY_FILE"] = str(busy_file)
    os.environ["HERMES_BUSY_STALE_SECONDS"] = "30"
    events = []

    try:
        probe = build_availability_probe_from_env(
            process_exists=lambda pid: False,
            now_iso=lambda: "2026-05-10T10:31:00+00:00",
            logger=lambda message: events.append(message),
        )
        assert probe(AgentChoice.HERMES) is True
    finally:
        if previous_busy_file is None:
            os.environ.pop("HERMES_BUSY_FILE", None)
        else:
            os.environ["HERMES_BUSY_FILE"] = previous_busy_file
        if previous_stale_seconds is None:
            os.environ.pop("HERMES_BUSY_STALE_SECONDS", None)
        else:
            os.environ["HERMES_BUSY_STALE_SECONDS"] = previous_stale_seconds

    assert busy_file.exists() is False
    assert any("stale" in event.lower() for event in events)
