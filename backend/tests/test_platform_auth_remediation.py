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
