"""Optional coding-engine hooks for the existing TaskService pipeline.

The native TaskService remains the default.  These helpers activate only when a
request explicitly carries ``metadata.coding_engine == 'openhands'``.  OpenHands
owns proposal preparation only; LUMINA keeps approval, backup, patch apply,
build validation and rollback.
"""
from __future__ import annotations

from collections.abc import Mapping
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


def has_approved_openhands_plan(context: Any) -> bool:
    metadata = _metadata(context)
    return is_openhands_request(context) and isinstance(metadata.get("approved_preparation_plan"), Mapping)


def should_bypass_native_analysis(context: Any) -> bool:
    return is_openhands_preparation(context) or has_approved_openhands_plan(context)


def build_minimal_analysis(context: Any) -> dict[str, Any]:
    """Return the minimum analysis contract required by TaskService.

    OpenHands inspects the disposable repository itself during preparation, so
    running the native repository+LLM analysis before it is redundant.  The
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
    if isinstance(approved_plan, Mapping) and not is_openhands_preparation(context):
        return dict(approved_plan)

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
