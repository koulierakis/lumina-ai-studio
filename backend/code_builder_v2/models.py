from __future__ import annotations

from datetime import UTC, datetime
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


class ProjectStatus(str, Enum):
    creating = "creating"
    generating = "generating"
    installing_deps = "installing_deps"
    starting_server = "starting_server"
    running = "running"
    failed = "failed"
    stopped = "stopped"


class DevServerStatus(str, Enum):
    starting = "starting"
    ready = "ready"
    failed = "failed"
    stopped = "stopped"


class FrameworkType(str, Enum):
    react_vite = "react_vite"
    nextjs = "nextjs"
    python_flask = "python_flask"
    python_fastapi = "python_fastapi"
    vanilla_js = "vanilla_js"
    unknown = "unknown"


class TaskRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=20_000)
    model: str | None = None
    auto_apply: bool = False
    autonomous: bool = False
    max_attempts: int = Field(default=3, ge=1, le=10)
    timeout_seconds: int = Field(default=300, ge=30, le=3600)
    project_id: str | None = None
    create_new_project: bool = False
    project_name: str | None = None
    framework: str | None = None


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
    attempts: int = 1
    autonomous: bool = False


class TaskEvent(BaseModel):
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    phase: TaskStatus
    message: str


class BuildTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    request: TaskRequest
    status: TaskStatus = TaskStatus.queued
    plan: ChangePlan | None = None
    execution: ExecutionReport | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    events: list[TaskEvent] = Field(default_factory=list)

    def transition(self, status: TaskStatus, message: str) -> None:
        self.status = status
        self.updated_at = datetime.now(UTC)
        self.events.append(TaskEvent(phase=status, message=message))


class DevServerInfo(BaseModel):
    port: int | None = None
    url: str | None = None
    pid: int | None = None
    status: DevServerStatus = DevServerStatus.stopped
    started_at: datetime | None = None
    framework: FrameworkType = FrameworkType.unknown
    command: str | None = None
    error: str | None = None


class Project(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    workspace_root: str
    status: ProjectStatus = ProjectStatus.creating
    framework: FrameworkType = FrameworkType.unknown
    dev_server: DevServerInfo = Field(default_factory=DevServerInfo)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    task_ids: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    def transition(self, status: ProjectStatus, message: str = "") -> None:
        self.status = status
        self.updated_at = datetime.now(UTC)


class BrowserEvidence(BaseModel):
    page_loaded: bool = False
    page_url: str | None = None
    console_errors: list[str] = Field(default_factory=list)
    network_errors: list[str] = Field(default_factory=list)
    uncaught_exceptions: list[str] = Field(default_factory=list)
    screenshot_path: str | None = None
    page_content: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ValidationResult(BaseModel):
    passed: bool
    command: str | None = None
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    browser_evidence: BrowserEvidence | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
