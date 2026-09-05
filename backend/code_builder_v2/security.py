from __future__ import annotations

from pathlib import Path


class UnsafePathError(ValueError):
    pass


def resolve_inside(root: Path, relative_path: str) -> Path:
    root = root.resolve()
    candidate = (root / relative_path).resolve()
    if candidate == root or root not in candidate.parents:
        raise UnsafePathError(f"Path escapes repository root: {relative_path}")
    return candidate
