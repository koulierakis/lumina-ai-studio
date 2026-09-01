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

    expected_path = "/api/code-builder/engines"
    if not any(getattr(route, "path", None) == expected_path for route in code_builder_router.routes):
        code_builder_router.include_router(engine_router)

    if not any(getattr(route, "path", None) == expected_path for route in code_builder_router.routes):
        raise RuntimeError("Code Builder engine status route was not installed.")

    _INSTALLED = True
