"""Storage backends used by Lumina media services.

The application only depends on this small object interface. Local disk is the
default for development; the S3-compatible backend is suitable for Supabase
Storage gateways, Cloudflare R2, MinIO, and other private object stores. All
credentials are read server-side from environment variables.
"""
from __future__ import annotations

import os
import mimetypes
from pathlib import Path
from typing import Protocol


class StorageBackend(Protocol):
    def save(self, key: str, data: bytes) -> None: ...
    def read(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def list(self, prefix: str = "") -> list[str]: ...
    def metadata(self, key: str) -> dict: ...


def _safe_key(key: str) -> str:
    value = str(key or "").replace("\\", "/")
    parts = value.split("/")
    if not value or value.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Invalid storage key")
    return "/".join(parts)


class LocalStorageBackend:
    def __init__(self, root: Path):
        self.root = root

    def save(self, key: str, data: bytes) -> None:
        path = self.root / _safe_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read(self, key: str) -> bytes:
        return (self.root / _safe_key(key)).read_bytes()

    def delete(self, key: str) -> None:
        path = self.root / _safe_key(key)
        if path.exists():
            path.unlink()

    def list(self, prefix: str = "") -> list[str]:
        safe_prefix = str(prefix or "").replace("\\", "/").strip("/")
        if safe_prefix and any(part in {".", ".."} for part in safe_prefix.split("/")):
            raise ValueError("Invalid storage prefix")
        return sorted(
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
            if path.is_file() and path.relative_to(self.root).as_posix().startswith(safe_prefix)
        )

    def metadata(self, key: str) -> dict:
        path = self.root / _safe_key(key)
        stat = path.stat()
        return {"key": _safe_key(key), "size": stat.st_size, "content_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream"}


class S3StorageBackend:
    def __init__(self, bucket: str, endpoint_url: str | None, region: str):
        import boto3

        self.bucket = bucket
        self.client = boto3.client("s3", endpoint_url=endpoint_url or None, region_name=region)

    def save(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=_safe_key(key), Body=data)

    def read(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=_safe_key(key))["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=_safe_key(key))

    def list(self, prefix: str = "") -> list[str]:
        safe_prefix = str(prefix or "").replace("\\", "/").strip("/")
        if safe_prefix and any(part in {".", ".."} for part in safe_prefix.split("/")):
            raise ValueError("Invalid storage prefix")
        response = self.client.list_objects_v2(Bucket=self.bucket, Prefix=safe_prefix)
        return sorted(str(item["Key"]) for item in response.get("Contents", []) if item.get("Key"))

    def metadata(self, key: str) -> dict:
        safe_key = _safe_key(key)
        response = self.client.head_object(Bucket=self.bucket, Key=safe_key)
        return {"key": safe_key, "size": int(response.get("ContentLength", 0)), "content_type": response.get("ContentType")}


def create_storage_backend(root: Path) -> StorageBackend:
    mode = os.environ.get("STORAGE_BACKEND", "local").strip().lower()
    if mode in {"s3", "r2", "supabase"}:
        bucket = os.environ.get("S3_BUCKET", "").strip()
        if not bucket:
            raise RuntimeError("STORAGE_BACKEND requires S3_BUCKET")
        return S3StorageBackend(
            bucket=bucket,
            endpoint_url=os.environ.get("S3_ENDPOINT_URL", "").strip() or None,
            region=os.environ.get("S3_REGION", "auto").strip() or "auto",
        )
    if mode != "local":
        raise RuntimeError(f"Unsupported STORAGE_BACKEND: {mode}")
    return LocalStorageBackend(root)
