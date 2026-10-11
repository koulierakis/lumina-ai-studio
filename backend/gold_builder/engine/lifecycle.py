"""The Gold Builder lifecycle state machine.

One canonical place that answers "is this status change legal?". Before this
module, every caller wrote ``job.status = ...`` directly, so the only rules were
conventions spread across the orchestrator, the review loop, the API and the
Guardian. Two classes of bug followed:

- a terminal job could be resurrected (a late writer overwrote ``FAILED`` or
  ``COMPLETED`` with an active phase);
- ``COMPLETED`` could be written from anywhere, so a new path could quietly
  reintroduce a false completion.

This module makes the transitions explicit and fail-closed. ``transition()``
raises :class:`LifecycleViolation` for an illegal move instead of silently
corrupting the job. ``COMPLETED`` additionally requires the completion
authority (see :func:`completion_authority`), so only the single finalizer can
declare success.

The table is intentionally generous about *forward* movement (the engine has
many legitimate orders, especially across repair/review loops) and strict about
the invariants that actually matter: no leaving a terminal state, no declaring
success without authority, and no rewinding a run to an earlier phase.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import FrozenSet, Iterator, Tuple

from ..models import Job, JobStatus

# Canonical forward order of the build lifecycle. Review phases sit at the end,
# before the terminal states. Used to detect rewinds within a single run.
LIFECYCLE_STAGES: Tuple[JobStatus, ...] = (
    JobStatus.PENDING,
    JobStatus.UNDERSTANDING,
    JobStatus.INSPECTING,
    JobStatus.PLANNING,
    JobStatus.GENERATING,
    JobStatus.MEDIA,
    JobStatus.INSTALLING,
    JobStatus.BUILDING,
    JobStatus.TYPECHECKING,
    JobStatus.LINTING,
    JobStatus.TESTING,
    JobStatus.STARTING,
    JobStatus.VERIFYING,
    JobStatus.DIAGNOSING,
    JobStatus.REPAIRING,
    JobStatus.SELF_REVIEWING,
    JobStatus.REVIEW_REPAIR,
    JobStatus.INDEPENDENT_REVIEW,
    JobStatus.FINAL_VERIFYING,
)

TERMINAL_STATUSES: FrozenSet[JobStatus] = frozenset(
    {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
)

# Phases that pause/resume and recovery may re-enter; they are not linear.
_CONTROL_STATUSES: FrozenSet[JobStatus] = frozenset(
    {JobStatus.PAUSED, JobStatus.RECOVERING}
)

PLANNING_FAMILY: FrozenSet[JobStatus] = frozenset(
    {JobStatus.PENDING, JobStatus.UNDERSTANDING, JobStatus.INSPECTING, JobStatus.PLANNING}
)

REVIEW_PHASES: FrozenSet[JobStatus] = frozenset(
    {
        JobStatus.SELF_REVIEWING,
        JobStatus.REVIEW_REPAIR,
        JobStatus.INDEPENDENT_REVIEW,
        JobStatus.FINAL_VERIFYING,
    }
)

# Everything that may be entered from a control phase (recovery/pause resume):
# any non-terminal phase. Recovery legitimately restarts planning, execution or
# review depending on where the job stalled, so it is deliberately unconstrained
# in the forward direction — its guard is the ownership claim, not the ordering.
_ENTERABLE_FROM_CONTROL: FrozenSet[JobStatus] = frozenset(
    set(LIFECYCLE_STAGES) | set(_CONTROL_STATUSES)
)

_EXECUTION_FAMILY: FrozenSet[JobStatus] = frozenset(
    {
        JobStatus.GENERATING, JobStatus.MEDIA, JobStatus.INSTALLING,
        JobStatus.BUILDING, JobStatus.TYPECHECKING, JobStatus.LINTING,
        JobStatus.TESTING, JobStatus.STARTING, JobStatus.VERIFYING,
        JobStatus.DIAGNOSING, JobStatus.REPAIRING,
    }
)

_TERMINAL_OR_CANCEL: FrozenSet[JobStatus] = frozenset(
    {JobStatus.FAILED, JobStatus.CANCELLED}
)


def _edges(*targets: JobStatus) -> FrozenSet[JobStatus]:
    return frozenset(targets)


def _build_transitions() -> dict:
    forward = {
        JobStatus.PENDING: _edges(
            JobStatus.UNDERSTANDING, JobStatus.INSPECTING, JobStatus.PLANNING,
            JobStatus.GENERATING, JobStatus.MEDIA,
        ),
        JobStatus.UNDERSTANDING: _edges(
            JobStatus.INSPECTING, JobStatus.PLANNING, JobStatus.GENERATING,
        ),
        JobStatus.INSPECTING: _edges(JobStatus.PLANNING),
        JobStatus.PLANNING: _edges(
            JobStatus.INSPECTING, JobStatus.PLANNING, JobStatus.GENERATING,
            JobStatus.MEDIA,
        ),
        JobStatus.GENERATING: _edges(
            JobStatus.MEDIA, *_EXECUTION_FAMILY, JobStatus.PLANNING,
        ),
        JobStatus.MEDIA: _edges(
            *_EXECUTION_FAMILY, JobStatus.GENERATING,
        ),
        JobStatus.INSTALLING: _edges(
            JobStatus.BUILDING, JobStatus.TYPECHECKING, JobStatus.LINTING,
            JobStatus.TESTING, JobStatus.STARTING, JobStatus.VERIFYING,
            JobStatus.DIAGNOSING, JobStatus.REPAIRING, JobStatus.MEDIA,
        ),
        JobStatus.BUILDING: _edges(
            JobStatus.TYPECHECKING, JobStatus.LINTING, JobStatus.TESTING,
            JobStatus.STARTING, JobStatus.VERIFYING, JobStatus.DIAGNOSING,
            JobStatus.REPAIRING, JobStatus.MEDIA,
        ),
        JobStatus.TYPECHECKING: _edges(
            JobStatus.BUILDING, JobStatus.LINTING, JobStatus.TESTING,
            JobStatus.STARTING, JobStatus.VERIFYING, JobStatus.DIAGNOSING,
            JobStatus.REPAIRING, JobStatus.MEDIA,
        ),
        JobStatus.LINTING: _edges(
            JobStatus.BUILDING, JobStatus.TYPECHECKING, JobStatus.TESTING,
            JobStatus.STARTING, JobStatus.VERIFYING, JobStatus.DIAGNOSING,
            JobStatus.REPAIRING, JobStatus.MEDIA,
        ),
        JobStatus.TESTING: _edges(
            JobStatus.BUILDING, JobStatus.TYPECHECKING, JobStatus.LINTING,
            JobStatus.STARTING, JobStatus.VERIFYING, JobStatus.DIAGNOSING,
            JobStatus.REPAIRING, JobStatus.MEDIA,
        ),
        JobStatus.STARTING: _edges(
            JobStatus.VERIFYING, JobStatus.DIAGNOSING, JobStatus.REPAIRING,
            JobStatus.MEDIA,
        ),
        JobStatus.VERIFYING: _edges(
            JobStatus.DIAGNOSING, JobStatus.REPAIRING, JobStatus.GENERATING,
            JobStatus.SELF_REVIEWING, JobStatus.FINAL_VERIFYING, JobStatus.MEDIA,
        ),
        JobStatus.DIAGNOSING: _edges(
            JobStatus.REPAIRING, JobStatus.VERIFYING, JobStatus.GENERATING,
        ),
        JobStatus.REPAIRING: _edges(
            *_EXECUTION_FAMILY, JobStatus.SELF_REVIEWING,
            JobStatus.FINAL_VERIFYING, JobStatus.MEDIA,
        ),
        # Review loop: self -> (repair -> re-verify)* -> independent -> final.
        JobStatus.SELF_REVIEWING: _edges(
            JobStatus.REVIEW_REPAIR, JobStatus.INDEPENDENT_REVIEW,
            JobStatus.FINAL_VERIFYING,
        ),
        JobStatus.REVIEW_REPAIR: _edges(
            JobStatus.FINAL_VERIFYING, JobStatus.SELF_REVIEWING,
        ),
        JobStatus.INDEPENDENT_REVIEW: _edges(
            JobStatus.REVIEW_REPAIR, JobStatus.FINAL_VERIFYING,
        ),
        JobStatus.FINAL_VERIFYING: _edges(
            JobStatus.SELF_REVIEWING, JobStatus.INDEPENDENT_REVIEW,
            JobStatus.REVIEW_REPAIR,
            # Final verification re-runs the deterministic pipeline (install ->
            # verify); generation/planning remain unreachable from here.
            JobStatus.INSTALLING, JobStatus.BUILDING, JobStatus.TYPECHECKING,
            JobStatus.LINTING, JobStatus.TESTING, JobStatus.STARTING, JobStatus.VERIFYING,
        ),
    }

    # Every non-terminal phase may fail, be cancelled, pause, or be claimed by
    # recovery. These are the only universally legal moves.
    universal = _edges(
        JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.PAUSED, JobStatus.RECOVERING,
    )
    transitions: dict = {}
    for stage in LIFECYCLE_STAGES:
        transitions[stage] = frozenset(forward.get(stage, frozenset()) | universal)

    # The review layer is a reusable, late-stage gate: it may be entered from any
    # non-terminal phase (the orchestrator normally enters it right after
    # verification, but it is also invoked standalone). Entering review can only
    # lead to repair, failure, or a completion that still requires the single
    # finalizer, so it never weakens the safety invariants.
    for stage in LIFECYCLE_STAGES:
        transitions[stage] = frozenset(transitions[stage] | REVIEW_PHASES)

    # The finalizer is the only legal producer of COMPLETED; it is a target from
    # the phases that can decide a run is done.
    for stage in (
        JobStatus.VERIFYING, JobStatus.SELF_REVIEWING,
        JobStatus.INDEPENDENT_REVIEW, JobStatus.FINAL_VERIFYING,
    ):
        transitions[stage] = frozenset(transitions[stage] | {JobStatus.COMPLETED})

    transitions[JobStatus.PAUSED] = _ENTERABLE_FROM_CONTROL | _TERMINAL_OR_CANCEL
    transitions[JobStatus.RECOVERING] = _ENTERABLE_FROM_CONTROL | _TERMINAL_OR_CANCEL

    for terminal in TERMINAL_STATUSES:
        transitions[terminal] = frozenset()
    return transitions


TRANSITIONS: dict = _build_transitions()


class LifecycleViolation(ValueError):
    """Raised when a status change would break a lifecycle invariant."""


# The completion authority: only the single finalizer may enter this context, so
# no other code path can declare a terminal status even if it calls transition().
_COMPLETION_AUTHORITY: ContextVar[bool] = ContextVar(
    "gold_builder_completion_authority", default=False
)


@contextmanager
def completion_authority() -> Iterator[None]:
    """Mark the dynamic extent in which the finalizer may decide a terminal state.

    Inside this context the single finalizer may set COMPLETED (or re-decide a
    previously terminal job during manual re-verification). Outside it, entering
    a terminal state must follow the lifecycle table, so a late writer cannot
    overwrite FAILED/COMPLETED with an active phase and nothing but the
    finalizer can declare success.
    """
    token = _COMPLETION_AUTHORITY.set(True)
    try:
        yield
    finally:
        _COMPLETION_AUTHORITY.reset(token)


def _as_status(value) -> JobStatus:
    return value if isinstance(value, JobStatus) else JobStatus(str(value))


def can_transition(current, target) -> bool:
    """True when ``current -> target`` is a legal lifecycle move.

    Re-entering the same status is always allowed (idempotent re-assertion).
    """
    src = _as_status(current)
    dst = _as_status(target)
    if src == dst:
        return True
    return dst in TRANSITIONS.get(src, frozenset())


def transition(job: Job, target, *, context: str = "") -> Job:
    """Move ``job`` to ``target``, enforcing the lifecycle table.

    Raises :class:`LifecycleViolation` on an illegal move so a bug surfaces at
    the call site instead of producing a silently corrupt status.

    Two invariants are enforced:

    - ``COMPLETED`` may only be written inside :func:`completion_authority`, so
      the single finalizer is the sole producer of success.
    - a terminal state is never exited, so a late writer cannot resurrect a
      finished job. ``FAILED`` and ``CANCELLED`` are fail-safe and may be set
      from any non-terminal phase.
    """
    dst = _as_status(target)
    src = job.status
    if dst == JobStatus.COMPLETED and not _COMPLETION_AUTHORITY.get():
        raise LifecycleViolation(
            "COMPLETED may only be set inside completion_authority()"
            f"{f' ({context})' if context else ''}"
        )
    if dst in TERMINAL_STATUSES and _COMPLETION_AUTHORITY.get():
        # The finalizer is the authority: it may re-decide a previously terminal
        # job (e.g. manual re-verification), which the ordering table forbids.
        job.status = dst
        return job
    if not can_transition(src, dst):
        raise LifecycleViolation(
            f"illegal lifecycle transition {_as_status(src).value} -> {dst.value}"
            f"{f' ({context})' if context else ''}"
        )
    job.status = dst
    return job


def begin_new_run(job: Job, target, *, context: str = "") -> Job:
    """Deliberately start a fresh run, clearing a terminal state.

    Two product operations continue a *finished* job with new work: ``iterate``
    (a new continuation request on a completed/failed job) and manual resume.
    They are the only sanctioned way to leave a terminal state; ordinary code
    must use :func:`transition`, which forbids it. Keeping this explicit means a
    late writer cannot resurrect a finished job by accident, only on purpose.
    """
    dst = _as_status(target)
    if dst in TERMINAL_STATUSES:
        raise LifecycleViolation(
            f"begin_new_run cannot target terminal status {dst.value}"
            f"{f' ({context})' if context else ''}"
        )
    job.status = dst
    return job
