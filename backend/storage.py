"""Local disk storage for private media assets."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Tuple
import uuid

import boto3

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
        "audio/flac": ".flac", "audio/ogg": ".ogg", "audio/aac": ".aac", "audio/mp4": ".m4a",
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "text/plain": ".txt", "text/html": ".html", "text/markdown": ".md",
    }.get(mime.lower(), ".png")


def _safe_filename(filename: str) -> str:
    candidate = os.path.basename(filename)
    if not candidate or candidate != filename or ".." in candidate:
        raise ValueError("Invalid filename")
    return candidate


def _kind_dir(root: Path, kind: str) -> Path:
    return root / ("references" if kind == "reference" else "generated")


def _uses_s3() -> bool:
    return os.environ.get("STORAGE_BACKEND", "local").strip().lower() in {"s3", "supabase"}


def _s3_bucket() -> str:
    bucket = os.environ.get("S3_BUCKET", "").strip()
    if not bucket:
        raise RuntimeError("S3_BUCKET is required when STORAGE_BACKEND is s3.")
    return bucket


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None,
        region_name=os.environ.get("S3_REGION") or "auto",
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY_ID") or None,
        aws_secret_access_key=os.environ.get("S3_SECRET_ACCESS_KEY") or None,
    )


def _object_key(filename: str, kind: str) -> str:
    folder = "references" if kind == "reference" else "generated"
    return f"{folder}/{_safe_filename(filename)}"


def save_bytes(data: bytes, mime: str, kind: str = "reference") -> Tuple[str, str, int]:
    """Save bytes to disk. Returns (filename, absolute_path, size_bytes)."""
    if kind not in {"reference", "generated"}:
        raise ValueError("Invalid storage kind")
    ext = _ext_from_mime(mime)
    filename = f"{uuid.uuid4().hex}{ext}"
    if _uses_s3():
        _s3_client().put_object(Bucket=_s3_bucket(), Key=_object_key(filename, kind), Body=data, ContentType=mime)
        return filename, f"s3://{_s3_bucket()}/{_object_key(filename, kind)}", len(data)
    abs_path = _kind_dir(_root(), kind) / filename
    abs_path.write_bytes(data)
    return filename, str(abs_path), len(data)


def read_bytes(filename: str, kind: str = "reference") -> bytes:
    if kind not in {"reference", "generated"}:
        raise ValueError("Invalid storage kind")
    safe_name = _safe_filename(filename)
    if _uses_s3():
        response = _s3_client().get_object(Bucket=_s3_bucket(), Key=_object_key(safe_name, kind))
        return response["Body"].read()
    abs_path = _kind_dir(_root(), kind) / safe_name
    return abs_path.read_bytes()


def delete_file(filename: str, kind: str = "reference") -> None:
    if kind not in {"reference", "generated"}:
        return
    safe_name = _safe_filename(filename)
    if _uses_s3():
        _s3_client().delete_object(Bucket=_s3_bucket(), Key=_object_key(safe_name, kind))
        return
    p = _kind_dir(_root(), kind) / safe_name
    if p.exists():
        p.unlink()
