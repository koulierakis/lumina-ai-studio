from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    queued = "queued"
    planning = "planning"
    awaiting_approval = "awaiting_approval"
    executing = "executing"
    validating = "validating"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    rolled_back = "rolled_back"


class TaskRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=20_000)
    model: str | None = None
    auto_apply: bool = False
    timeout_seconds: int = Field(default=300, ge=30, le=3600)


class PlannedChange(BaseModel):
    path: str
    operation: Literal["create", "modify", "delete"]
    reason: str


class ChangePlan(BaseModel):
    summary: str
    changes: list[PlannedChange] = Field(default_factory=list)
    validation_commands: list[str] = Field(default_factory=list)


class ExecutionReport(BaseModel):
    backup_id: str
    changed_paths: list[str] = Field(default_factory=list)
    validation_commands: list[str] = Field(default_factory=list)


class TaskEvent(BaseModel):
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    phase: TaskStatus
    message: str


class BuildTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    request: TaskRequest
    status: TaskStatus = TaskStatus.queued
    plan: ChangePlan | None = None
    execution: ExecutionReport | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    events: list[TaskEvent] = Field(default_factory=list)

    def transition(self, status: TaskStatus, message: str) -> None:
        self.status = status
        self.updated_at = datetime.now(timezone.utc)
        self.events.append(TaskEvent(phase=status, message=message))
