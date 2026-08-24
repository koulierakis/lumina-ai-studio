"""Bounded automatic repair loop for LUMINA Code Builder.

This module installs a narrow wrapper around TaskService's build-validation
stage.  It does not replace the orchestrator.  When mandatory validation
fails after a patch was applied, the wrapper feeds the real failure back into
the existing analysis/planning/patch pipeline, applies a targeted corrective
patch, and re-runs validation.  Repair is bounded, cancellation-aware, and
restricted to the paths in the already-approved implementation plan.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from .task_service import (
    TaskBuildError,
    TaskEventLevel,
    TaskExecutionContext,
    TaskService,
    TaskServiceError,
    TaskStage,
    TaskStatus,
    _EventRecorder,
    _extract_paths,
)

DEFAULT_MAX_AUTOMATIC_REPAIR_ATTEMPTS: Final[int] = 2
MAX_AUTOMATIC_REPAIR_ATTEMPTS: Final[int] = 5

_ORIGINAL_BUILD_STAGE = TaskService._execute_build_stage
_INSTALLED = False


def _bounded_repair_attempts(context: TaskExecutionContext) -> int:
    raw_value = context.request.metadata.get(
        "max_automatic_repair_attempts",
        DEFAULT_MAX_AUTOMATIC_REPAIR_ATTEMPTS,
    )
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = DEFAULT_MAX_AUTOMATIC_REPAIR_ATTEMPTS
    return max(0, min(value, MAX_AUTOMATIC_REPAIR_ATTEMPTS))


def _repair_context_text(
    existing: str | None,
    *,
    failure: BaseException,
    attempt: int,
) -> str:
    prefix = (existing or "").rstrip()
    diagnostic = str(failure).strip() or failure.__class__.__name__
    repair_block = (
        "AUTOMATIC REPAIR CONTEXT\n"
        "========================\n"
        f"Repair attempt: {attempt}\n"
        "The previous implementation was applied but mandatory validation "
        "failed. Diagnose the failure and produce the smallest corrective "
        "change that fixes the real error without expanding scope.\n"
        f"Validation failure:\n{diagnostic}"
    )
    return f"{prefix}\n\n{repair_block}" if prefix else repair_block


def _repair_request(context: TaskExecutionContext, failure: BaseException, attempt: int):
    metadata = dict(context.request.metadata)
    # A repair must be freshly generated from the failure, not replay the
    # prepared patch that already failed validation.
    metadata.pop("patch_operations", None)
    metadata.pop("execution_patch_operations", None)
    metadata.pop("approved_patch_operations", None)
    metadata.pop("approved_preparation_plan", None)
    metadata.update(
        {
            "automatic_repair": True,
            "automatic_repair_attempt": attempt,
            "automatic_repair_failure": str(failure),
        }
    )
    return context.request.model_copy(
        update={
            "context": _repair_context_text(
                context.request.context,
                failure=failure,
                attempt=attempt,
            ),
            "metadata": metadata,
        }
    )


def _approved_paths(context: TaskExecutionContext) -> frozenset[str]:
    raw = context.metadata.get("automatic_repair_approved_paths")
    if raw is None:
        raw = _extract_paths(context.plan)
        context.metadata["automatic_repair_approved_paths"] = tuple(raw)
    return frozenset(str(path) for path in raw or ())


def _assert_repair_scope(
    context: TaskExecutionContext,
    approved_paths: frozenset[str],
) -> None:
    if not approved_paths:
        return
    repair_paths = frozenset(str(path) for path in _extract_paths(context.plan))
    unexpected = sorted(repair_paths - approved_paths)
    if unexpected:
        raise TaskBuildError(
            "Automatic repair attempted to expand the approved file scope: "
            + ", ".join(unexpected)
        )


def _record(
    service: TaskService,
    context: TaskExecutionContext,
    recorder: _EventRecorder,
    *,
    level: TaskEventLevel,
    message: str,
    details: Mapping[str, Any] | None = None,
) -> None:
    service._record_event(
        context,
        recorder,
        stage=TaskStage.BUILD,
        status=TaskStatus.BUILDING,
        level=level,
        message=message,
        details=details,
    )


def _execute_build_stage_with_repair(
    self: TaskService,
    context: TaskExecutionContext,
    recorder: _EventRecorder,
) -> None:
    try:
        _ORIGINAL_BUILD_STAGE(self, context, recorder)
        return
    except TaskBuildError as initial_failure:
        failure: BaseException = initial_failure

    maximum_attempts = _bounded_repair_attempts(context)
    if maximum_attempts <= 0 or context.request.dry_run:
        raise failure

    approved_paths = _approved_paths(context)
    original_request = context.request
    context.metadata["automatic_repair_attempts"] = 0

    for attempt in range(1, maximum_attempts + 1):
        context.raise_if_interrupted()
        context.metadata["automatic_repair_attempts"] = attempt

        _record(
            self,
            context,
            recorder,
            level=TaskEventLevel.WARNING,
            message="Automatic repair attempt started after validation failure.",
            details={
                "repair_attempt": attempt,
                "maximum_repair_attempts": maximum_attempts,
                "failure_type": failure.__class__.__name__,
                "failure_message": str(failure),
            },
        )

        try:
            context.request = _repair_request(
                context,
                failure,
                attempt,
            )
            # Re-analyse the repository in its current post-failure state, then
            # generate a corrective plan and patch through the existing safe
            # services.  Backup is intentionally not repeated: the original
            # task backup remains the single rollback point.
            self._execute_analysis_stage(context, recorder)
            self._execute_planning_stage(context, recorder)
            _assert_repair_scope(context, approved_paths)
            self._execute_patch_generation_stage(context, recorder)
            self._execute_patch_validation_stage(context, recorder)
            self._execute_patch_application_stage(context, recorder)
            _ORIGINAL_BUILD_STAGE(self, context, recorder)
        except (TaskBuildError, TaskServiceError) as repair_failure:
            failure = repair_failure
            _record(
                self,
                context,
                recorder,
                level=TaskEventLevel.WARNING,
                message="Automatic repair attempt did not pass validation.",
                details={
                    "repair_attempt": attempt,
                    "failure_type": repair_failure.__class__.__name__,
                    "failure_message": str(repair_failure),
                },
            )
            if attempt >= maximum_attempts:
                context.request = original_request
                raise TaskBuildError(
                    "Automatic repair exhausted after "
                    f"{maximum_attempts} attempt(s). Last failure: {repair_failure}"
                ) from repair_failure
            continue
        except BaseException:
            context.request = original_request
            raise
        else:
            context.request = original_request
            context.metadata["automatic_repair_succeeded"] = True
            _record(
                self,
                context,
                recorder,
                level=TaskEventLevel.INFO,
                message="Automatic repair completed and validation passed.",
                details={
                    "repair_attempt": attempt,
                    "maximum_repair_attempts": maximum_attempts,
                    "changed_paths": list(context.changed_paths),
                },
            )
            return

    context.request = original_request
    raise TaskBuildError(str(failure))


def install_automatic_repair() -> None:
    """Install the repair wrapper exactly once for this Python process."""
    global _INSTALLED
    if _INSTALLED:
        return
    TaskService._execute_build_stage = _execute_build_stage_with_repair
    _INSTALLED = True


def automatic_repair_installed() -> bool:
    return bool(_INSTALLED and TaskService._execute_build_stage is _execute_build_stage_with_repair)
