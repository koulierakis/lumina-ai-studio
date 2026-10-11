"""Deterministic, provider-independent recovery policy.

All decisions here are pure functions of persisted job state and environment
configuration. No LLM provider is consulted, so recovery works even during a
complete provider outage.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from ..models import Job, JobStatus

# Phases in which a job is genuinely executing (heartbeat expected).
ACTIVE_STATUSES = {
    JobStatus.PENDING, JobStatus.UNDERSTANDING, JobStatus.INSPECTING,
    JobStatus.PLANNING, JobStatus.GENERATING, JobStatus.MEDIA,
    JobStatus.INSTALLING, JobStatus.BUILDING, JobStatus.TYPECHECKING,
    JobStatus.LINTING, JobStatus.TESTING, JobStatus.STARTING,
    JobStatus.VERIFYING, JobStatus.DIAGNOSING, JobStatus.REPAIRING,
    JobStatus.RECOVERING,
    JobStatus.SELF_REVIEWING, JobStatus.INDEPENDENT_REVIEW,
    JobStatus.REVIEW_REPAIR, JobStatus.FINAL_VERIFYING,
}

# Statuses the Guardian may automatically recover.
RECOVERABLE_STATUSES = set(ACTIVE_STATUSES)

# Planning-family phases restart from a fresh plan; everything else resumes
# execution from the persisted plan/workspace. Review phases are execution
# family: a restart resumes the review from persisted evidence rather than
# discarding it, and the single-runner ownership guarantee prevents a
# duplicate reviewer/repair run.
_PLANNING_PHASES = {
    JobStatus.PENDING, JobStatus.UNDERSTANDING, JobStatus.INSPECTING,
    JobStatus.PLANNING,
}

# Phase-aware stale thresholds (seconds). A stale install/build step is
# expected to take far longer than a stale planning step.
_DEFAULT_STALE_SECONDS = 300.0
_DEFAULT_MIN_STALE_SECONDS = 90.0
_DEFAULT_MAX_STALE_SECONDS = 3600.0
STALE_PHASE_SECONDS = {
    "pending": 120.0,
    "understanding": 180.0,
    "inspecting": 240.0,
    "planning": 240.0,
    "generating": 300.0,
    "media": 600.0,
    "installing": 900.0,
    "building": 900.0,
    "typechecking": 600.0,
    "linting": 600.0,
    "testing": 600.0,
    "starting": 300.0,
    "verifying": 600.0,
    "diagnosing": 300.0,
    "repairing": 600.0,
    "recovering": 300.0,
    "self_reviewing": 600.0,
    "independent_review": 600.0,
    "review_repair": 900.0,
    "final_verifying": 600.0,
}


def _phase_key(value) -> str:
    if isinstance(value, JobStatus):
        return value.value
    return str(value or "").lower()


def stale_threshold_seconds(phase) -> float:
    """Phase-aware stale threshold, clamped to configured bounds."""
    try:
        floor = float(os.environ.get("GB_GUARDIAN_MIN_STALE_SECONDS", _DEFAULT_MIN_STALE_SECONDS))
        ceiling = float(os.environ.get("GB_GUARDIAN_MAX_STALE_SECONDS", _DEFAULT_MAX_STALE_SECONDS))
    except (TypeError, ValueError):
        floor, ceiling = _DEFAULT_MIN_STALE_SECONDS, _DEFAULT_MAX_STALE_SECONDS
    if floor <= 0:
        floor = _DEFAULT_MIN_STALE_SECONDS
    if ceiling < floor:
        ceiling = _DEFAULT_MAX_STALE_SECONDS
    base = STALE_PHASE_SECONDS.get(_phase_key(phase), _DEFAULT_STALE_SECONDS)
    override = os.environ.get("GB_GUARDIAN_STALE_SECONDS", "").strip()
    if override:
        try:
            base = float(override)
        except ValueError:
            pass
    return max(floor, min(ceiling, base))


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def heartbeat_age_seconds(job: Job, *, now: Optional[datetime] = None) -> float:
    """Seconds since the last real execution heartbeat.

    Falls back to ``updated_at`` for jobs created before Guardian existed.
    """
    now = now or datetime.now(timezone.utc)
    reference = _parse_iso(getattr(job, "heartbeat_at", None)) or _parse_iso(job.updated_at)
    if reference is None:
        return 0.0
    return max(0.0, (now - reference).total_seconds())


def is_stale(job: Job, *, now: Optional[datetime] = None) -> bool:
    """Phase-aware stale detection for an active job."""
    if job.status not in ACTIVE_STATUSES:
        return False
    if getattr(job, "provider_paused", False):
        return False
    phase = getattr(job, "active_phase", None) or job.status.value
    return heartbeat_age_seconds(job, now=now) > stale_threshold_seconds(phase)


def recovery_action_for(job: Job) -> str:
    """Choose a deterministic recovery action.

    - ``replan``          : planning family (or a job with no plan yet)
    - ``resume_execution``: execution family, plan already persisted
    - ``restart``         : restart scan / stale recovery phase
    """
    phase = getattr(job, "active_phase", None)
    if job.status == JobStatus.RECOVERING or _phase_key(phase) == "recovering":
        return "restart"
    if job.plan is None:
        return "replan"
    if job.status in _PLANNING_PHASES:
        return "replan"
    return "resume_execution"
