"""Document Intelligence and Corporate Studio backend module."""

from importlib import import_module

from .pdf_extraction import extract_pdf_text
from .pdf_fonts import ensure_pdf_font_aliases
from .provider_status import router as provider_status_router
from .safe_smart_fields import extract_fact_safe_smart_fields

# Bootstrap PDF font aliases before the export service is imported.
ensure_pdf_font_aliases()

from .import_route import router as hardened_import_router  # noqa: E402
from .router import configure_document_studio_router, router  # noqa: E402

_service_module = import_module(".service", __name__)
_router_module = import_module(".router", __name__)

# Deterministic generation must not invent missing company/profile facts.
_service_module.extract_smart_fields = extract_fact_safe_smart_fields
_router_module.extract_smart_fields = extract_fact_safe_smart_fields

# Use Unicode-aware PDF text extraction while keeping existing DOCX/text/image logic.
_legacy_extract_text_from_upload = _service_module.extract_text_from_upload


def _extract_text_from_upload(data: bytes, mime: str, filename: str = "document") -> str:
    if mime == "application/pdf":
        return extract_pdf_text(data)
    return _legacy_extract_text_from_upload(data, mime, filename)


_service_module.extract_text_from_upload = _extract_text_from_upload
_router_module.extract_text_from_upload = _extract_text_from_upload

# Replace only the legacy POST /api/documents/import route. All other Document
# Studio routes keep their existing implementation and persistence lifecycle.
router.routes[:] = [
    route
    for route in router.routes
    if not (
        getattr(route, "path", None) == "/api/documents/import"
        and "POST" in (getattr(route, "methods", set()) or set())
    )
]
router.routes.extend(hardened_import_router.routes)

# Provider readiness is exposed through the same Document Studio API router.
router.include_router(provider_status_router)

__all__ = ["configure_document_studio_router", "router"]
