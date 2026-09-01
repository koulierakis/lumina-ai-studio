"""Safe end-to-end OpenHands execution inside a disposable LUMINA workspace."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from .openhands_adapter import OpenHandsAdapter, OpenHandsRunResult
from .openhands_workspace_service import OpenHandsWorkspaceService

MAX_REVIEW_DIFF_CHARACTERS = 500_000


@dataclass(frozen=True, slots=True)
class OpenHandsFileChange:
    path: str
    change_type: str
    diff: str


@dataclass(frozen=True, slots=True)
class OpenHandsExecutionResult:
    run: OpenHandsRunResult
    changes: tuple[OpenHandsFileChange, ...]

    def public_summary(self) -> dict[str, object]:
        return {"successful": self.run.successful, "changed_files": len(self.changes), "changes": [{"path": i.path, "change_type": i.change_type, "diff": i.diff} for i in self.changes]}


class OpenHandsExecutionService:
    """Runs OpenHands on a copy and returns reviewable changes without touching source."""

    def __init__(self, adapter: OpenHandsAdapter | None = None, workspace_service: OpenHandsWorkspaceService | None = None) -> None:
        self.adapter = adapter or OpenHandsAdapter()
        self.workspace_service = workspace_service or OpenHandsWorkspaceService()

    @staticmethod
    def _files(root: Path) -> dict[str, bytes]:
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file() and p.name != ".lumina_openhands_sandbox"}

    @staticmethod
    def _text_diff(path: str, before: bytes | None, after: bytes | None) -> str:
        try:
            old = (before or b"").decode("utf-8").splitlines(keepends=True)
            new = (after or b"").decode("utf-8").splitlines(keepends=True)
        except UnicodeDecodeError:
            return "[binary file changed]"
        diff = "".join(difflib.unified_diff(old, new, fromfile=f"a/{path}", tofile=f"b/{path}"))
        if len(diff) > MAX_REVIEW_DIFF_CHARACTERS:
            return diff[:MAX_REVIEW_DIFF_CHARACTERS] + "\n[diff truncated for safe review]\n"
        return diff

    def execute(self, *, repository_root: str | Path, instruction: str) -> OpenHandsExecutionResult:
        normalized = instruction.strip()
        if not normalized:
            raise ValueError("OpenHands instruction must not be empty.")
        workspace = self.workspace_service.prepare(repository_root)
        try:
            before = self._files(workspace.workspace_root)
            run = self.adapter.run(prompt=normalized, workspace_root=workspace.workspace_root, disposable_workspace=True)
            after = self._files(workspace.workspace_root)
            changes = []
            for path in sorted(set(before) | set(after)):
                if before.get(path) == after.get(path): continue
                kind = "created" if path not in before else "deleted" if path not in after else "modified"
                changes.append(OpenHandsFileChange(path, kind, self._text_diff(path, before.get(path), after.get(path))))
            return OpenHandsExecutionResult(run=run, changes=tuple(changes))
        finally:
            workspace.cleanup()
