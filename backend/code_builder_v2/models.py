from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class GenerationProgress(BaseModel):
    """Track incremental generation progress for resumability across restarts."""
    completed_files: dict[str, dict] = Field(default_factory=dict)
    failed_file: str | None = None
    total_files: int = 0
    current_file_index: int = 0
    batch_size: int = 1
    rate_limited_providers: list[str] = Field(default_factory=list)

    def is_complete(self) -> bool:
        return self.current_file_index >= self.total_files

    def get_next_batch(self, planned_changes: list) -> list:
        """Get the next batch of files to generate."""
        end_idx = min(self.current_file_index + self.batch_size, len(planned_changes))
        if self.current_file_index >= len(planned_changes):
            return []
        return planned_changes[self.current_file_index:end_idx]

    def mark_batch_completed(self, changes: list) -> None:
        for change in changes:
            self.completed_files[change.path] = change.model_dump()
        self.current_file_index += len(changes)

    def mark_failed(self, path: str) -> None:
        self.failed_file = path

    def get_completed_changes(self) -> list[dict]:
        return list(self.completed_files.values())

    def add_rate_limited_provider(self, provider: str) -> None:
        if provider not in self.rate_limited_providers:
            self.rate_limited_providers.append(provider)

    def is_provider_rate_limited(self, provider: str) -> bool:
        return provider in self.rate_limited_providers


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
    autonomous: bool = False
    max_attempts: int = Field(default=3, ge=1, le=10)
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
    attempts: int = 1
    autonomous: bool = False


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
    generation_progress: GenerationProgress | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    events: list[TaskEvent] = Field(default_factory=list)

    def transition(self, status: TaskStatus, message: str) -> None:
        self.status = status
        self.updated_at = datetime.now(timezone.utc)
        self.events.append(TaskEvent(phase=status, message=message))
