"""Compatibility storage facade backed by the canonical storage backend.

Legacy Image Studio, Identity Packs, Voice Studio and Document Studio call this
module. The implementation delegates every user-file operation to
``storage_backends.py`` so production S3 persistence does not depend on Render's
ephemeral filesystem.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple
import uuid

from storage_backends import LocalStorageBackend, create_storage_backend

ROOT_DIR = Path(__file__).resolve().parent
_BACKEND = None
_BACKEND_SIGNATURE = None


def _root() -> Path:
    configured = os.environ.get("STORAGE_DIR", "").strip()
    return Path(configured).expanduser() if configured else ROOT_DIR / "storage"


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
        "audio/mp4": ".m4a", "audio/x-m4a": ".m4a",
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/zip": ".zip",
        "text/plain": ".txt", "text/html": ".html", "text/markdown": ".md",
    }.get((mime or "").lower(), ".bin")


def _safe_filename(filename: str) -> str:
    candidate = os.path.basename(filename)
    if not candidate or candidate != filename or ".." in candidate:
        raise ValueError("Invalid filename")
    return candidate


def _production_requires_cloud() -> bool:
    environment = os.environ.get("LUMINA_ENV", "development").strip().lower()
    return environment in {"production", "prod"} or bool(
        os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_ID")
    )


def _backend_signature() -> tuple[str, ...]:
    return (
        os.environ.get("STORAGE_BACKEND", "local").strip().lower(),
        str(_root()),
        os.environ.get("S3_BUCKET", "").strip(),
        os.environ.get("S3_ENDPOINT_URL", "").strip(),
        os.environ.get("S3_REGION", "auto").strip(),
        os.environ.get("S3_ACCESS_KEY_ID", "").strip(),
    )


def _backend():
    global _BACKEND, _BACKEND_SIGNATURE
    signature = _backend_signature()
    mode = signature[0]
    if _production_requires_cloud() and mode not in {"s3", "r2", "supabase"}:
        raise RuntimeError("Production user-file storage requires an S3-compatible STORAGE_BACKEND")
    if _BACKEND is None or _BACKEND_SIGNATURE != signature:
        _BACKEND = create_storage_backend(_root())
        _BACKEND_SIGNATURE = signature
    return _BACKEND


def _storage_key(filename: str, kind: str) -> str:
    # Voice reference samples intentionally keep an owner-scoped canonical S3 key.
    # Only this controlled prefix may contain path separators in MediaAsset.filename.
    normalized = str(filename or "").replace("\\", "/").lstrip("/")
    if normalized.startswith("voice_references/"):
        parts = normalized.split("/")
        if len(parts) != 3 or any(not part or part in {".", ".."} for part in parts):
            raise ValueError("Invalid voice reference storage key")
        if _safe_filename(parts[-1]) != parts[-1]:
            raise ValueError("Invalid voice reference filename")
        return normalized
    safe_name = _safe_filename(filename)
    # Preserve the existing media retrieval contract: reference assets live in
    # references/, while every generated/document/voice derivative lives in generated/.
    prefix = "references" if kind == "reference" else "generated"
    return f"{prefix}/{safe_name}"


def save_bytes(data: bytes, mime: str, kind: str = "reference") -> Tuple[str, str, int]:
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("Storage payload must be bytes")
    filename = f"{uuid.uuid4().hex}{_ext_from_mime(mime)}"
    backend = _backend()
    key = _storage_key(filename, kind)
    backend.save(key, bytes(data))
    if isinstance(backend, LocalStorageBackend):
        location = str((_root() / key).resolve())
    else:
        location = f"s3://{getattr(backend, 'bucket', 'bucket')}/{key}"
    return filename, location, len(data)


def save_bytes_at_key(data: bytes, mime: str, key: str) -> Tuple[str, str, int]:
    """Persist bytes at an explicit canonical key (used for owner-scoped voice references)."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("Storage payload must be bytes")
    normalized = _storage_key(key, "reference")
    if not normalized.startswith("voice_references/"):
        raise ValueError("Explicit storage keys are restricted to voice_references/")
    backend = _backend()
    backend.save(normalized, bytes(data))
    if isinstance(backend, LocalStorageBackend):
        location = str((_root() / normalized).resolve())
    else:
        location = f"s3://{getattr(backend, 'bucket', 'bucket')}/{normalized}"
    return normalized, location, len(data)


def read_bytes(filename: str, kind: str = "reference") -> bytes:
    return _backend().read(_storage_key(filename, kind))


def delete_file(filename: str, kind: str = "reference") -> None:
    _backend().delete(_storage_key(filename, kind))


def storage_health() -> dict:
    mode = os.environ.get("STORAGE_BACKEND", "local").strip().lower()
    try:
        backend = _backend()
        backend.ping()
    except Exception as exc:
        return {
            "status": "FAIL",
            "backend": mode,
            "persistent": mode in {"s3", "r2", "supabase"},
            "error": type(exc).__name__,
        }
    return {
        "status": "OK",
        "backend": mode,
        "persistent": mode in {"s3", "r2", "supabase"},
    }
