"""Checkpoint & resume backed by MongoDB with a local durable fallback.

The local fallback keeps jobs across process restarts on the same Render
instance, even when no external MongoDB is configured. MongoDB remains the
source of truth when available.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import tarfile
import time
from pathlib import Path
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from .. import workspace
from ..models import Job


logger = logging.getLogger(__name__)

COLLECTION = "gold_jobs"


class PersistenceError(RuntimeError):
    """A critical (state-transition) checkpoint could not be persisted.

    Raised only for ownership/state transitions that must fail closed: a
    recovery claim, a pause, or a terminal recovery outcome. Ordinary job
    progress persistence stays best-effort (see :func:`save_job`).
    """


class OwnershipConfigError(ValueError):
    """Unsafe/invalid ownership configuration for the current deployment.

    Raised when a production deployment cannot be proven safe: an unset
    ownership mode in production, or a ``single_host`` choice in a production
    (e.g. Render) deployment. This is intentionally fail-closed — a production
    configuration mistake must never silently enable host-local ownership.
    """


class ConditionalWriteResult:
    """Outcome of a compare-and-set checkpoint write.

    ``applied`` is True only when the caller's exact expected state matched the
    persisted document and the write succeeded. ``doc_found`` distinguishes
    "another writer already advanced past us" from "no document exists yet".
    """

    __slots__ = ("applied", "doc_found")

    def __init__(self, applied: bool, doc_found: bool) -> None:
        self.applied = applied
        self.doc_found = doc_found
_PG_TABLE = "gold_builder_jobs"
_ARCHIVE_INTERVAL_S = 30.0
_last_archive_at: dict[str, float] = {}


# --------------------------------------------------------------------------- ownership mode
#
# Source of truth for recovery ownership:
#
#   * ``distributed`` — a shared compare-and-set backend (MongoDB) is the ONLY
#     authority for claiming recovery ownership. A host-local file lock never
#     confers ownership. If the shared backend is unreachable, or the shared job
#     document is unexpectedly missing, the claim fails closed and no execution
#     starts. This is the correct mode for any deployment that runs more than
#     one host/worker against the same jobs.
#
#   * ``single_host`` — the host-local checkpoint (guarded by an OS file lock)
#     is the ownership authority. This is only safe when exactly one host can
#     touch a given ``JOB_STATE_ROOT``. A filesystem lock cannot serialise
#     separate hosts.
#
# ``GB_GUARDIAN_OWNERSHIP_MODE`` selects the mode explicitly. ``auto`` (the
# default) is a *safe* inference:
#   * a real shared MongoDB configured (``MONGO_URL``/``MONGODB_URI``) and not an
#     in-process mock  -> ``distributed``
#   * a production deployment (Render) with no explicit mode and no shared Mongo
#     -> REFUSED (``OwnershipConfigError``), never silently downgraded
#   * a local dev/test environment -> ``single_host``
OWNERSHIP_DISTRIBUTED = "distributed"
OWNERSHIP_SINGLE_HOST = "single_host"
OWNERSHIP_MODES = (OWNERSHIP_DISTRIBUTED, OWNERSHIP_SINGLE_HOST)


def _is_production() -> bool:
    """Best-effort detection of a production/Render deployment.

    Conservative on purpose: any Render signal or an explicit
    ``GB_ENVIRONMENT``/``APP_ENV``/``ENVIRONMENT`` of ``production``/``prod``
    counts as production. Callers may always override with an explicit
    ownership mode.
    """
    env = (
        os.environ.get("GB_ENVIRONMENT")
        or os.environ.get("APP_ENV")
        or os.environ.get("ENVIRONMENT")
        or ""
    ).strip().lower()
    if env in {"production", "prod"}:
        return True
    if (os.environ.get("RENDER") or "").strip():
        return True
    if (os.environ.get("RENDER_SERVICE_ID") or "").strip():
        return True
    return False


def _shared_mongo_configured() -> bool:
    return bool((os.environ.get("MONGO_URL") or os.environ.get("MONGODB_URI") or "").strip())


def _looks_like_shared_db(db) -> bool:
    """True unless ``db`` is provably an in-process mock database.

    ``mongomock_motor`` masquerades as a real motor client, so the class name is
    not trustworthy; its underlying ``delegate`` is a ``mongomock`` database. Any
    database that is not a detected mock is treated as a genuine shared backend.
    """
    for obj in (db, getattr(db, "client", None)):
        for attr in ("delegate", "_delegate"):
            delegate = getattr(obj, attr, None)
            if delegate is None:
                continue
            marker = f"{type(delegate).__module__}.{type(delegate).__name__}".lower()
            if "mock" in marker:
                return False
    return True


def resolve_ownership_mode(explicit: Optional[str] = None, db=None) -> str:
    """Resolve the ownership mode deterministically and fail closed.

    Precedence:

    1. an explicit mode (constructor / ``GB_GUARDIAN_OWNERSHIP_MODE``);
    2. ``auto`` -> ``distributed`` when a real shared MongoDB is configured;
    3. ``auto`` in production with no shared Mongo -> :class:`OwnershipConfigError`
       (never a silent host-local downgrade);
    4. ``auto`` elsewhere (dev/test) -> ``single_host``.

    An unknown value is rejected so a typo cannot silently change ownership
    safety.
    """
    requested = (explicit or os.environ.get("GB_GUARDIAN_OWNERSHIP_MODE", "") or "auto").strip().lower()
    if requested in OWNERSHIP_MODES:
        return requested
    if requested not in ("", "auto"):
        raise OwnershipConfigError(
            f"invalid GB_GUARDIAN_OWNERSHIP_MODE={requested!r}; "
            f"expected one of {', '.join(OWNERSHIP_MODES)} or 'auto'"
        )
    if (db is not None and _looks_like_shared_db(db)) or _shared_mongo_configured():
        return OWNERSHIP_DISTRIBUTED
    if _is_production():
        raise OwnershipConfigError(
            "refusing unsafe ownership configuration: production deployment "
            "without a shared MongoDB must set GB_GUARDIAN_OWNERSHIP_MODE "
            "explicitly (distributed requires MONGO_URL/MONGODB_URI). "
            "Host-local ownership is never enabled silently in production."
        )
    return OWNERSHIP_SINGLE_HOST


def ownership_diagnostics() -> dict:
    """Non-secret ownership diagnostics for health/status endpoints and logs."""
    explicit = (os.environ.get("GB_GUARDIAN_OWNERSHIP_MODE", "") or "").strip().lower()
    production = _is_production()
    shared_mongo = _shared_mongo_configured()
    try:
        resolved = resolve_ownership_mode()
        error = None
    except OwnershipConfigError as exc:
        resolved = None
        error = str(exc)
    return {
        "ownership_authority": resolved,
        "ownership_mode_explicit": bool(explicit),
        "ownership_config_error": error,
        "production": production,
        "shared_mongo_configured": shared_mongo,
    }


def is_distributed(mode: str) -> bool:
    return mode == OWNERSHIP_DISTRIBUTED


def _state_dir() -> Path:
    configured = os.environ.get("JOB_STATE_ROOT", "").strip()
    root = Path(configured) if configured else (workspace.workspace_root() / ".state" / "jobs")
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _job_file(job_id: str) -> Path:
    if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
        raise ValueError("invalid job id")
    return _state_dir() / f"{job_id}.json"


def _write_local(job: Job) -> None:
    target = _job_file(job.id)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(job.model_dump(mode="json"), ensure_ascii=False), encoding="utf-8")
    tmp.replace(target)


def _write_local_monotonic(job: Job) -> None:
    """Write the local checkpoint unless it would regress a newer generation.

    A stale process (or a losing claimer's telemetry write) must never clobber a
    checkpoint that a newer generation already owns.
    """
    current = _read_local(job.id)
    if current is not None:
        if (
            current.execution_generation > job.execution_generation
            or (
                current.execution_generation == job.execution_generation
                and current.recovery_attempts > job.recovery_attempts
            )
        ):
            return
    _write_local(job)


def _read_local(job_id: str) -> Optional[Job]:
    if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
        return None
    try:
        path = _job_file(job_id)
        if not path.exists():
            return None
        return Job(**json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _postgres_url() -> str:
    return (os.environ.get("JOB_DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()


def _pack_workspace(job_id: str) -> Optional[bytes]:
    project = workspace.project_dir(job_id)
    if not project.exists():
        return None
    skip = {"node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", "dist", "build", ".next", ".yarn"}
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for path in project.rglob("*"):
            rel = path.relative_to(project)
            if any(part in skip for part in rel.parts):
                continue
            try:
                tf.add(path, arcname=str(rel), recursive=False)
            except OSError:
                continue
    data = buf.getvalue()
    max_bytes = int(os.environ.get("JOB_ARCHIVE_MAX_BYTES", str(25 * 1024 * 1024)))
    return data if len(data) <= max_bytes else None


def _restore_workspace_archive(job_id: str, archive: bytes | memoryview | None) -> bool:
    if not archive:
        return False
    project = workspace.project_dir(job_id)
    # Restore only if the local workspace is absent/empty. Never overwrite a live job.
    try:
        if any(project.iterdir()):
            return False
    except OSError:
        pass
    data = bytes(archive)
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            members = []
            root = project.resolve()
            for member in tf.getmembers():
                if member.islnk() or member.issym():
                    continue
                target = (project / member.name).resolve()
                try:
                    target.relative_to(root)
                except ValueError:
                    continue
                members.append(member)
            tf.extractall(project, members=members)
        return True
    except (tarfile.TarError, OSError):
        return False


def _pg_init_sync(url: str) -> None:
    import psycopg
    with psycopg.connect(url, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {_PG_TABLE} (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    job_json JSONB NOT NULL,
                    workspace_archive BYTEA NULL
                )
            """)
        conn.commit()


def _pg_save_sync(
    url: str,
    job: Job,
    archive: Optional[bytes],
    guard: Optional[tuple[int, int]] = None,
) -> None:
    import psycopg
    _pg_init_sync(url)
    payload = json.dumps(job.model_dump(mode="json"), ensure_ascii=False)
    with psycopg.connect(url, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            if archive is None:
                if guard is not None:
                    gen, attempts = guard
                    cur.execute(
                        f"""INSERT INTO {_PG_TABLE} (id, created_at, updated_at, job_json)
                            VALUES (%s, %s, %s, %s::jsonb)
                            ON CONFLICT (id) DO UPDATE SET
                              updated_at=EXCLUDED.updated_at,
                              job_json=EXCLUDED.job_json
                            WHERE COALESCE(({_PG_TABLE}.job_json->>'execution_generation')::int, 0) <= %s
                              AND COALESCE(({_PG_TABLE}.job_json->>'recovery_attempts')::int, 0) <= %s""",
                        (job.id, job.created_at, job.updated_at, payload, gen, attempts),
                    )
                else:
                    cur.execute(
                        f"""INSERT INTO {_PG_TABLE} (id, created_at, updated_at, job_json)
                            VALUES (%s, %s, %s, %s::jsonb)
                            ON CONFLICT (id) DO UPDATE SET
                              updated_at=EXCLUDED.updated_at,
                              job_json=EXCLUDED.job_json""",
                        (job.id, job.created_at, job.updated_at, payload),
                    )
            else:
                cur.execute(
                    f"""INSERT INTO {_PG_TABLE} (id, created_at, updated_at, job_json, workspace_archive)
                        VALUES (%s, %s, %s, %s::jsonb, %s)
                        ON CONFLICT (id) DO UPDATE SET
                          updated_at=EXCLUDED.updated_at,
                          job_json=EXCLUDED.job_json,
                          workspace_archive=EXCLUDED.workspace_archive""",
                    (job.id, job.created_at, job.updated_at, payload, archive),
                )
        conn.commit()


def _pg_load_sync(url: str, job_id: str) -> tuple[Optional[Job], Optional[bytes]]:
    import psycopg
    _pg_init_sync(url)
    with psycopg.connect(url, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT job_json, workspace_archive FROM {_PG_TABLE} WHERE id=%s", (job_id,))
            row = cur.fetchone()
    if not row:
        return None, None
    raw = row[0]
    payload = raw if isinstance(raw, dict) else json.loads(raw)
    return Job(**payload), (bytes(row[1]) if row[1] is not None else None)


def _pg_list_sync(url: str, limit: int) -> list[Job]:
    import psycopg
    _pg_init_sync(url)
    with psycopg.connect(url, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT job_json FROM {_PG_TABLE} ORDER BY updated_at DESC LIMIT %s", (limit,))
            rows = cur.fetchall()
    out = []
    for (raw,) in rows:
        payload = raw if isinstance(raw, dict) else json.loads(raw)
        out.append(Job(**payload))
    return out


def _pg_delete_sync(url: str, job_id: str) -> None:
    import psycopg
    _pg_init_sync(url)
    with psycopg.connect(url, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {_PG_TABLE} WHERE id=%s", (job_id,))
        conn.commit()


async def _save_postgres(job: Job) -> None:
    url = _postgres_url()
    if not url:
        return
    now = time.monotonic()
    terminal = str(job.status.value if hasattr(job.status, "value") else job.status) in {"completed", "failed", "cancelled"}
    archive = None
    if terminal or now - _last_archive_at.get(job.id, 0.0) >= _ARCHIVE_INTERVAL_S:
        archive = await asyncio.to_thread(_pack_workspace, job.id)
        _last_archive_at[job.id] = now
    try:
        await asyncio.to_thread(
            _pg_save_sync, url, job, archive,
            (job.execution_generation, job.recovery_attempts),
        )
    except Exception:
        pass




def _pg_ping_sync(url: str) -> bool:
    import psycopg
    with psycopg.connect(url, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            return cur.fetchone() == (1,)


async def persistence_status() -> dict:
    """Return non-secret runtime persistence diagnostics for health checks."""
    url = _postgres_url()
    reachable = False
    if url:
        try:
            reachable = await asyncio.to_thread(_pg_ping_sync, url)
        except Exception:
            reachable = False
    status = {
        "postgres_configured": bool(url),
        "postgres_reachable": reachable,
        "workspace_archive_enabled": bool(url),
        "local_state_root": str(_state_dir()),
        "durable_across_host_replacement": bool(url and reachable),
        "postgres_role": "mirror_archive_only",
    }
    status.update(ownership_diagnostics())
    return status

async def save_job(db: AsyncIOMotorDatabase, job: Job) -> None:
    doc = job.model_dump(mode="json")
    doc["_id"] = job.id
    try:
        # Best-effort mirror, but never let a stale process regress a newer
        # generation/attempt count that another worker already owns.
        await db[COLLECTION].replace_one(
            {
                "_id": job.id,
                "execution_generation": {"$lte": job.execution_generation},
                "recovery_attempts": {"$lte": job.recovery_attempts},
            },
            doc, upsert=True,
        )
    except Exception:
        # Database loss must not abort a job with a durable local checkpoint.
        pass
    finally:
        # Always persist a process-restart-safe local copy as a second checkpoint.
        _write_local_monotonic(job)
        await _save_postgres(job)


async def save_job_critical(db: AsyncIOMotorDatabase, job: Job, *, mode: Optional[str] = None) -> None:
    """Persist an ownership/state transition, failing closed on write error.

    Unlike :func:`save_job`, a failure here is never swallowed. The caller must
    treat a raised :class:`PersistenceError` as "the transition did not happen"
    and must not continue execution as if it owned the new state.

    The durable source of truth depends on the ownership ``mode``:

    * ``distributed`` — **MongoDB is the single ownership arbiter**. The
      transition is durable only if the Mongo compare-and-set actually applied
      (or the Mongo document is already at an equal-or-newer generation, which
      the guarded write reflects). Postgres is a mirror/archive and its success
      NEVER authorizes continued execution. If Mongo is unreachable the
      transition fails closed, even when Postgres is healthy.
    * ``single_host`` — the host-local checkpoint is authoritative; shared
      backends remain best-effort mirrors. If the local write fails the
      transition fails.
    """
    resolved = resolve_ownership_mode(mode, db)
    doc = job.model_dump(mode="json")
    doc["_id"] = job.id

    if is_distributed(resolved):
        # Mongo is the sole arbiter. The guarded replace both records the
        # transition and refuses to regress a newer generation. Nothing else is
        # written until Mongo accepts, so no phantom generation can linger.
        try:
            await db[COLLECTION].replace_one(
                {
                    "_id": job.id,
                    "execution_generation": {"$lte": job.execution_generation},
                    "recovery_attempts": {"$lte": job.recovery_attempts},
                },
                doc, upsert=True,
            )
        except Exception as exc:
            # Mongo unavailable: fail closed. Postgres health must not mask it.
            raise PersistenceError(
                "critical transition not durable: ownership arbiter (MongoDB) unavailable"
            ) from exc
        # Host-local file is only a restart cache in distributed mode.
        try:
            _write_local_monotonic(job)
        except OSError:
            logger.warning("local cache write failed for job %s (non-authoritative)", job.id)
        # Postgres remains a mirror/archive only; its outcome is not authoritative.
        await _save_postgres_best_effort(job)
        return

    # single_host: the host-local checkpoint is authoritative. Shared backends
    # are best-effort mirrors.
    try:
        _write_local_monotonic(job)
    except OSError as exc:
        raise PersistenceError(f"local checkpoint write failed: {exc}") from exc
    try:
        await db[COLLECTION].replace_one(
            {
                "_id": job.id,
                "execution_generation": {"$lte": job.execution_generation},
                "recovery_attempts": {"$lte": job.recovery_attempts},
            },
            doc, upsert=True,
        )
    except Exception:
        pass
    await _save_postgres_best_effort(job)


async def _save_postgres_best_effort(job: Job) -> None:
    """Postgres mirror/archive for a critical write; never authoritative.

    Failures are swallowed: Postgres is a mirror, recovery archive and
    workspace backup, not an ownership authority.
    """
    url = _postgres_url()
    if not url:
        return
    try:
        archive = await asyncio.to_thread(_pack_workspace, job.id)
        await asyncio.to_thread(
            _pg_save_sync, url, job, archive,
            (job.execution_generation, job.recovery_attempts),
        )
    except Exception:
        logger.warning(
            "postgres mirror write failed for job %s (non-authoritative, ignored)",
            job.id,
        )


def _job_generation_filter(job_id: str, expected_generation: int, expected_attempts: int) -> dict:
    from ..models import JobStatus

    terminal = [
        JobStatus.COMPLETED.value, JobStatus.FAILED.value,
        JobStatus.CANCELLED.value, JobStatus.PAUSED.value,
    ]
    return {
        "_id": job_id,
        "execution_generation": {"$lte": expected_generation},
        "recovery_attempts": {"$lte": expected_attempts},
        "status": {"$nin": terminal},
    }



async def _conditional_mongo_replace(db, job: Job, filter_doc: dict) -> str:
    """Atomic compare-and-set replace in Mongo.

    Returns one of ``"applied"`` (matched and replaced), ``"conflict"`` (a live
    document exists but did not match — another writer advanced past us), or
    ``"error"`` (the shared backend is unreachable). ``upsert=False``: claiming
    must never fabricate a document, and an upsert against a non-matching filter
    would raise a duplicate-key error.
    """
    doc = job.model_dump(mode="json")
    doc["_id"] = job.id
    try:
        result = await db[COLLECTION].replace_one(filter_doc, doc, upsert=False)
    except Exception:
        return "error"
    if bool(getattr(result, "matched_count", 0)):
        return "applied"
    return "conflict"


async def save_job_conditional(
    db: AsyncIOMotorDatabase,
    job: Job,
    *,
    expected_generation: int,
    expected_attempts: int,
    mode: Optional[str] = None,
) -> ConditionalWriteResult:
    """Compare-and-set persist used to claim recovery ownership.

    The persisted document is replaced only when its ``execution_generation``
    and ``recovery_attempts`` are no greater than the values this caller
    observed. A concurrent claimer that already advanced the generation (or
    attempts) wins; this caller gets ``applied=False`` and must not proceed.

    Ownership authority depends on ``mode`` (see :func:`resolve_ownership_mode`):

    * ``distributed`` — only the shared Mongo compare-and-set can grant
      ownership. The host-local file is never used to claim. If Mongo is
      unreachable or the shared document is unexpectedly absent, the result is
      ``applied=False`` and the caller fails closed.
    * ``single_host`` — Mongo is tried first (when a document exists it remains
      the arbiter); otherwise the guarded host-local file lock grants ownership.
    """
    resolved = resolve_ownership_mode(mode, db)
    filter_doc = _job_generation_filter(job.id, expected_generation, expected_attempts)

    outcome = await _conditional_mongo_replace(db, job, filter_doc)
    if outcome == "applied":
        _write_local_monotonic(job)
        await _save_postgres(job)
        return ConditionalWriteResult(applied=True, doc_found=True)

    # Either another writer advanced the persisted state, no Mongo document
    # exists, or Mongo is unavailable. Distinguish the three.
    mongo_error = False
    live = None
    try:
        live = await db[COLLECTION].find_one(
            {"_id": job.id}, {"execution_generation": 1, "recovery_attempts": 1}
        )
    except Exception:
        mongo_error = True

    if mongo_error:
        if is_distributed(resolved):
            # Distributed mode: the shared arbiter is unreachable and no local
            # file may confer ownership. Fail closed.
            return ConditionalWriteResult(applied=False, doc_found=False)
        # single_host: fall through to the local durable checkpoint arbiter.
    elif live is not None:
        # A shared document exists: it is the arbiter and it did not match, so
        # another writer owns the newer state (or the job is terminal).
        return ConditionalWriteResult(applied=False, doc_found=True)

    if is_distributed(resolved):
        # Distributed mode with the shared backend reachable but no job document:
        # the durable record is unexpectedly missing. Never fabricate ownership
        # locally; surface it so the caller fails closed and can recover safely.
        return ConditionalWriteResult(applied=False, doc_found=False)

    # No Mongo document (single_host, or distributed with unreachable Mongo):
    # fall back to the host-local durable checkpoint as arbiter.
    return await asyncio.to_thread(_conditional_local_claim, job, expected_generation, expected_attempts)


def _conditional_local_claim(job: Job, expected_generation: int, expected_attempts: int) -> ConditionalWriteResult:
    lock = _state_dir() / f".{job.id}.claim.lock"
    fd = None
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_RDWR, 0o600)
        _flock(fd)
        current = _read_local(job.id)
        if current is not None:
            if (
                current.execution_generation > expected_generation
                or current.recovery_attempts > expected_attempts
            ):
                return ConditionalWriteResult(applied=False, doc_found=True)
        _write_local(job)
        return ConditionalWriteResult(applied=True, doc_found=current is not None)
    except OSError:
        return ConditionalWriteResult(applied=False, doc_found=True)
    finally:
        if fd is not None:
            try:
                _funlock(fd)
            finally:
                os.close(fd)
        try:
            lock.unlink(missing_ok=True)
        except OSError:
            pass


if os.name == "nt":  # pragma: no cover - production target is Linux
    import msvcrt

    def _flock(fd: int) -> None:
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)

    def _funlock(fd: int) -> None:
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _flock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _funlock(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass


async def load_job(db: AsyncIOMotorDatabase, job_id: str) -> Optional[Job]:
    try:
        doc = await db[COLLECTION].find_one({"_id": job_id})
    except Exception:
        doc = None
    if doc:
        doc.pop("_id", None)
        return Job(**doc)
    url = _postgres_url()
    if url:
        try:
            restored, archive = await asyncio.to_thread(_pg_load_sync, url, job_id)
            if restored:
                await asyncio.to_thread(_restore_workspace_archive, job_id, archive)
                return restored
        except Exception:
            pass
    return _read_local(job_id)


async def list_jobs(db: AsyncIOMotorDatabase, limit: int = 50) -> list[Job]:
    by_id: dict[str, Job] = {}
    try:
        cursor = db[COLLECTION].find({}, {"_id": 0}).sort("created_at", -1).limit(limit)
        async for doc in cursor:
            job = Job(**doc)
            by_id[job.id] = job
    except Exception:
        pass

    url = _postgres_url()
    if url:
        try:
            for job in await asyncio.to_thread(_pg_list_sync, url, limit):
                by_id.setdefault(job.id, job)
        except Exception:
            pass

    try:
        for path in _state_dir().glob("*.json"):
            try:
                job = Job(**json.loads(path.read_text(encoding="utf-8")))
                by_id.setdefault(job.id, job)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
    except OSError:
        pass

    return sorted(by_id.values(), key=lambda j: j.created_at, reverse=True)[:limit]


async def delete_job(db: AsyncIOMotorDatabase, job_id: str) -> None:
    if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
        return
    try:
        await db[COLLECTION].delete_one({"_id": job_id})
    finally:
        url = _postgres_url()
        if url:
            try:
                await asyncio.to_thread(_pg_delete_sync, url, job_id)
            except Exception:
                pass
        try:
            _job_file(job_id).unlink(missing_ok=True)
        except OSError:
            pass
        _last_archive_at.pop(job_id, None)
