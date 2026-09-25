"""Prepare disposable repository copies for autonomous Code Builder execution."""
from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_DEFAULT_IGNORES: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".lumina-runtime",
        ".pytest_cache",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        ".env",
        ".env.local",
        ".env.production",
        "venv",
        ".venv",
        "coverage",
        ".coverage",
        "logs",
        "tmp",
        "temp",
    }
)
_SECRET_PREFIXES: Final[tuple[str, ...]] = (".env.",)


class DisposableWorkspaceError(RuntimeError):
    """Raised when an isolated workspace cannot be prepared."""


@dataclass(frozen=True, slots=True)
class DisposableWorkspace:
    source_root: Path
    workspace_root: Path

    def cleanup(self) -> None:
        shutil.rmtree(self.workspace_root.parent, ignore_errors=True)


class DisposableWorkspaceService:
    """Copies a repository without secrets, build outputs, or symlinks."""

    def __init__(
        self, *, ignored_names: frozenset[str] = _DEFAULT_IGNORES
    ) -> None:
        self.ignored_names = ignored_names

    @staticmethod
    def _resolve_source(repository_root: str | os.PathLike[str]) -> Path:
        source = Path(repository_root).expanduser().resolve()
        if not source.is_dir():
            raise DisposableWorkspaceError(
                f"Repository directory does not exist: {source}"
            )
        return source

    def _ignore(self, directory: str, names: list[str]) -> set[str]:
        base = Path(directory)
        ignored = {name for name in names if name in self.ignored_names}
        ignored.update(
            name
            for name in names
            if any(name.startswith(prefix) for prefix in _SECRET_PREFIXES)
        )
        for name in names:
            try:
                if (base / name).is_symlink():
                    ignored.add(name)
            except OSError:
                ignored.add(name)
        return ignored

    def prepare(
        self, repository_root: str | os.PathLike[str]
    ) -> DisposableWorkspace:
        source = self._resolve_source(repository_root)
        temp_parent = Path(tempfile.mkdtemp(prefix="lumina-code-builder-"))
        destination = temp_parent / "workspace"
        try:
            shutil.copytree(
                source,
                destination,
                ignore=self._ignore,
                symlinks=False,
            )
        except Exception as exc:
            shutil.rmtree(temp_parent, ignore_errors=True)
            raise DisposableWorkspaceError(
                f"Could not create disposable Code Builder workspace: {exc}"
            ) from exc

        (destination / ".lumina_code_builder_sandbox").write_text(
            "Disposable LUMINA workspace. Autonomous edits are allowed here only.\n",
            encoding="utf-8",
        )
        return DisposableWorkspace(source, destination)
