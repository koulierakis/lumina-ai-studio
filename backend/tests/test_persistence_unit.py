from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from persistence import SQLitePersistenceProvider, initialize_persistence_provider


def run(coro):
    return asyncio.run(coro)


def test_sqlite_default_startup_windows_project_path(tmp_path, monkeypatch):
    db_path = tmp_path / ".lumina-runtime" / "database" / "lumina.db"
    monkeypatch.setenv("LUMINA_DATABASE_PROVIDER", "sqlite")
    provider = SQLitePersistenceProvider(db_path)
    run(provider.initialize())
    run(provider.verify())
    diagnostics = provider.diagnostics()
    assert diagnostics["provider"] == "sqlite"
    assert diagnostics["ready"] is True
    assert str(db_path).endswith(str(Path(".lumina-runtime") / "database" / "lumina.db"))
    assert db_path.exists()


def test_talking_portrait_job_listing_without_mongodb(tmp_path):
    provider = SQLitePersistenceProvider(tmp_path / "lumina.db")
    run(provider.initialize())
    run(provider.insert_one("talking_portrait_jobs", {"id": "job-1", "owner_email": "owner@lumina.local", "status": "queued", "title": "Local job", "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"}))

    async def collect():
        return [row async for row in provider.find("talking_portrait_jobs", {"owner_email": "owner@lumina.local"}).sort("created_at", -1).limit(10)]

    rows = run(collect())
    assert rows[0]["id"] == "job-1"


def test_install_job_creation_without_mongodb(tmp_path):
    provider = SQLitePersistenceProvider(tmp_path / "lumina.db")
    run(provider.initialize())
    run(provider.insert_one("talking_portrait_install_jobs", {"id": "install-1", "install_job_id": "install-1", "owner_email": "owner@lumina.local", "provider": "liveportrait", "status": "queued", "stage": "preflight", "progress": 0}))
    found = run(provider.find_one("talking_portrait_install_jobs", {"id": "install-1", "owner_email": "owner@lumina.local"}))
    assert found["install_job_id"] == "install-1"


def test_database_persistence_after_restart(tmp_path):
    db_path = tmp_path / "lumina.db"
    first = SQLitePersistenceProvider(db_path)
    run(first.initialize())
    run(first.insert_one("talking_portrait_jobs", {"id": "persisted", "owner_email": "owner@lumina.local", "status": "completed", "title": "Persisted"}))
    second = SQLitePersistenceProvider(db_path)
    run(second.initialize())
    assert run(second.find_one("talking_portrait_jobs", {"id": "persisted"}))["title"] == "Persisted"


def test_sqlite_supports_all_document_studio_library_tables(tmp_path):
    provider = SQLitePersistenceProvider(tmp_path / "lumina.db")
    run(provider.initialize())
    tables = (
        "document_collections",
        "document_tags",
        "enterprise_document_templates",
        "enterprise_document_template_versions",
    )

    for table in tables:
        run(provider.insert_one(table, {"id": f"{table}-1", "owner_email": "owner@lumina.local"}))
        assert run(provider.find_one(table, {"id": f"{table}-1"}))["owner_email"] == "owner@lumina.local"


def test_concurrent_sqlite_access(tmp_path):
    provider = SQLitePersistenceProvider(tmp_path / "lumina.db")
    run(provider.initialize())

    async def write_many():
        await asyncio.gather(*[provider.insert_one("talking_portrait_jobs", {"id": f"job-{idx}", "owner_email": "owner@lumina.local", "status": "queued"}) for idx in range(20)])

    run(write_many())
    assert run(provider.count_documents("talking_portrait_jobs", {"owner_email": "owner@lumina.local"})) == 20


def test_startup_recovery_marks_interrupted_jobs(tmp_path):
    provider = SQLitePersistenceProvider(tmp_path / "lumina.db")
    run(provider.initialize())
    run(provider.insert_one("talking_portrait_jobs", {"id": "active", "owner_email": "owner@lumina.local", "status": "rendering"}))
    run(provider.recover_active_jobs())
    assert run(provider.find_one("talking_portrait_jobs", {"id": "active"}))["status"] == "failed"


def test_auto_fallback_no_30_second_timeout(monkeypatch):
    class SlowFailClient:
        class Admin:
            async def command(self, name):
                await asyncio.sleep(5)
        admin = Admin()

    monkeypatch.setenv("LUMINA_DATABASE_PROVIDER", "auto")
    monkeypatch.setenv("MONGO_URL", "mongodb://localhost:27017")
    start = time.perf_counter()
    provider = run(initialize_persistence_provider(db=object(), client=SlowFailClient()))
    elapsed = time.perf_counter() - start
    assert provider.diagnostics()["provider"] == "sqlite"
    assert provider.diagnostics()["fallback_active"] is True
    assert elapsed < 3


def test_mongo_required_fails_clearly(monkeypatch):
    class FailClient:
        class Admin:
            async def command(self, name):
                raise RuntimeError("mongo unavailable")
        admin = Admin()

    monkeypatch.setenv("LUMINA_DATABASE_PROVIDER", "mongo")
    monkeypatch.setenv("MONGO_URL", "mongodb://localhost:27017")
    with pytest.raises(RuntimeError, match="mongo unavailable"):
        run(initialize_persistence_provider(db=object(), client=FailClient()))
