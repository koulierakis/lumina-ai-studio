"""ZIP export of generated projects + engine source.

Both exporters run an at-export secret scan (`security.scan_paths_for_secrets`)
and refuse to package files containing likely credentials. `.env` files are
always stripped from the ZIP; only `.env.example` is allowed through.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import List

from ..security import (
    SecretDetectedError,
    is_secretful_filename,
    scan_paths_for_secrets,
)


# Directory names that never make sense to package.
_SKIP_DIRS = {
    "node_modules", ".venv", "venv", "__pycache__", ".git",
    "workspaces", ".yarn", "build", "dist", ".next",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "htmlcov",
    "test_reports", ".coverage",
}

# Path components (case-sensitive) whose contents we do NOT scan for
# secret-shaped strings — they legitimately contain fake fixtures. The
# files themselves still get packaged and any real filename-blocklist
# stripping still applies.
_UNSCANNED_PATH_PARTS = {"tests", "test", "fixtures", "__fixtures__"}


def _eligible_files(root: Path, extra_skip: set[str] = frozenset()) -> List[Path]:
    files: List[Path] = []
    skip = _SKIP_DIRS | set(extra_skip)
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in skip for part in rel.parts):
            continue
        if is_secretful_filename(str(rel)):
            continue
        # Cap file size
        try:
            if p.stat().st_size > 5 * 1024 * 1024:
                continue
        except OSError:
            continue
        files.append(p)
    return files


def _files_to_scan(files: List[Path], root: Path) -> List[Path]:
    """Subset of the eligible files that should actually be scanned for
    secret-shaped content."""
    out: List[Path] = []
    for p in files:
        rel = p.relative_to(root)
        if any(part in _UNSCANNED_PATH_PARTS for part in rel.parts):
            continue
        if p.name.startswith("test_") or p.name.endswith("_test.py"):
            continue
        out.append(p)
    return out


def _write_zip(files: List[Path], root: Path, out_zip: Path) -> Path:
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, arcname=p.relative_to(root))
    return out_zip


def export_zip(project: Path, out_zip: Path,
               strict: bool = True) -> Path:
    """Package a generated project. Refuses to ship secrets when strict=True."""
    files = _eligible_files(project)
    hits = scan_paths_for_secrets(_files_to_scan(files, project))
    if hits and strict:
        raise SecretDetectedError(
            "Refusing to export: secret-like content detected in "
            f"{len(hits)} file(s):\n  - " + "\n  - ".join(hits[:5])
        )
    return _write_zip(files, project, out_zip)


def export_engine_zip(engine_root: Path, out_zip: Path,
                      strict: bool = True) -> Path:
    """Export the Gold Builder engine source itself. Same secret guarantees."""
    files = _eligible_files(engine_root, extra_skip={"workspaces"})
    hits = scan_paths_for_secrets(_files_to_scan(files, engine_root))
    if hits and strict:
        raise SecretDetectedError(
            "Refusing to export engine ZIP: secret-like content in "
            f"{len(hits)} file(s):\n  - " + "\n  - ".join(hits[:5])
        )
    return _write_zip(files, engine_root, out_zip)
