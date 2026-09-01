"""Shared preparation boundary for Native and OpenHands Code Builder engines.

This module lets the existing Code Builder task lifecycle keep ownership of
approval, backup, apply, build validation and rollback.  The selected coding
engine is responsible only for preparing a reviewable proposal.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .engine_registry import NATIVE_ENGINE, OPENHANDS_ENGINE, CodingEngineRegistry
from .openhands_preparation_service import OpenHandsPreparationService

NativePreparation = Callable[[], Any]


class EnginePreparationError(RuntimeError):
    """Raised when an engine cannot produce an approval-compatible proposal."""


class CodeBuilderEnginePreparationService:
    """Prepare changes with Native or OpenHands without bypassing LUMINA safety."""

    def __init__(
        self,
        *,
        registry: CodingEngineRegistry | None = None,
        openhands: OpenHandsPreparationService | None = None,
    ) -> None:
        self.registry = registry or CodingEngineRegistry()
        self.openhands = openhands or OpenHandsPreparationService(self.registry)

    def prepare(
        self,
        *,
        engine: str | None,
        task_id: str,
        repository_root: str | Path,
        instruction: str,
        native_prepare: NativePreparation,
        target_paths: tuple[str, ...] = (),
        excluded_paths: tuple[str, ...] = (),
        allow_file_creation: bool = True,
        allow_file_deletion: bool = False,
    ) -> Any:
        selected = self.registry.validate_selection(engine)
        if selected == NATIVE_ENGINE:
            return native_prepare()
        if selected == OPENHANDS_ENGINE:
            return self.openhands.prepare(
                task_id=task_id,
                repository_root=repository_root,
                instruction=instruction,
                target_paths=target_paths,
                excluded_paths=excluded_paths,
                allow_file_creation=allow_file_creation,
                allow_file_deletion=allow_file_deletion,
            )
        raise EnginePreparationError(f"Unsupported coding engine: {selected}")

    @staticmethod
    def approval_metadata(preparation_result: Any) -> dict[str, Any]:
        """Build the exact metadata keys the existing TaskService already accepts."""
        if hasattr(preparation_result, "model_dump"):
            preparation_result = preparation_result.model_dump(mode="python")
        if not isinstance(preparation_result, Mapping):
            raise EnginePreparationError("Preparation result is not a mapping.")

        patch = preparation_result.get("patch")
        if not isinstance(patch, Mapping):
            raise EnginePreparationError("Preparation result has no patch payload.")
        operations = patch.get("operations")
        if not isinstance(operations, Sequence) or isinstance(operations, (str, bytes, bytearray)) or not operations:
            raise EnginePreparationError("Preparation result has no patch operations.")

        return {
            "approved_patch_operations": list(operations),
            "approved_preparation_plan": preparation_result.get("plan"),
            "approved_preparation_task_id": preparation_result.get("task_id"),
            "coding_engine": preparation_result.get("engine", NATIVE_ENGINE),
        }
