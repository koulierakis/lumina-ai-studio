from __future__ import annotations

import asyncio

from persistence import PostgresPersistenceProvider


def test_postgres_pushes_owner_and_id_into_sql_where():
    provider = PostgresPersistenceProvider("postgresql://example.invalid/db")
    where_sql, params = provider._sql_where(
        "media",
        {"owner_email": "owner@example.com", "id": "media-1", "status": "ready"},
    )
    assert where_sql == "namespace = %s AND owner_email = %s AND id = %s"
    assert params == ("media", "owner@example.com", "media-1")


def test_postgres_pushes_id_in_filter_into_sql_where():
    provider = PostgresPersistenceProvider("postgresql://example.invalid/db")
    where_sql, params = provider._sql_where("media", {"id": {"$in": ["a", "b"]}})
    assert where_sql == "namespace = %s AND id IN (%s, %s)"
    assert params == ("media", "a", "b")


def test_postgres_ping_is_read_only(monkeypatch):
    provider = PostgresPersistenceProvider("postgresql://example.invalid/db")
    calls = []

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, sql, params=None): calls.append((sql, params))
        def fetchone(self): return (1,)

    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def cursor(self): return Cursor()

    monkeypatch.setattr(provider, "_connect", lambda: Connection())
    asyncio.run(provider.ping())
    assert calls == [("SELECT 1", None)]


def test_postgres_update_many_applies_update_and_reports_count(monkeypatch):
    provider = PostgresPersistenceProvider("postgresql://example.invalid/db")
    written = []

    async def fake_insert_one(table, document):
        written.append((table, dict(document)))

    rows = [
        {"id": "n-1", "owner_email": "owner@example.com", "read": False},
        {"id": "n-2", "owner_email": "owner@example.com", "read": False},
    ]
    monkeypatch.setattr(provider, "insert_one", fake_insert_one)
    monkeypatch.setattr(provider, "_rows", lambda table, query: rows)

    count = asyncio.run(
        provider.update_many(
            "notifications",
            {"owner_email": "owner@example.com", "read": False},
            {"$set": {"read": True}},
        )
    )

    assert count == 2
    assert len(written) == 2
    assert all(table == "notifications" for table, _ in written)
    assert all(doc["read"] is True for _, doc in written)
    assert {doc["id"] for _, doc in written} == {"n-1", "n-2"}


def test_postgres_delete_many_pushes_named_deletes_and_reports_count(monkeypatch):
    provider = PostgresPersistenceProvider("postgresql://example.invalid/db")
    executed = []

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, sql, params=None): executed.append((sql, params))

    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def cursor(self): return Cursor()

    rows = [
        {"id": "v-1", "owner_email": "owner@example.com"},
        {"id": "v-2", "owner_email": "owner@example.com"},
    ]
    monkeypatch.setattr(provider, "_connect", lambda: Connection())
    monkeypatch.setattr(provider, "_rows", lambda table, query: rows)

    count = asyncio.run(
        provider.delete_many("versions", {"document_id": "doc-1", "owner_email": "owner@example.com"})
    )

    assert count == 2
    assert executed == [
        ("DELETE FROM lumina_records WHERE namespace = %s AND id = %s", ("versions", "v-1")),
        ("DELETE FROM lumina_records WHERE namespace = %s AND id = %s", ("versions", "v-2")),
    ]


def test_postgres_delete_many_returns_zero_when_nothing_matches(monkeypatch):
    provider = PostgresPersistenceProvider("postgresql://example.invalid/db")
    monkeypatch.setattr(provider, "_rows", lambda table, query: [])
    count = asyncio.run(
        provider.delete_many("versions", {"document_id": "missing", "owner_email": "owner@example.com"})
    )
    assert count == 0
