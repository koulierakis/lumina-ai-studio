"""Safe end-to-end OpenHands execution inside a disposable LUMINA workspace."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from .openhands_adapter import OpenHandsAdapter, OpenHandsRunResult
from .openhands_workspace_service import OpenHandsWorkspaceService


@dataclass(frozen=True, slots=True)
class OpenHandsFileChange:
    path: str
    change_type: str
    diff: str


@dataclass(frozen=True, slots=True)
class OpenHandsExecutionResult:
    run: OpenHandsRunResult
    changes: tuple[OpenHandsFileChange, ...]


class OpenHandsExecutionService:
    """Runs OpenHands on a copy and returns reviewable changes without touching source."""

    def __init__(self, adapter: OpenHandsAdapter | None = None, workspace_service: OpenHandsWorkspaceService | None = None) -> None:
        self.adapter = adapter or OpenHandsAdapter()
        self.workspace_service = workspace_service or OpenHandsWorkspaceService()

    @staticmethod
    def _files(root: Path) -> dict[str, bytes]:
        result: dict[str, bytes] = {}
        for path in root.rglob("*"):
            if path.is_file() and path.name != ".lumina_openhands_sandbox":
                result[path.relative_to(root).as_posix()] = path.read_bytes()
        return result

    @staticmethod
    def _text_diff(path: str, before: bytes | None, after: bytes | None) -> str:
        try:
            old = (before or b"").decode("utf-8").splitlines(keepends=True)
            new = (after or b"").decode("utf-8").splitlines(keepends=True)
        except UnicodeDecodeError:
            return "[binary file changed]"
        return "".join(difflib.unified_diff(old, new, fromfile=f"a/{path}", tofile=f"b/{path}"))

    def execute(self, *, repository_root: str | Path, instruction: str) -> OpenHandsExecutionResult:
        workspace = self.workspace_service.prepare(repository_root)
        try:
            before = self._files(workspace.workspace_root)
            run = self.adapter.run(
                prompt=instruction,
                workspace_root=workspace.workspace_root,
                disposable_workspace=True,
            )
            after = self._files(workspace.workspace_root)
            changes: list[OpenHandsFileChange] = []
            for path in sorted(set(before) | set(after)):
                if before.get(path) == after.get(path):
                    continue
                if path not in before:
                    kind = "created"
                elif path not in after:
                    kind = "deleted"
                else:
                    kind = "modified"
                changes.append(OpenHandsFileChange(path, kind, self._text_diff(path, before.get(path), after.get(path))))
            return OpenHandsExecutionResult(run=run, changes=tuple(changes))
        finally:
            workspace.cleanup()
