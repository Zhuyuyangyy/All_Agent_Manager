from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, Field


class AgentChoice(StrEnum):
    AUTO = "auto"
    ILIYA = "iliya"
    OPENCLAW = "openclaw"
    HERMES = "hermes"
    OPENHANAKO = "openhanako"


@dataclass(slots=True)
class RoutingDecision:
    requested_agent: AgentChoice
    selected_agent: AgentChoice
    routing_reason: str
    scheduler_mode: str = "rules"


class TaskStatus(StrEnum):
    PENDING = "pending"
    WAITING = "waiting"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass(slots=True)
class TaskCreate:
    goal: str
    requested_agent: AgentChoice = AgentChoice.AUTO


@dataclass(slots=True)
class TaskRecord:
    id: str
    goal: str
    status: TaskStatus
    requested_agent: AgentChoice
    selected_agent: AgentChoice
    routing_reason: str
    scheduler_mode: str
    plan_summary: str
    result_payload: Optional[str]
    error_message: Optional[str]
    created_at: str
    updated_at: str
    retry_count: int = 0
    last_dispatch_attempt_at: Optional[str] = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "id": self.id,
            "goal": self.goal,
            "status": self.status.value,
            "requested_agent": self.requested_agent.value,
            "selected_agent": self.selected_agent.value,
            "routing_reason": self.routing_reason,
            "scheduler_mode": self.scheduler_mode,
            "plan_summary": self.plan_summary,
            "result_payload": self.result_payload,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "retry_count": str(self.retry_count),
            "last_dispatch_attempt_at": self.last_dispatch_attempt_at,
        }


@dataclass(slots=True)
class HermesBusyState:
    agent: str
    pid: int
    task_id: str
    started_at: str
    heartbeat_at: str
    command: str


class SubmitTaskRequest(BaseModel):
    goal: str = Field(min_length=1)
    requested_agent: AgentChoice = AgentChoice.AUTO


class SubmitTaskResponse(BaseModel):
    task_id: str
    status: str
    selected_agent: AgentChoice
    routing_reason: str
