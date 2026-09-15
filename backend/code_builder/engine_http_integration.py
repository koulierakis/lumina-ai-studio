"""Install the read-only Code Builder engine status route idempotently."""
from __future__ import annotations

_INSTALLED = False


def install_engine_http_routes() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # Import lazily so the canonical Code Builder router is fully constructed
    # before the small engine-status router is attached to it.
    from .engine_http_routes import router as engine_router
    from .router import router as code_builder_router

    # Keep idempotency under our control. FastAPI 0.141 represents a nested
    # router as an opaque declaration until the parent router is mounted, so
    # inspecting its private route objects here is no longer stable.
    code_builder_router.include_router(engine_router)
    _INSTALLED = True
