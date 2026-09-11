import io
import os

import pytest


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
