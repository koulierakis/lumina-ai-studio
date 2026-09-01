"""Capture OpenHands sandbox file changes without trusting agent output."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Mapping

MAX_TEXT_FILE_BYTES: Final[int] = 2_000_000
MAX_CHANGED_FILES: Final[int] = 200
MAX_SNAPSHOT_FILES: Final[int] = 20_000
FORBIDDEN_PARTS: Final[frozenset[str]] = frozenset({
    ".git", ".lumina-runtime", ".env", ".env.local", ".env.production",
    "node_modules", ".venv", "venv", "__pycache__",
})


class OpenHandsChangeCaptureError(RuntimeError):
    """Raised when sandbox changes cannot be represented safely."""


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    sha256: str
    size_bytes: int
    text: str | None


@dataclass(frozen=True, slots=True)
class OpenHandsFileChange:
    relative_path: str
    change_type: Literal["created", "modified", "deleted"]
    before_text: str | None
    after_text: str | None


class OpenHandsChangeCaptureService:
    """Snapshot a disposable workspace and derive a bounded text-only change set."""

    @staticmethod
    def _safe_root(workspace_root: str | os.PathLike[str]) -> Path:
        root = Path(workspace_root).expanduser().resolve()
        if not root.is_dir():
            raise OpenHandsChangeCaptureError(f"Workspace directory does not exist: {root}")
        return root

    @staticmethod
    def _relative(root: Path, path: Path) -> str:
        try:
            relative = path.relative_to(root)
        except ValueError as exc:
            raise OpenHandsChangeCaptureError(f"Path escaped workspace: {path}") from exc
        if relative.is_absolute() or ".." in relative.parts:
            raise OpenHandsChangeCaptureError(f"Unsafe workspace path: {relative}")
        return relative.as_posix()

    @staticmethod
    def _forbidden(relative: str) -> bool:
        parts = Path(relative).parts
        return any(part in FORBIDDEN_PARTS or part.startswith(".env.") for part in parts)

    @staticmethod
    def _snapshot_file(path: Path) -> FileSnapshot:
        digest = hashlib.sha256()
        size = 0
        chunks: list[bytes] = []
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(131072)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
                if size <= MAX_TEXT_FILE_BYTES:
                    chunks.append(chunk)
        text: str | None = None
        if size <= MAX_TEXT_FILE_BYTES:
            raw = b"".join(chunks)
            try:
                decoded = raw.decode("utf-8")
                if "\x00" not in decoded:
                    text = decoded
            except UnicodeDecodeError:
                text = None
        return FileSnapshot(digest.hexdigest(), size, text)

    def snapshot(self, workspace_root: str | os.PathLike[str]) -> dict[str, FileSnapshot]:
        root = self._safe_root(workspace_root)
        result: dict[str, FileSnapshot] = {}
        for path in root.rglob("*"):
            if path.is_symlink():
                raise OpenHandsChangeCaptureError(f"Symlink created inside OpenHands workspace: {path}")
            if not path.is_file():
                continue
            relative = self._relative(root, path)
            if self._forbidden(relative):
                raise OpenHandsChangeCaptureError(f"Forbidden path exists inside OpenHands workspace: {relative}")
            result[relative] = self._snapshot_file(path)
            if len(result) > MAX_SNAPSHOT_FILES:
                raise OpenHandsChangeCaptureError("OpenHands workspace contains too many files to review safely.")
        return result

    def compare(
        self,
        before: Mapping[str, FileSnapshot],
        after: Mapping[str, FileSnapshot],
    ) -> tuple[OpenHandsFileChange, ...]:
        changes: list[OpenHandsFileChange] = []
        for relative in sorted(set(before) | set(after)):
            old = before.get(relative)
            new = after.get(relative)
            if old and new and old.sha256 == new.sha256:
                continue
            if self._forbidden(relative):
                raise OpenHandsChangeCaptureError(f"OpenHands changed a forbidden path: {relative}")
            if (old and old.text is None) or (new and new.text is None):
                raise OpenHandsChangeCaptureError(
                    f"OpenHands changed a binary or oversized file that requires manual review: {relative}"
                )
            if old is None:
                changes.append(OpenHandsFileChange(relative, "created", None, new.text if new else None))
            elif new is None:
                changes.append(OpenHandsFileChange(relative, "deleted", old.text, None))
            else:
                changes.append(OpenHandsFileChange(relative, "modified", old.text, new.text))
            if len(changes) > MAX_CHANGED_FILES:
                raise OpenHandsChangeCaptureError("OpenHands changed too many files for one safe LUMINA review.")
        return tuple(changes)
