"""Local disk storage for private media assets."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Tuple
import uuid

ROOT_DIR = Path(__file__).resolve().parent


def _root() -> Path:
    configured = os.environ.get("STORAGE_DIR", "").strip()
    root = Path(configured).expanduser() if configured else ROOT_DIR / "storage"
    root.mkdir(parents=True, exist_ok=True)
    (root / "references").mkdir(exist_ok=True)
    (root / "generated").mkdir(exist_ok=True)
    return root


def _ext_from_mime(mime: str) -> str:
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
        "audio/flac": ".flac", "audio/ogg": ".ogg", "audio/aac": ".aac",
    }.get(mime.lower(), ".png")


def _safe_filename(filename: str) -> str:
    candidate = os.path.basename(filename)
    if not candidate or candidate != filename or ".." in candidate:
        raise ValueError("Invalid filename")
    return candidate


def _kind_dir(root: Path, kind: str) -> Path:
    return root / ("references" if kind == "reference" else "generated")


def save_bytes(data: bytes, mime: str, kind: str = "reference") -> Tuple[str, str, int]:
    """Save bytes to disk. Returns (filename, absolute_path, size_bytes)."""
    if kind not in {"reference", "generated"}:
        raise ValueError("Invalid storage kind")
    ext = _ext_from_mime(mime)
    filename = f"{uuid.uuid4().hex}{ext}"
    abs_path = _kind_dir(_root(), kind) / filename
    abs_path.write_bytes(data)
    return filename, str(abs_path), len(data)


def read_bytes(filename: str, kind: str = "reference") -> bytes:
    if kind not in {"reference", "generated"}:
        raise ValueError("Invalid storage kind")
    safe_name = _safe_filename(filename)
    abs_path = _kind_dir(_root(), kind) / safe_name
    return abs_path.read_bytes()


def delete_file(filename: str, kind: str = "reference") -> None:
    if kind not in {"reference", "generated"}:
        return
    safe_name = _safe_filename(filename)
    p = _kind_dir(_root(), kind) / safe_name
    if p.exists():
        p.unlink()
