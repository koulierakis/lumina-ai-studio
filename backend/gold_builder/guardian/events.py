"""Structured Guardian events.

Events are metadata-only. They never contain prompts, model output, source
code, credentials, or tokens: only identifiers, phase names, durations, and
decision outcomes. They are appended to the persisted job and mirrored to the
opt-in progress stream so operators can follow recovery without reading logs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from ..models import GuardianEvent

_MAX_JOB_EVENTS = 200


def _truncate(value: str, limit: int = 300) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _safe_data(data: Optional[dict]) -> Optional[dict[str, Any]]:
    if not data:
        return None
    out: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[str(key)] = _truncate(value) if isinstance(value, str) else value
        elif isinstance(value, (list, tuple)):
            out[str(key)] = [v for v in value if isinstance(v, (str, int, float, bool))]
        else:
            out[str(key)] = str(value)[:300]
    return out


def guardian_event(
    job,
    kind: str,
    *,
    phase: str = "",
    message: str = "",
    data: Optional[dict] = None,
    persist: bool = True,
) -> GuardianEvent:
    """Record one structured Guardian event on the job (and progress stream)."""
    event = GuardianEvent(
        ts=datetime.now(timezone.utc).isoformat(),
        kind=kind,
        phase=phase or (getattr(job, "active_phase", None) or ""),
        message=_truncate(message),
        data=_safe_data(data),
    )
    if persist:
        history = getattr(job, "guardian_events", None)
        if history is None:
            job.guardian_events = []
            history = job.guardian_events
        history.append(event)
        if len(history) > _MAX_JOB_EVENTS:
            del history[: len(history) - _MAX_JOB_EVENTS]
    try:
        from ..progress import mark
        mark(
            f"GUARDIAN {kind.upper()}",
            job_id=getattr(job, "id", ""),
            phase=event.phase,
            message=event.message,
            **(event.data or {}),
        )
    except Exception:
        pass
    return event
