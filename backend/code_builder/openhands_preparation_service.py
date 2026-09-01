"""Prepare OpenHands proposals in the same shape the existing Code Builder approval flow expects."""
from __future__ import annotations

from pathlib import Path

from .engine_registry import CodingEngineRegistry, OPENHANDS_ENGINE
from .openhands_patch_bridge import build_patch_request_from_openhands


class OpenHandsPreparationService:
    """Runs OpenHands safely and returns an approval-compatible dry-run payload."""

    def __init__(self, registry: CodingEngineRegistry | None = None) -> None:
        self.registry = registry or CodingEngineRegistry()

    def prepare(
        self,
        *,
        task_id: str,
        repository_root: str | Path,
        instruction: str,
    ) -> dict[str, object]:
        result = self.registry.execute(
            engine=OPENHANDS_ENGINE,
            repository_root=repository_root,
            instruction=instruction,
        )
        patch_request = build_patch_request_from_openhands(result, dry_run=True)
        review = result.public_summary()
        changed_paths = [change.path for change in result.changes]

        return {
            "task_id": task_id,
            "status": "dry_run",
            "success": True,
            "engine": OPENHANDS_ENGINE,
            "runtime_validated": True,
            "source_repository_unchanged": True,
            "requires_approval": True,
            "changed_paths": changed_paths,
            "plan": {
                "files": changed_paths,
                "engine": OPENHANDS_ENGINE,
                "review_only": True,
            },
            "patch": patch_request.model_dump(mode="json"),
            "openhands_review": review,
        }
