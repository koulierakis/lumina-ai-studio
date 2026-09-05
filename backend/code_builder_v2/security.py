from __future__ import annotations

from pathlib import Path, PurePosixPath


class UnsafePathError(ValueError):
    pass


def normalize_relative_path(relative_path: str) -> str:
    """Return a canonical repository-relative POSIX path or reject it.

    Backslashes are treated as separators so Windows-style paths cannot bypass
    traversal checks. Empty paths, absolute paths, drive-qualified paths, dot
    segments, and parent traversal are rejected.
    """
    raw = relative_path.strip().replace("\\", "/")
    if not raw:
        raise UnsafePathError("Path must not be empty")

    if raw.startswith("/"):
        raise UnsafePathError(f"Absolute path is not allowed: {relative_path}")

    if len(raw) >= 2 and raw[1] == ":":
        raise UnsafePathError(f"Drive-qualified path is not allowed: {relative_path}")

    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise UnsafePathError(f"Unsafe repository-relative path: {relative_path}")

    return path.as_posix()


def resolve_inside(root: Path, relative_path: str) -> Path:
    root = root.resolve()
    normalized = normalize_relative_path(relative_path)
    candidate = (root / normalized).resolve()
    if candidate == root or root not in candidate.parents:
        raise UnsafePathError(f"Path escapes repository root: {relative_path}")
    return candidate
