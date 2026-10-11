"""Workspace management. Each job gets an isolated dir under WORKSPACE_ROOT.

All path resolution goes through `gold_builder.security.safe_resolve` so
callers cannot escape the workspace via `..`, absolute paths, URL
encoding, or symlinks.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Union

from .security import UnsafePathError, safe_resolve


def workspace_root() -> Path:
    root = Path(os.environ.get("WORKSPACE_ROOT", "/app/workspaces"))
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def job_dir(job_id: str) -> Path:
    # job_id must not contain traversal
    safe_id = safe_resolve(workspace_root(), job_id).name
    d = workspace_root() / safe_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def project_dir(job_id: str) -> Path:
    d = job_dir(job_id) / "project"
    d.mkdir(parents=True, exist_ok=True)
    return d


def artifacts_dir(job_id: str) -> Path:
    d = job_dir(job_id) / "artifacts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cleanup(job_id: str) -> None:
    try:
        target = safe_resolve(workspace_root(), job_id)
    except UnsafePathError:
        return
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)


def resolve_within(root: Path, rel_path: str) -> Path:
    """Public entrypoint for callers that need a validated path inside root."""
    return safe_resolve(root, rel_path)


def safe_write(project: Path, rel_path: str, content: Union[str, bytes],
               binary: bool = False) -> Path:
    """Write file safely inside project dir. Blocks all traversal patterns."""
    target = safe_resolve(project, rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if binary or isinstance(content, (bytes, bytearray)):
        data = content if isinstance(content, (bytes, bytearray)) else content.encode("latin-1")
        target.write_bytes(bytes(data))
    else:
        target.write_text(content, encoding="utf-8")
    return target


def safe_read_text(project: Path, rel_path: str) -> str:
    target = safe_resolve(project, rel_path)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"not found: {rel_path}")
    return target.read_text(encoding="utf-8")


def validate_within_workspace(target_path: Union[str, Path]) -> Path:
    """Ensure a given directory/file is strictly within the WORKSPACE_ROOT."""
    p = Path(target_path).resolve()
    root = workspace_root().resolve()
    try:
        p.relative_to(root)
    except ValueError:
        raise UnsafePathError(f"Path escapes workspace: {target_path}")
    return p
