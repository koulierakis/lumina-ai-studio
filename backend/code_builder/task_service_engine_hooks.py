"""Optional coding-engine hooks for the existing TaskService pipeline.

The native TaskService remains the default. These helpers activate only when a
request explicitly carries ``metadata.coding_engine == 'openhands'``. OpenHands
owns proposal preparation only; LUMINA keeps approval, backup, patch apply,
build validation and rollback.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .openhands_preparation_service import OpenHandsPreparationService
from .patch_service import PatchRequestPayload

OPENHANDS_ENGINE = "openhands"
_PREPARATION_FLAG = "code_builder_preparation"
_PREPARED_RESULT_KEY = "_openhands_preparation_result"


def _metadata(context: Any) -> Mapping[str, Any]:
    value = getattr(getattr(context, "request", None), "metadata", None)
    return value if isinstance(value, Mapping) else {}


def is_openhands_request(context: Any) -> bool:
    return str(_metadata(context).get("coding_engine", "")).strip().lower() == OPENHANDS_ENGINE


def is_openhands_preparation(context: Any) -> bool:
    return is_openhands_request(context) and bool(_metadata(context).get(_PREPARATION_FLAG))


def require_approved_openhands_execution(context: Any) -> Mapping[str, Any]:
    """Validate that an approved OpenHands proposal belongs to this exact task.

    Approval metadata is replay-sensitive. A proposal prepared for task A must
    never be reusable as an execution payload for task B. Approved patch
    operations are therefore accepted only when the reviewed plan and the
    originating task id are present together and match the current request.
    """
    if not is_openhands_request(context):
        raise RuntimeError("OpenHands approval validation requires an OpenHands request.")

    metadata = _metadata(context)
    approved_plan = metadata.get("approved_preparation_plan")
    if not isinstance(approved_plan, Mapping):
        raise RuntimeError("OpenHands execution requires an approved preparation plan.")

    approved_task_id = str(metadata.get("approved_preparation_task_id", "")).strip()
    current_task_id = str(getattr(getattr(context, "request", None), "task_id", "")).strip()
    if not approved_task_id:
        raise RuntimeError("OpenHands approved plan is missing its originating task id.")
    if not current_task_id or approved_task_id != current_task_id:
        raise RuntimeError(
            "OpenHands approved plan belongs to a different task and cannot be replayed."
        )

    approved_operations = metadata.get("approved_patch_operations")
    if (
        not isinstance(approved_operations, Sequence)
        or isinstance(approved_operations, (str, bytes, bytearray))
        or not approved_operations
    ):
        raise RuntimeError("OpenHands approved plan has no approved patch operations.")

    return approved_plan


def has_approved_openhands_plan(context: Any) -> bool:
    if not is_openhands_request(context):
        return False
    metadata = _metadata(context)
    if not isinstance(metadata.get("approved_preparation_plan"), Mapping):
        return False
    require_approved_openhands_execution(context)
    return True


def should_bypass_native_analysis(context: Any) -> bool:
    return is_openhands_preparation(context) or has_approved_openhands_plan(context)


def build_minimal_analysis(context: Any) -> dict[str, Any]:
    """Return the minimum analysis contract required by TaskService.

    OpenHands inspects the disposable repository itself during preparation, so
    running the native repository+LLM analysis before it is redundant. The
    approved execution path also reuses the already reviewed plan/patch.
    """
    repository_root = Path(context.configuration.repository_root).resolve()
    return {
        "repository_root": str(repository_root),
        "repository_name": repository_root.name,
        "engine": OPENHANDS_ENGINE,
        "analysis_mode": "openhands_preapproved" if has_approved_openhands_plan(context) else "openhands_sandbox",
        "files": [],
        "warnings": [],
        "errors": [],
    }


def prepare_or_reuse_plan(context: Any) -> Any | None:
    """Return an OpenHands/pre-approved plan or ``None`` for native planning."""
    if not is_openhands_request(context):
        return None

    metadata = _metadata(context)
    approved_plan = metadata.get("approved_preparation_plan")
    approved_operations = metadata.get("approved_patch_operations")

    # An execution payload must never be accepted without the reviewed plan it
    # came from. This blocks direct metadata injection of patch operations.
    if (
        approved_operations is not None
        and not isinstance(approved_plan, Mapping)
        and not is_openhands_preparation(context)
    ):
        raise RuntimeError(
            "OpenHands patch operations cannot execute without an approved preparation plan."
        )

    if isinstance(approved_plan, Mapping) and not is_openhands_preparation(context):
        return dict(require_approved_openhands_execution(context))

    if not is_openhands_preparation(context):
        return None

    request = context.request
    service = OpenHandsPreparationService()
    prepared = service.prepare(
        task_id=request.task_id,
        repository_root=context.configuration.repository_root,
        instruction=request.instruction,
        target_paths=tuple(request.target_paths),
        excluded_paths=tuple(request.excluded_paths),
        allow_file_creation=bool(request.allow_file_creation),
        allow_file_deletion=bool(request.allow_file_deletion),
    )

    if not isinstance(prepared, Mapping):
        raise RuntimeError("OpenHands preparation returned an invalid result.")
    plan = prepared.get("plan")
    patch = prepared.get("patch")
    if not isinstance(plan, Mapping):
        raise RuntimeError("OpenHands preparation returned no reviewable plan.")
    if not isinstance(patch, Mapping):
        raise RuntimeError("OpenHands preparation returned no patch payload.")

    context.metadata[_PREPARED_RESULT_KEY] = dict(prepared)
    return dict(plan)


def prepared_patch_for_context(context: Any) -> PatchRequestPayload | None:
    """Return the sandbox-generated patch during the pre-approval dry run."""
    prepared = getattr(context, "metadata", {}).get(_PREPARED_RESULT_KEY)
    if not isinstance(prepared, Mapping):
        return None
    patch = prepared.get("patch")
    if not isinstance(patch, Mapping):
        raise RuntimeError("Stored OpenHands preparation has no patch payload.")

    payload = dict(patch)
    payload["dry_run"] = bool(context.request.dry_run)
    payload["rollback_on_failure"] = True
    return PatchRequestPayload.model_validate(payload)


def public_engine_metadata(context: Any) -> dict[str, Any]:
    """Expose review evidence without changing TaskExecutionResult's schema."""
    prepared = getattr(context, "metadata", {}).get(_PREPARED_RESULT_KEY)
    if not isinstance(prepared, Mapping):
        return {}
    return {
        "coding_engine": OPENHANDS_ENGINE,
        "openhands_preparation": dict(prepared),
        "source_repository_unchanged": bool(prepared.get("source_repository_unchanged", True)),
        "requires_approval": True,
    }
