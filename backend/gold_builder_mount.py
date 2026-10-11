"""Mount the vendored Gold Builder Engine (/api/gb/*) into Lumina behind owner auth."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response

from auth import _allowed_emails, decode_token, issue_token, require_owner

logger = logging.getLogger("lumina.gold_builder")

PREVIEW_COOKIE = "lumina_gb_preview"
PREVIEW_COOKIE_PATH = "/api/gb/jobs"


async def require_gold_builder_access(request: Request) -> str:
    # Iframe previews and <img> screenshots cannot send headers; accept the scoped HttpOnly cookie.
    if not request.headers.get("authorization"):
        token = request.cookies.get(PREVIEW_COOKIE)
        if token:
            subject = decode_token(token)
            if subject and subject in _allowed_emails():
                return subject
            raise HTTPException(status_code=401, detail="Invalid or expired preview session")
    return await require_owner(request)


def _gold_db():
    mongo_url = (os.environ.get("GOLD_BUILDER_MONGO_URL") or os.environ.get("MONGO_URL") or "").strip()
    db_name = os.environ.get("GOLD_BUILDER_DB_NAME") or os.environ.get("DB_NAME") or "lumina_gold_builder"
    if mongo_url and not mongo_url.startswith("mongomock://"):
        from motor.motor_asyncio import AsyncIOMotorClient

        return AsyncIOMotorClient(mongo_url)[db_name], "mongo"
    from mongomock_motor import AsyncMongoMockClient

    return AsyncMongoMockClient()[db_name], "in-memory+checkpoint"


def mount_gold_builder(app: FastAPI, runtime_root: Path) -> None:
    gold_root = runtime_root / "gold-builder"
    os.environ.setdefault("WORKSPACE_ROOT", str(gold_root / "workspaces"))
    os.environ.setdefault("JOB_STATE_ROOT", str(gold_root / "job-state"))
    Path(os.environ["WORKSPACE_ROOT"]).mkdir(parents=True, exist_ok=True)

    from gold_builder.api.routes import get_guardian, make_router

    db, store = _gold_db()
    guard = [Depends(require_gold_builder_access)]
    app.include_router(make_router(db), prefix="/api", dependencies=guard)

    @app.post("/api/gb-session", include_in_schema=False)
    async def gold_builder_session(request: Request, response: Response, owner: str = Depends(require_owner)) -> dict:
        response.set_cookie(
            PREVIEW_COOKIE,
            issue_token(owner, hours=12),
            max_age=12 * 3600,
            httponly=True,
            secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https",
            samesite="strict",
            path=PREVIEW_COOKIE_PATH,
        )
        return {"ok": True, "engine": "gold-builder", "store": store}

    @app.on_event("startup")
    async def _gold_builder_startup() -> None:
        guardian = get_guardian()
        if guardian is None:
            return
        try:
            recovered = await guardian.startup_scan()
            if recovered:
                logger.info("Gold Builder guardian recovered %d job(s)", len(recovered))
            await guardian.start()
        except Exception:
            logger.exception("Gold Builder guardian failed to start")

    @app.on_event("shutdown")
    async def _gold_builder_shutdown() -> None:
        guardian = get_guardian()
        if guardian is not None:
            try:
                await guardian.stop()
            except Exception:
                logger.exception("Gold Builder guardian stop failed")

    @app.get("/api/health/gold-builder-mongo", include_in_schema=False)
    async def gold_builder_mongo_health(response: Response) -> dict:
        """Report a real MongoDB ping without exposing the connection string."""
        if store != "mongo":
            response.status_code = 503
            return {"status": "not_configured", "store": store, "mongo_ping": "SKIPPED"}
        try:
            await asyncio.wait_for(db.command("ping"), timeout=5.0)
        except Exception as exc:
            logger.warning("Gold Builder MongoDB health ping failed: %s", type(exc).__name__)
            response.status_code = 503
            return {
                "status": "degraded",
                "store": store,
                "mongo_ping": "FAIL",
                "error": type(exc).__name__,
            }
        return {"status": "ok", "store": store, "mongo_ping": "OK"}

    logger.info("Gold Builder Engine mounted at /api/gb (store=%s)", store)
