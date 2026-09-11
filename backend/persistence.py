from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger("lumina.persistence")

ACTIVE_JOB_STATUSES = {"queued", "preparing", "processing", "rendering", "installing", "running", "cancel_requested"}


def runtime_database_path() -> Path:
    configured = os.environ.get("LUMINA_SQLITE_PATH") or os.environ.get("LUMINA_DATABASE_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[1] / ".lumina-runtime" / "database" / "lumina.db"


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _json_default(value: Any) -> str:
    return str(value)


class PersistenceCursor:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows

    def sort(self, key: str, direction: int = 1) -> "PersistenceCursor":
        reverse = direction < 0
        self.rows.sort(key=lambda item: item.get(key) or "", reverse=reverse)
        return self

    def limit(self, count: int) -> "PersistenceCursor":
        self.rows = self.rows[: max(0, int(count))]
        return self

    def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        self._iter = iter(self.rows)
        return self

    async def __anext__(self) -> dict[str, Any]:
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class PersistenceProvider(ABC):
    name = "base"

    @abstractmethod
    async def initialize(self) -> None: ...

    @abstractmethod
    async def verify(self) -> None: ...

    async def ping(self) -> None:
        # Default compatibility path for custom providers. Concrete database
        # providers override this with a read-only SELECT/ping operation.
        await self.verify()

    @abstractmethod
    async def recover_active_jobs(self) -> None: ...

    @abstractmethod
    async def insert_one(self, table: str, document: dict[str, Any]) -> None: ...

    @abstractmethod
    async def find_one(self, table: str, query: dict[str, Any]) -> Optional[dict[str, Any]]: ...

    @abstractmethod
    def find(self, table: str, query: dict[str, Any]) -> PersistenceCursor: ...

    @abstractmethod
    async def update_one(self, table: str, query: dict[str, Any], update: dict[str, Any]) -> None: ...

    @abstractmethod
    async def replace_one(self, table: str, query: dict[str, Any], document: dict[str, Any]) -> None: ...

    @abstractmethod
    async def count_documents(self, table: str, query: dict[str, Any]) -> int: ...

    @abstractmethod
    def diagnostics(self) -> dict[str, Any]: ...


class MongoPersistenceProvider(PersistenceProvider):
    name = "mongo"

    def __init__(self, db: Any, client: Any):
        if db is None or client is None:
            raise ValueError("Mongo persistence requires both db and client")
        self.db = db
        self.client = client
        self.ready = False

    async def initialize(self) -> None:
        await asyncio.wait_for(self.client.admin.command("ping"), timeout=1.5)
        self.ready = True

    async def verify(self) -> None:
        await asyncio.wait_for(self.client.admin.command("ping"), timeout=1.5)

    async def recover_active_jobs(self) -> None:
        interrupted = {"$set": {"status": "failed", "stage": "interrupted", "safe_error_message": "The backend restarted before this job finished.", "error": "The backend restarted before this job finished.", "updated_at": _now_iso(), "completed_at": _now_iso()}}
        for table in ("talking_portrait_jobs", "talking_portrait_install_jobs"):
            await self.db[table].update_many({"status": {"$in": list(ACTIVE_JOB_STATUSES)}}, interrupted)

    async def insert_one(self, table: str, document: dict[str, Any]) -> None:
        await self.db[table].insert_one(document)

    async def find_one(self, table: str, query: dict[str, Any]) -> Optional[dict[str, Any]]:
        return await self.db[table].find_one(query, {"_id": 0})

    def find(self, table: str, query: dict[str, Any]) -> Any:
        return self.db[table].find(query, {"_id": 0})

    async def update_one(self, table: str, query: dict[str, Any], update: dict[str, Any]) -> None:
        await self.db[table].update_one(query, update)

    async def replace_one(self, table: str, query: dict[str, Any], document: dict[str, Any]) -> None:
        await self.db[table].replace_one(query, document)

    async def count_documents(self, table: str, query: dict[str, Any]) -> int:
        return await self.db[table].count_documents(query)

    def diagnostics(self) -> dict[str, Any]:
        return {"provider": self.name, "ready": self.ready, "fallback_active": False, "mongo_configured": True, "mongo_available": self.ready}


class SQLitePersistenceProvider(PersistenceProvider):
    name = "sqlite"
    TABLES = {
        "identity_packs", "media", "jobs", "gallery", "video_generation_jobs",
        "video_library_organizations", "video_templates", "video_brand_kits", "video_projects",
        "voice_jobs", "voice_library_organizations", "voice_packs", "voice_personal_models",
        "voice_projects", "voice_recordings", "transcription_jobs", "talking_face_jobs",
        "projects", "preferences", "notifications", "editor_sessions", "ai_edit_jobs",
        "photo_collections", "photo_batch_jobs", "documents", "document_versions",
        "company_profiles", "company_versions", "document_folders", "document_collections",
        "document_tags", "enterprise_document_templates",
        "enterprise_document_template_versions", "document_people", "document_banks",
        "document_clauses", "talking_portrait_jobs",
        "talking_portrait_install_jobs", "talking_portrait_logs", "talking_portrait_outputs",
        "provider_status",
        "driver_preferences", "driver_places", "driver_trips",
    }

    def __init__(self, path: Path | None = None, *, fallback_active: bool = False, mongo_configured: bool = False, mongo_available: bool = False):
        self.path = path or runtime_database_path()
        self.fallback_active = fallback_active
        self.mongo_configured = mongo_configured
        self.mongo_available = mongo_available
        self.ready = False
        self._lock = threading.RLock()

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=2.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=2000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize_sync(self) -> None:
        with self._lock, self._connect() as conn:
            # Journal mode is a database-level setting. Changing it on every
            # request connection can block on Windows while another request
            # still owns a read/write handle. Configure it once at startup.
            conn.execute("PRAGMA journal_mode=WAL")
            schema = """
            id TEXT PRIMARY KEY,
            owner_email TEXT,
            provider TEXT,
            status TEXT,
            stage TEXT,
            progress INTEGER DEFAULT 0,
            title TEXT,
            source_photo_path TEXT,
            audio_path TEXT,
            output_path TEXT,
            settings_json TEXT,
            error_code TEXT,
            safe_error_message TEXT,
            technical_details TEXT,
            created_at TEXT,
            started_at TEXT,
            updated_at TEXT,
            completed_at TEXT,
            data_json TEXT NOT NULL
            """
            for table in self.TABLES:
                conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({schema})")
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_owner_status_updated ON {table}(owner_email, status, updated_at)")
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_created ON {table}(created_at)")
            conn.commit()
        self.ready = True

    async def verify(self) -> None:
        probe = {"id": "__persistence_probe__", "status": "ok", "updated_at": _now_iso(), "created_at": _now_iso()}
        await self.insert_one("provider_status", probe)
        found = await self.find_one("provider_status", {"id": probe["id"]})
        if not found:
            raise RuntimeError("SQLite persistence read/write verification failed")
        await self.update_one("provider_status", {"id": probe["id"]}, {"$set": {"status": "verified", "updated_at": _now_iso()}})

    def _ping_sync(self) -> None:
        with self._connect() as conn:
            conn.execute("SELECT 1").fetchone()

    async def ping(self) -> None:
        await asyncio.to_thread(self._ping_sync)

    async def recover_active_jobs(self) -> None:
        interrupted = {"status": "failed", "stage": "interrupted", "safe_error_message": "The backend restarted before this job finished.", "error": "The backend restarted before this job finished.", "updated_at": _now_iso(), "completed_at": _now_iso()}
        for table in ("talking_portrait_jobs", "talking_portrait_install_jobs"):
            for status in ACTIVE_JOB_STATUSES:
                rows = list((await asyncio.to_thread(self._find_sync, table, {"status": status})))
                for row in rows:
                    await self.update_one(table, {"id": row["id"]}, {"$set": interrupted})

    def _normalize(self, table: str, document: dict[str, Any]) -> dict[str, Any]:
        data = dict(document)
        document_id = str(data.get("id") or data.get("install_job_id") or _now_iso())
        data["id"] = document_id
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        return {
            "id": document_id,
            "owner_email": data.get("owner_email"),
            "provider": data.get("provider"),
            "status": data.get("status"),
            "stage": data.get("stage") or metadata.get("stage"),
            "progress": int(data.get("progress") or 0),
            "title": data.get("title") or data.get("step"),
            "source_photo_path": data.get("source_photo_path") or data.get("portrait_media_id"),
            "audio_path": data.get("audio_path") or data.get("audio_media_id"),
            "output_path": data.get("output_path") or data.get("output_media_id"),
            "settings_json": json.dumps(metadata or data.get("settings") or {}, default=_json_default),
            "error_code": data.get("error_code"),
            "safe_error_message": data.get("full_user_safe_error") or data.get("error"),
            "technical_details": json.dumps(data.get("technical_details") or metadata.get("technical_details") or {}, default=_json_default),
            "created_at": data.get("created_at") or _now_iso(),
            "started_at": data.get("started_at"),
            "updated_at": data.get("updated_at") or _now_iso(),
            "completed_at": data.get("completed_at"),
            "data_json": json.dumps(data, default=_json_default),
        }

    def _upsert_sync(self, table: str, document: dict[str, Any]) -> None:
        if table not in self.TABLES:
            raise ValueError(f"Unsupported SQLite persistence table: {table}")
        row = self._normalize(table, document)
        cols = list(row.keys())
        sql = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})"
        with self._lock, self._connect() as conn:
            conn.execute(sql, [row[col] for col in cols])
            conn.commit()

    async def insert_one(self, table: str, document: dict[str, Any]) -> None:
        await asyncio.to_thread(self._upsert_sync, table, document)

    def _matches(self, item: dict[str, Any], query: dict[str, Any]) -> bool:
        for key, expected in query.items():
            if key == "$or":
                if not any(self._matches(item, clause) for clause in expected):
                    return False
                continue
            if key == "$and":
                if not all(self._matches(item, clause) for clause in expected):
                    return False
                continue
            actual = item.get(key)
            if isinstance(expected, dict):
                if "$in" in expected:
                    wanted = set(expected["$in"])
                    if isinstance(actual, list):
                        if not wanted.intersection(actual):
                            return False
                    elif actual not in wanted:
                        return False
                if "$ne" in expected and actual == expected["$ne"]:
                    return False
                if "$all" in expected:
                    actual_set = set(actual or []) if isinstance(actual, list) else {actual}
                    if not set(expected["$all"]).issubset(actual_set):
                        return False
                if "$regex" in expected:
                    import re
                    flags = re.I if "i" in str(expected.get("$options", "")) else 0
                    if not re.search(str(expected["$regex"]), str(actual or ""), flags):
                        return False
            elif actual != expected:
                return False
        return True

    def _find_sync(self, table: str, query: dict[str, Any]) -> list[dict[str, Any]]:
        if table not in self.TABLES:
            raise ValueError(f"Unsupported SQLite persistence table: {table}")
        with self._lock, self._connect() as conn:
            rows = conn.execute(f"SELECT data_json FROM {table}").fetchall()
        docs = [json.loads(row["data_json"]) for row in rows]
        return [doc for doc in docs if self._matches(doc, query)]

    async def find_one(self, table: str, query: dict[str, Any]) -> Optional[dict[str, Any]]:
        rows = await asyncio.to_thread(self._find_sync, table, query)
        return rows[0] if rows else None

    def find(self, table: str, query: dict[str, Any]) -> PersistenceCursor:
        rows = self._find_sync(table, query)
        return PersistenceCursor(rows)

    def _apply_set(self, document: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
        doc = dict(document)
        for key, value in values.items():
            if "." in key:
                head, tail = key.split(".", 1)
                nested = dict(doc.get(head) or {})
                nested[tail] = value
                doc[head] = nested
            else:
                doc[key] = value
        return doc

    def _apply_update(self, document: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
        doc = dict(document)
        if "$set" in update:
            doc = self._apply_set(doc, update.get("$set") or {})
        if "$addToSet" in update:
            for key, value in (update.get("$addToSet") or {}).items():
                values = list(doc.get(key) or [])
                if value not in values:
                    values.append(value)
                doc[key] = values
        if "$pull" in update:
            for key, value in (update.get("$pull") or {}).items():
                doc[key] = [item for item in list(doc.get(key) or []) if item != value]
        if not any(str(key).startswith("$") for key in update):
            doc = self._apply_set(doc, update)
        return doc

    async def update_one(self, table: str, query: dict[str, Any], update: dict[str, Any]) -> None:
        doc = await self.find_one(table, query)
        if not doc:
            return
        await self.insert_one(table, self._apply_update(doc, update))

    async def update_many(self, table: str, query: dict[str, Any], update: dict[str, Any]) -> int:
        rows = await asyncio.to_thread(self._find_sync, table, query)
        for row in rows:
            await self.insert_one(table, self._apply_update(row, update))
        return len(rows)

    async def replace_one(self, table: str, query: dict[str, Any], document: dict[str, Any]) -> None:
        existing = await self.find_one(table, query)
        if not existing:
            return
        replacement = dict(document)
        if not replacement.get("id") and existing.get("id"):
            replacement["id"] = existing["id"]
        await self.insert_one(table, replacement)

    def _delete_sync(self, table: str, query: dict[str, Any]) -> int:
        rows = self._find_sync(table, {})
        keep = [row for row in rows if not self._matches(row, query)]
        deleted = len(rows) - len(keep)
        if deleted:
            with self._lock, self._connect() as conn:
                conn.execute(f"DELETE FROM {table}")
                conn.commit()
            for row in keep:
                self._upsert_sync(table, row)
        return deleted

    async def delete_one(self, table: str, query: dict[str, Any]) -> int:
        return await asyncio.to_thread(self._delete_sync, table, query)

    async def delete_many(self, table: str, query: dict[str, Any]) -> int:
        return await asyncio.to_thread(self._delete_sync, table, query)

    async def count_documents(self, table: str, query: dict[str, Any]) -> int:
        return len(await asyncio.to_thread(self._find_sync, table, query))

    def diagnostics(self) -> dict[str, Any]:
        return {"provider": self.name, "ready": self.ready, "path": str(self.path), "fallback_active": self.fallback_active, "mongo_configured": self.mongo_configured, "mongo_available": self.mongo_available}


def export_sqlite_records_for_postgres(provider: SQLitePersistenceProvider, tables: set[str] | None = None) -> list[dict[str, Any]]:
    """Return a lossless, PostgreSQL-compatible export without writing data.

    The PostgreSQL adapter stores the original JSON document in ``data_json``
    under a namespace and stable id. This helper is deliberately read-only so
    migration can be reviewed or dry-run validated before any cloud write.
    """
    selected = tables or set(provider.TABLES)
    unknown = selected - provider.TABLES
    if unknown:
        raise ValueError(f"Unsupported SQLite tables: {sorted(unknown)}")
    exported: list[dict[str, Any]] = []
    for table in sorted(selected):
        for document in provider._find_sync(table, {}):
            document_id = str(document.get("id") or "")
            if not document_id:
                raise ValueError(f"SQLite record in {table} has no id")
            exported.append({
                "namespace": table,
                "id": document_id,
                "owner_email": document.get("owner_email"),
                "data_json": json.dumps(document, default=_json_default, sort_keys=True),
                "created_at": document.get("created_at"),
            })
    return exported


class PostgresPersistenceProvider(PersistenceProvider):
    """Small generic PostgreSQL adapter for the existing collection contract.

    Records stay JSON-shaped so SQLite and PostgreSQL can share all domain
    services during migration. It intentionally uses one namespaced table,
    allowing a Supabase/PostgreSQL deployment without destructive migration.
    """
    name = "postgres"

    def __init__(self, dsn: str):
        if not dsn:
            raise ValueError("PostgreSQL persistence requires DATABASE_URL or POSTGRES_DSN")
        self.dsn = dsn
        self.ready = False

    def _matches(self, item: dict[str, Any], query: dict[str, Any]) -> bool:
        return SQLitePersistenceProvider._matches(self, item, query)

    def _apply_set(self, document: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
        return SQLitePersistenceProvider._apply_set(self, document, values)

    def _apply_update(self, document: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
        return SQLitePersistenceProvider._apply_update(self, document, update)

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - exercised only when selected
            raise RuntimeError("PostgreSQL mode requires the optional psycopg[binary] dependency") from exc
        return psycopg.connect(self.dsn)

    def _sql_where(self, table: str, query: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
        """Push direct owner/id predicates into PostgreSQL.

        Complex Mongo-style predicates are still evaluated by the shared
        matcher after the narrowed result set is returned.
        """
        clauses = ["namespace = %s"]
        params: list[Any] = [table]
        for field in ("owner_email", "id"):
            if field not in query:
                continue
            expected = query[field]
            if isinstance(expected, dict):
                if "$in" not in expected:
                    continue
                values = list(expected.get("$in") or [])
                if not values:
                    clauses.append("FALSE")
                    continue
                placeholders = ", ".join(["%s"] * len(values))
                clauses.append(f"{field} IN ({placeholders})")
                params.extend(str(value) if field == "id" else value for value in values)
                continue
            if expected is None:
                clauses.append(f"{field} IS NULL")
            else:
                clauses.append(f"{field} = %s")
                params.append(str(expected) if field == "id" else expected)
        return " AND ".join(clauses), tuple(params)

    def _rows(self, table: str, query: dict[str, Any]) -> list[dict[str, Any]]:
        where_sql, params = self._sql_where(table, query)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT data_json FROM lumina_records WHERE {where_sql}", params)
            rows = [json.loads(row[0]) for row in cur.fetchall()]
        return [row for row in rows if SQLitePersistenceProvider._matches(self, row, query)]

    def _write(self, table: str, document: dict[str, Any]) -> None:
        payload = dict(document)
        payload["id"] = str(payload.get("id") or _now_iso())
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO lumina_records(namespace, id, owner_email, data_json)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT(namespace, id) DO UPDATE SET
                   owner_email = EXCLUDED.owner_email, data_json = EXCLUDED.data_json""",
                (table, payload["id"], payload.get("owner_email"), json.dumps(payload, default=_json_default)),
            )

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS lumina_records (
                namespace TEXT NOT NULL,
                id TEXT NOT NULL,
                owner_email TEXT,
                data_json TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY(namespace, id)
            )""")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_lumina_records_owner ON lumina_records(owner_email)")
        self.ready = True

    async def verify(self) -> None:
        probe = {"id": "__persistence_probe__", "status": "ok", "created_at": _now_iso()}
        await self.insert_one("provider_status", probe)
        if not await self.find_one("provider_status", {"id": probe["id"]}):
            raise RuntimeError("PostgreSQL persistence read/write verification failed")

    def _ping_sync(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()

    async def ping(self) -> None:
        await asyncio.to_thread(self._ping_sync)

    async def recover_active_jobs(self) -> None:
        for table in ("talking_portrait_jobs", "talking_portrait_install_jobs"):
            for row in await asyncio.to_thread(self._rows, table, {}):
                if row.get("status") in ACTIVE_JOB_STATUSES:
                    row.update({"status": "failed", "stage": "interrupted", "safe_error_message": "The backend restarted before this job finished.", "updated_at": _now_iso(), "completed_at": _now_iso()})
                    await self.insert_one(table, row)

    async def insert_one(self, table: str, document: dict[str, Any]) -> None:
        await asyncio.to_thread(self._write, table, document)

    async def find_one(self, table: str, query: dict[str, Any]) -> Optional[dict[str, Any]]:
        rows = await asyncio.to_thread(self._rows, table, query)
        return rows[0] if rows else None

    def find(self, table: str, query: dict[str, Any]) -> PersistenceCursor:
        return PersistenceCursor(self._rows(table, query))

    async def update_one(self, table: str, query: dict[str, Any], update: dict[str, Any]) -> None:
        row = await self.find_one(table, query)
        if row:
            await self.insert_one(table, SQLitePersistenceProvider._apply_update(self, row, update))

    async def replace_one(self, table: str, query: dict[str, Any], document: dict[str, Any]) -> None:
        row = await self.find_one(table, query)
        if row:
            replacement = dict(document)
            replacement.setdefault("id", row.get("id"))
            await self.insert_one(table, replacement)

    async def delete_one(self, table: str, query: dict[str, Any]) -> int:
        rows = await asyncio.to_thread(self._rows, table, query)
        if not rows:
            return 0
        with self._connect() as conn, conn.cursor() as cur:
            for row in rows:
                cur.execute("DELETE FROM lumina_records WHERE namespace = %s AND id = %s", (table, row["id"]))
        return len(rows)

    async def count_documents(self, table: str, query: dict[str, Any]) -> int:
        return len(await asyncio.to_thread(self._rows, table, query))

    def diagnostics(self) -> dict[str, Any]:
        return {"provider": self.name, "ready": self.ready, "dsn_configured": bool(self.dsn), "fallback_active": False}


class TalkingPortraitCollection:
    def __init__(self, provider: PersistenceProvider, table: str):
        self.provider = provider
        self.table = table

    async def insert_one(self, document: dict[str, Any]) -> None:
        await self.provider.insert_one(self.table, document)

    async def find_one(self, query: dict[str, Any], projection: dict[str, Any] | None = None) -> Optional[dict[str, Any]]:
        del projection
        return await self.provider.find_one(self.table, query)

    def find(self, query: dict[str, Any], projection: dict[str, Any] | None = None) -> Any:
        del projection
        return self.provider.find(self.table, query)

    async def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> None:
        await self.provider.update_one(self.table, query, update)

    async def update_many(self, query: dict[str, Any], update: dict[str, Any]) -> Any:
        modified = await self.provider.update_many(self.table, query, update)
        return type("UpdateResult", (), {"modified_count": modified})()

    async def replace_one(self, query: dict[str, Any], document: dict[str, Any]) -> None:
        await self.provider.replace_one(self.table, query, document)

    async def count_documents(self, query: dict[str, Any]) -> int:
        return await self.provider.count_documents(self.table, query)


class LocalPersistenceCollection:
    def __init__(self, provider: SQLitePersistenceProvider, table: str):
        self.provider = provider
        self.table = table

    async def insert_one(self, document: dict[str, Any]) -> None:
        await self.provider.insert_one(self.table, document)

    async def find_one(self, query: dict[str, Any], projection: dict[str, Any] | None = None) -> Optional[dict[str, Any]]:
        doc = await self.provider.find_one(self.table, query)
        return _project_document(doc, projection)

    def find(self, query: dict[str, Any], projection: dict[str, Any] | None = None) -> PersistenceCursor:
        cursor = self.provider.find(self.table, query)
        if projection:
            cursor.rows = [_project_document(row, projection) or {} for row in cursor.rows]
        return cursor

    async def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> None:
        await self.provider.update_one(self.table, query, update)

    async def update_many(self, query: dict[str, Any], update: dict[str, Any]) -> Any:
        modified = await self.provider.update_many(self.table, query, update)
        return type("UpdateResult", (), {"modified_count": modified})()

    async def replace_one(self, query: dict[str, Any], document: dict[str, Any], upsert: bool = False) -> None:
        existing = await self.provider.find_one(self.table, query)
        if existing:
            await self.provider.replace_one(self.table, query, document)
        elif upsert:
            await self.provider.insert_one(self.table, document)

    async def delete_one(self, query: dict[str, Any]) -> Any:
        deleted = await self.provider.delete_one(self.table, query)
        return type("DeleteResult", (), {"deleted_count": deleted})()

    async def delete_many(self, query: dict[str, Any]) -> Any:
        deleted = await self.provider.delete_many(self.table, query)
        return type("DeleteResult", (), {"deleted_count": deleted})()

    async def find_one_and_update(self, query: dict[str, Any], update: dict[str, Any], return_document: Any = None, projection: dict[str, Any] | None = None) -> Optional[dict[str, Any]]:
        del return_document
        doc = await self.provider.find_one(self.table, query)
        if not doc:
            return None
        new_doc = self.provider._apply_update(doc, update)
        await self.provider.insert_one(self.table, new_doc)
        return _project_document(new_doc, projection)

    async def find_one_and_delete(self, query: dict[str, Any], projection: dict[str, Any] | None = None) -> Optional[dict[str, Any]]:
        doc = await self.provider.find_one(self.table, query)
        if not doc:
            return None
        await self.provider.delete_one(self.table, query)
        return _project_document(doc, projection)

    async def count_documents(self, query: dict[str, Any]) -> int:
        return await self.provider.count_documents(self.table, query)


def _project_document(document: Optional[dict[str, Any]], projection: dict[str, Any] | None) -> Optional[dict[str, Any]]:
    if document is None or not projection:
        return document
    doc = dict(document)
    if projection.get("_id") == 0:
        doc.pop("_id", None)
    include = {key for key, value in projection.items() if key != "_id" and value}
    if include:
        doc = {key: doc[key] for key in include if key in doc}
    return doc


def _database_mode() -> str:
    mode = os.environ.get("LUMINA_DATABASE_PROVIDER", "sqlite").strip().lower()
    if mode not in {"sqlite", "mongo", "postgres", "auto"}:
        logger.warning("Unknown LUMINA_DATABASE_PROVIDER=%s; using sqlite", mode)
        return "sqlite"
    return mode


def create_persistence_provider(db: Any = None, client: Any = None) -> PersistenceProvider:
    mode = _database_mode()
    if mode == "postgres":
        return PostgresPersistenceProvider(os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_DSN") or "")
    if mode == "mongo" and db is not None and client is not None:
        return MongoPersistenceProvider(db, client)
    return SQLitePersistenceProvider(
        mongo_configured=bool(os.environ.get("MONGO_URL")),
        mongo_available=False,
    )


async def initialize_persistence_provider(db: Any = None, client: Any = None) -> PersistenceProvider:
    mode = _database_mode()
    if mode == "postgres":
        provider = PostgresPersistenceProvider(os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_DSN") or "")
        await provider.initialize()
        await provider.verify()
        await provider.recover_active_jobs()
        return provider
    mongo_configured = bool(os.environ.get("MONGO_URL"))

    if mode in {"mongo", "auto"} and db is not None and client is not None and mongo_configured:
        try:
            mongo = MongoPersistenceProvider(db, client)
            await mongo.initialize()
            await mongo.verify()
            await mongo.recover_active_jobs()
            return mongo
        except Exception:
            if mode == "mongo":
                raise
            logger.warning("Mongo unavailable; falling back to SQLite", exc_info=True)
            provider = SQLitePersistenceProvider(
                fallback_active=True,
                mongo_configured=True,
                mongo_available=False,
            )
            await provider.initialize()
            await provider.verify()
            await provider.recover_active_jobs()
            return provider

    if mode == "mongo":
        raise RuntimeError("Mongo persistence requested but MONGO_URL/db/client is unavailable")

    provider = SQLitePersistenceProvider(
        fallback_active=(mode == "auto" and mongo_configured),
        mongo_configured=mongo_configured,
        mongo_available=False,
    )
    await provider.initialize()
    await provider.verify()
    await provider.recover_active_jobs()
    return provider
