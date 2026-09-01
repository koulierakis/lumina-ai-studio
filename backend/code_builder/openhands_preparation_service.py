"""Prepare OpenHands proposals in the same shape the existing Code Builder approval flow expects."""
from __future__ import annotations

from pathlib import Path, PurePosixPath

from .engine_registry import CodingEngineRegistry, OPENHANDS_ENGINE
from .openhands_patch_bridge import build_patch_request_from_openhands


class OpenHandsScopeError(RuntimeError):
    """Raised when an OpenHands proposal leaves the user-approved task scope."""


def _normalize_relative(path: str) -> str:
    value = str(path).replace("\\", "/").strip().lstrip("./")
    candidate = PurePosixPath(value)
    if not value or candidate.is_absolute() or ".." in candidate.parts:
        raise OpenHandsScopeError(f"Unsafe repository path returned by OpenHands: {path!r}")
    return candidate.as_posix()


def _is_within(path: str, scope: str) -> bool:
    path_parts = PurePosixPath(_normalize_relative(path)).parts
    scope_parts = PurePosixPath(_normalize_relative(scope)).parts
    return len(path_parts) >= len(scope_parts) and path_parts[: len(scope_parts)] == scope_parts


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
        target_paths: tuple[str, ...] = (),
        excluded_paths: tuple[str, ...] = (),
        allow_file_creation: bool = True,
        allow_file_deletion: bool = False,
    ) -> dict[str, object]:
        normalized_targets = tuple(_normalize_relative(path) for path in target_paths)
        normalized_excluded = tuple(_normalize_relative(path) for path in excluded_paths)

        scope_lines = [
            "LUMINA SAFETY SCOPE:",
            "- Work only inside the disposable repository copy.",
            f"- Allowed target paths: {', '.join(normalized_targets) if normalized_targets else 'repository-wide within the user instruction'}.",
            f"- Excluded paths: {', '.join(normalized_excluded) if normalized_excluded else 'none'}.",
            f"- File creation allowed: {allow_file_creation}.",
            f"- File deletion allowed: {allow_file_deletion}.",
            "- Do not make unrelated changes.",
            "USER INSTRUCTION:",
            instruction,
        ]
        constrained_instruction = "\n".join(scope_lines)

        result = self.registry.execute(
            engine=OPENHANDS_ENGINE,
            repository_root=repository_root,
            instruction=constrained_instruction,
        )

        normalized_changed_paths: list[str] = []
        for change in result.changes:
            path = _normalize_relative(change.path)
            if normalized_targets and not any(_is_within(path, target) for target in normalized_targets):
                raise OpenHandsScopeError(
                    f"OpenHands proposed an out-of-scope change: {path}. Allowed targets: {normalized_targets}"
                )
            if any(_is_within(path, excluded) for excluded in normalized_excluded):
                raise OpenHandsScopeError(f"OpenHands proposed a change in an excluded path: {path}")
            if change.change_type == "created" and not allow_file_creation:
                raise OpenHandsScopeError(f"OpenHands proposed file creation but creation is disabled: {path}")
            if change.change_type == "deleted" and not allow_file_deletion:
                raise OpenHandsScopeError(f"OpenHands proposed file deletion but deletion is disabled: {path}")
            normalized_changed_paths.append(path)

        patch_request = build_patch_request_from_openhands(result, dry_run=True)
        review = result.public_summary()

        return {
            "task_id": task_id,
            "status": "dry_run",
            "success": True,
            "engine": OPENHANDS_ENGINE,
            # This proves only that this individual sandbox preparation completed.
            # It does not declare the global OpenHands integration production-ready.
            "preparation_execution_completed": True,
            "runtime_validated": False,
            "ready": False,
            "source_repository_unchanged": True,
            "requires_approval": True,
            "changed_paths": normalized_changed_paths,
            "plan": {
                "files": normalized_changed_paths,
                "engine": OPENHANDS_ENGINE,
                "review_only": True,
                "target_paths": list(normalized_targets),
                "excluded_paths": list(normalized_excluded),
            },
            "patch": patch_request.model_dump(mode="json"),
            "openhands_review": review,
        }
