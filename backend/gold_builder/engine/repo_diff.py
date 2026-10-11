"""File-level change tracking for existing-repo edits.

`FileHash` captures the SHA-256 of each file at a point in time.
`diff(before, after)` returns lists of CREATED / MODIFIED / DELETED /
UNCHANGED paths.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from ..models import RepoChangeSet


SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__",
             "dist", "build", ".next", ".yarn", ".pytest_cache"}


def hash_tree(root: Path) -> Dict[str, str]:
    """Walk root and return {relative_path: sha256_hex}."""
    out: Dict[str, str] = {}
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        try:
            h = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            continue
        out[str(rel).replace("\\", "/")] = h
    return out


def diff(before: Dict[str, str], after: Dict[str, str]) -> RepoChangeSet:
    before_keys = set(before)
    after_keys = set(after)
    created = sorted(after_keys - before_keys)
    deleted = sorted(before_keys - after_keys)
    common = before_keys & after_keys
    modified = sorted(k for k in common if before[k] != after[k])
    unchanged = sorted(k for k in common if before[k] == after[k])
    return RepoChangeSet(
        created=created,
        modified=modified,
        deleted=deleted,
        unchanged=unchanged,
    )
