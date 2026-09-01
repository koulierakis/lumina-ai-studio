"""Small drop-in helpers for wiring coding-engine selection into router.py.

The router keeps its current task store, approval, backup, apply, build and
rollback behavior.  These helpers only decide how the pre-approval proposal is
prepared and how its approved operations are attached to the existing request.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from .engine_preparation_service import CodeBuilderEnginePreparationService
from .engine_registry import NATIVE_ENGINE


def requested_engine(metadata: Mapping[str, Any] | None) -> str:
    """Read the requested coding engine from task metadata; Native is default."""
    value = (metadata or {}).get("coding_engine", NATIVE_ENGINE)
    normalized = str(value).strip().lower()
    return normalized or NATIVE_ENGINE


def prepare_for_router(
    *,
    preparation_service: CodeBuilderEnginePreparationService,
    task_id: str,
    repository_root: str | Path,
    instruction: str,
    metadata: Mapping[str, Any] | None,
    native_prepare: Callable[[], Any],
) -> Any:
    """Prepare the review proposal while preserving the existing Native path."""
    return preparation_service.prepare(
        engine=requested_engine(metadata),
        task_id=task_id,
        repository_root=repository_root,
        instruction=instruction,
        native_prepare=native_prepare,
    )


def approved_request_metadata(
    *,
    preparation_service: CodeBuilderEnginePreparationService,
    existing_metadata: Mapping[str, Any] | None,
    preparation_result: Any,
) -> dict[str, Any]:
    """Return request metadata ready for the existing approved execution path."""
    metadata = dict(existing_metadata or {})
    metadata.pop("patch_operations", None)
    metadata.pop("execution_patch_operations", None)
    metadata.update(preparation_service.approval_metadata(preparation_result))
    return metadata
