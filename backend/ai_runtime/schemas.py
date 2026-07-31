from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any, *, _seen: set[int] | None = None) -> Any:
    """Return a plain JSON-safe copy without circular references."""
    if _seen is None:
        _seen = set()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    value_id = id(value)
    if value_id in _seen:
        return "[Circular]"
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        branch_seen = set(_seen)
        branch_seen.add(value_id)
        return {str(k): _json_safe(v, _seen=branch_seen) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        branch_seen = set(_seen)
        branch_seen.add(value_id)
        return [_json_safe(item, _seen=branch_seen) for item in value]
    try:
        return copy.deepcopy(value)
    except Exception:
        return str(value)


class RuntimeJobStatus(str, Enum):
    QUEUED = "queued"
    PREPARING = "preparing"
    LOADING_MODEL = "loading_model"
    RUNNING = "running"
    WAITING = "waiting"
    RETRYING = "retrying"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


MODEL_TYPES = (
    "llm", "image_generation", "image_editing", "video", "speech", "voice_cloning",
    "music", "embedding", "ocr", "vision", "code", "translation",
)


@dataclass
class RuntimeLog:
    level: str
    message: str
    timestamp: str = field(default_factory=utc_now)
    source: str = "runtime"

    def as_dict(self) -> dict[str, Any]:
        return {"level": self.level, "message": self.message, "timestamp": self.timestamp, "source": self.source}


@dataclass
class RuntimeJob:
    studio: str
    task_type: str
    payload: dict[str, Any]
    owner_email: str = "system"
    provider: Optional[str] = None
    model: Optional[str] = None
    id: str = field(default_factory=lambda: uuid4().hex)
    status: RuntimeJobStatus = RuntimeJobStatus.QUEUED
    progress: int = 0
    result: Any = None
    error: Optional[str] = None
    logs: list[RuntimeLog] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 1
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    estimated_seconds_remaining: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def log(self, level: str, message: str, source: str = "runtime") -> None:
        self.logs.append(RuntimeLog(level=level, message=message, source=source))
        self.logs = self.logs[-200:]
        self.updated_at = utc_now()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "owner_email": self.owner_email, "studio": self.studio, "task_type": self.task_type,
            "provider": self.provider, "model": self.model, "status": self.status.value, "progress": self.progress,
            "result": _json_safe(self.result), "error": self.error, "logs": [log.as_dict() for log in self.logs],
            "retry_count": self.retry_count, "max_retries": self.max_retries, "created_at": self.created_at,
            "updated_at": self.updated_at, "started_at": self.started_at, "finished_at": self.finished_at,
            "estimated_seconds_remaining": self.estimated_seconds_remaining, "metadata": _json_safe(self.metadata),
        }


RuntimeExecutor = Callable[[RuntimeJob, Callable[[RuntimeJobStatus, int, str], Awaitable[None]]], Awaitable[Any]]
