
import asyncio

import pytest
from botocore.exceptions import ClientError


def _client_error(status: int, code: str = "", message: str = "storage failure") -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": message},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        "GetObject",
    )


def test_local_storage_backend_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    from storage import delete_file, read_bytes, save_bytes

    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    filename, location, size = save_bytes(b"hello", "text/plain", kind="reference")
    assert size == 5
    assert filename in location
    assert read_bytes(filename, "reference") == b"hello"
    delete_file(filename, "reference")
    with pytest.raises(FileNotFoundError):
        read_bytes(filename, "reference")


def test_s3_mode_requires_bucket_without_initializing_client(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.delenv("S3_BUCKET", raising=False)
    from storage_backends import create_storage_backend

    with pytest.raises(RuntimeError, match="S3_BUCKET"):
        create_storage_backend(__import__("pathlib").Path("."))


def test_local_storage_contract_metadata_listing_and_safe_keys(tmp_path):
    from storage_backends import LocalStorageBackend

    backend = LocalStorageBackend(tmp_path)
    backend.save("references/a.txt", b"one")
    backend.save("references/a-duplicate.txt", b"two")
    assert backend.read("references/a.txt") == b"one"
    assert backend.metadata("references/a.txt")["size"] == 3
    assert backend.list("references") == ["references/a-duplicate.txt", "references/a.txt"]
    backend.delete("references/a.txt")
    with pytest.raises(FileNotFoundError):
        backend.read("references/a.txt")
    with pytest.raises(ValueError):
        backend.read("../outside")


def test_s3_storage_contract_with_fake_compatible_client():
    from storage_backends import S3StorageBackend

    class Body:
        def __init__(self, value): self.value = value
        def read(self): return self.value

    class FakeClient:
        def __init__(self): self.objects = {}
        def put_object(self, Bucket, Key, Body): self.objects[(Bucket, Key)] = bytes(Body)
        def get_object(self, Bucket, Key):
            if (Bucket, Key) not in self.objects: raise FileNotFoundError(Key)
            return {"Body": Body(self.objects[(Bucket, Key)])}
        def delete_object(self, Bucket, Key): self.objects.pop((Bucket, Key), None)
        def list_objects_v2(self, Bucket, Prefix="", MaxKeys=None):
            items = [{"Key": key} for bucket, key in self.objects if bucket == Bucket and key.startswith(Prefix)]
            return {"Contents": items[:MaxKeys] if MaxKeys else items}
        def head_object(self, Bucket, Key):
            if (Bucket, Key) not in self.objects: raise FileNotFoundError(Key)
            return {"ContentLength": len(self.objects[(Bucket, Key)]), "ContentType": "text/plain"}

    backend = object.__new__(S3StorageBackend)
    backend.bucket = "test-bucket"
    backend.client = FakeClient()
    backend.ping()
    backend.save("generated/result.txt", b"hello")
    assert backend.read("generated/result.txt") == b"hello"
    assert backend.metadata("generated/result.txt")["size"] == 5
    assert backend.list("generated") == ["generated/result.txt"]
    backend.delete("generated/result.txt")
    with pytest.raises(FileNotFoundError):
        backend.read("generated/result.txt")
    with pytest.raises(ValueError):
        backend.save("../escape", b"x")


def test_s3_read_maps_missing_object_client_error_to_not_found():
    from storage_backends import S3StorageBackend, StorageObjectNotFound

    class MissingClient:
        def get_object(self, Bucket, Key):
            raise _client_error(404, "NoSuchKey")

    backend = object.__new__(S3StorageBackend)
    backend.bucket = "private-bucket"
    backend.client = MissingClient()

    with pytest.raises(StorageObjectNotFound) as exc_info:
        backend.read("generated/private-object.png")

    assert exc_info.value.operation == "GetObject"
    assert exc_info.value.http_status == 404
    assert exc_info.value.error_code == "NoSuchKey"


def test_s3_read_keeps_permission_failure_distinct_from_missing_object():
    from storage_backends import S3StorageBackend, StorageBackendError

    class DeniedClient:
        def get_object(self, Bucket, Key):
            raise _client_error(403, "AccessDenied")

    backend = object.__new__(S3StorageBackend)
    backend.bucket = "private-bucket"
    backend.client = DeniedClient()

    with pytest.raises(StorageBackendError) as exc_info:
        backend.read("generated/private-object.png")

    assert exc_info.value.operation == "GetObject"
    assert exc_info.value.http_status == 403
    assert exc_info.value.error_code == "AccessDenied"


def test_s3_read_keeps_missing_bucket_distinct_from_missing_object_even_with_404():
    from storage_backends import S3StorageBackend, StorageBackendError

    class MissingBucketClient:
        def get_object(self, Bucket, Key):
            raise _client_error(404, "NoSuchBucket")

    backend = object.__new__(S3StorageBackend)
    backend.bucket = "private-bucket"
    backend.client = MissingBucketClient()

    with pytest.raises(StorageBackendError) as exc_info:
        backend.read("generated/private-object.png")

    assert exc_info.value.operation == "GetObject"
    assert exc_info.value.http_status == 404
    assert exc_info.value.error_code == "NoSuchBucket"


def test_legacy_storage_facade_routes_production_to_cloud(monkeypatch):
    import storage

    class FakeBackend:
        bucket = "bucket"
        def __init__(self): self.objects = {}
        def save(self, key, data): self.objects[key] = data
        def read(self, key): return self.objects[key]
        def delete(self, key): self.objects.pop(key, None)
        def ping(self): return None

    fake = FakeBackend()
    monkeypatch.setenv("LUMINA_ENV", "production")
    monkeypatch.setenv("STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("S3_BUCKET", "bucket")
    monkeypatch.setattr(storage, "create_storage_backend", lambda root: fake)
    storage._BACKEND = None
    storage._BACKEND_SIGNATURE = None

    filename, location, size = storage.save_bytes(b"persistent", "text/plain", "reference")
    assert size == 10
    assert location.startswith("s3://bucket/references/")
    assert storage.read_bytes(filename, "reference") == b"persistent"


def test_production_rejects_local_user_file_storage(monkeypatch):
    import storage

    monkeypatch.setenv("LUMINA_ENV", "production")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    storage._BACKEND = None
    storage._BACKEND_SIGNATURE = None
    with pytest.raises(RuntimeError, match="S3-compatible"):
        storage.save_bytes(b"x", "text/plain", "reference")


def test_media_endpoint_logs_sanitized_storage_failure_details(monkeypatch, caplog):
    import server
    from fastapi import HTTPException
    from models import MediaAsset
    from storage_backends import StorageBackendError

    async def fake_get_media(media_id, owner):
        return MediaAsset(
            id=media_id,
            owner_email=owner,
            filename="secret-filename-that-must-not-appear.png",
            mime_type="image/png",
            kind="generated",
            source_module="documents",
        )

    def fake_read_bytes(filename, kind="reference"):
        raise StorageBackendError(
            "Storage GetObject failed",
            operation="GetObject",
            http_status=403,
            error_code="AccessDenied",
        )

    monkeypatch.setattr(server, "_get_media", fake_get_media)
    monkeypatch.setattr(server, "read_bytes", fake_read_bytes)

    with caplog.at_level("WARNING", logger="lumina"):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(server.get_media_file("media-1", owner="owner@example.com"))

    assert exc_info.value.status_code == 502
    assert "Media storage read failed" in caplog.text
    assert "operation=GetObject" in caplog.text
    assert "http_status=403" in caplog.text
    assert "error_code=AccessDenied" in caplog.text
    assert "storage_prefix=generated" in caplog.text
    assert "media_kind=generated" in caplog.text
    assert "source_module=documents" in caplog.text
    assert "secret-filename-that-must-not-appear" not in caplog.text
    assert "generated/secret-filename-that-must-not-appear.png" not in caplog.text
    assert "private-bucket" not in caplog.text
