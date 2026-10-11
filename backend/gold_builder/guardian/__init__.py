"""Internal Guardian / Watchdog / Recovery subsystem.

The Guardian keeps autonomous jobs progressing without depending on any LLM
provider. It provides persistent execution state, real heartbeats, phase-aware
stale detection, deterministic recovery (planning/execution/restart),
duplicate-recovery prevention, bounded recovery loops, provider-outage
pause/resume, safe checkpoints, and structured secret-free events.
"""
from .engine import Guardian
from .events import guardian_event
from .policy import (
    ACTIVE_STATUSES,
    RECOVERABLE_STATUSES,
    STALE_PHASE_SECONDS,
    recovery_action_for,
    stale_threshold_seconds,
    is_stale,
)

__all__ = [
    "Guardian",
    "guardian_event",
    "ACTIVE_STATUSES",
    "RECOVERABLE_STATUSES",
    "STALE_PHASE_SECONDS",
    "recovery_action_for",
    "stale_threshold_seconds",
    "is_stale",
]
