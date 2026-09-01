"""Safe end-to-end OpenHands execution inside a disposable LUMINA workspace."""
from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass
from pathlib import Path

from .openhands_adapter import OpenHandsAdapter, OpenHandsRunResult
from .openhands_workspace_service import OpenHandsWorkspaceService

MAX_REVIEW_DIFF_CHARACTERS = 500_000
MAX_CHANGED_FILES = 500


@dataclass(frozen=True, slots=True)
class OpenHandsFileChange:
    path: str
    change_type: str
    diff: str
    content: str | None = None
    expected_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class OpenHandsExecutionResult:
    run: OpenHandsRunResult
    changes: tuple[OpenHandsFileChange, ...]

    def public_summary(self) -> dict[str, object]:
        counts = {"created": 0, "modified": 0, "deleted": 0}
        for item in self.changes:
            counts[item.change_type] += 1
        return {
            "successful": self.run.successful,
            "changed_files": len(self.changes),
            "change_counts": counts,
            "changes": [
                {
                    "path": item.path,
                    "change_type": item.change_type,
                    "diff": item.diff,
                }
                for item in self.changes
            ],
        }


class OpenHandsExecutionService:
    def __init__(
        self,
        adapter: OpenHandsAdapter | None = None,
        workspace_service: OpenHandsWorkspaceService | None = None,
    ) -> None:
        self.adapter = adapter or OpenHandsAdapter()
        self.workspace_service = workspace_service or OpenHandsWorkspaceService()

    @staticmethod
    def _files(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file() and path.name != ".lumina_openhands_sandbox"
        }

    @staticmethod
    def _text_diff(path: str, before: bytes | None, after: bytes | None) -> str:
        try:
            old = (before or b"").decode("utf-8").splitlines(keepends=True)
            new = (after or b"").decode("utf-8").splitlines(keepends=True)
        except UnicodeDecodeError:
            return "[binary file changed]"
        diff = "".join(
            difflib.unified_diff(
                old,
                new,
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
        if len(diff) <= MAX_REVIEW_DIFF_CHARACTERS:
            return diff
        return diff[:MAX_REVIEW_DIFF_CHARACTERS] + "\n[diff truncated for safe review]\n"

    @staticmethod
    def _sha256(content: bytes | None) -> str | None:
        if content is None:
            return None
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def _utf8_content(content: bytes | None) -> str | None:
        if content is None:
            return None
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def execute(
        self,
        *,
        repository_root: str | Path,
        instruction: str,
    ) -> OpenHandsExecutionResult:
        normalized = instruction.strip()
        if not normalized:
            raise ValueError("OpenHands instruction must not be empty.")

        workspace = self.workspace_service.prepare(repository_root)
        try:
            before = self._files(workspace.workspace_root)
            run = self.adapter.run(
                prompt=normalized,
                workspace_root=workspace.workspace_root,
                disposable_workspace=True,
            )
            after = self._files(workspace.workspace_root)
            changed = sorted(
                path
                for path in set(before) | set(after)
                if before.get(path) != after.get(path)
            )
            if len(changed) > MAX_CHANGED_FILES:
                raise RuntimeError(
                    f"OpenHands changed too many files for safe review: {len(changed)}"
                )

            changes: list[OpenHandsFileChange] = []
            for path in changed:
                before_bytes = before.get(path)
                after_bytes = after.get(path)
                change_type = (
                    "created"
                    if path not in before
                    else "deleted"
                    if path not in after
                    else "modified"
                )
                changes.append(
                    OpenHandsFileChange(
                        path=path,
                        change_type=change_type,
                        diff=self._text_diff(path, before_bytes, after_bytes),
                        content=self._utf8_content(after_bytes) if change_type == "created" else None,
                        expected_sha256=self._sha256(before_bytes),
                    )
                )

            return OpenHandsExecutionResult(run, tuple(changes))
        finally:
            workspace.cleanup()
