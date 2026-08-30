"""Document Intelligence and Corporate Studio backend module."""

from importlib import import_module

from .pdf_extraction import extract_pdf_text
from .pdf_fonts import ensure_pdf_font_aliases
from .safe_smart_fields import extract_fact_safe_smart_fields

# The router imports the export service, which expects these aliases to exist.
# Bootstrap them first so PDF export is safe on Windows, Linux and macOS.
ensure_pdf_font_aliases()

from .import_hardening import router as import_hardening_router  # noqa: E402
from .provider_status import router as provider_status_router  # noqa: E402
from .router import configure_document_studio_router, router  # noqa: E402

_service_module = import_module(".service", __name__)
_router_module = import_module(".router", __name__)

# Deterministic generation must never convert missing profile values into invented facts.
_service_module.extract_smart_fields = extract_fact_safe_smart_fields
_router_module.extract_smart_fields = extract_fact_safe_smart_fields

# Keep the existing DOCX/text/image import implementation, but replace the legacy
# raw latin-1 PDF parser with a Unicode-aware PDF text layer extractor.
_legacy_extract_text_from_upload = _service_module.extract_text_from_upload


def _extract_text_from_upload(data: bytes, mime: str, filename: str = "document") -> str:
    if mime == "application/pdf":
        return extract_pdf_text(data)
    return _legacy_extract_text_from_upload(data, mime, filename)


_service_module.extract_text_from_upload = _extract_text_from_upload
_router_module.extract_text_from_upload = _extract_text_from_upload

# Replace only the legacy POST /api/documents/import route. Keeping one route for
# the path avoids ambiguous matching/OpenAPI while leaving the rest of the router untouched.
router.routes[:] = [
    route
    for route in router.routes
    if not (
        getattr(route, "path", None) == "/api/documents/import"
        and "POST" in (getattr(route, "methods", set()) or set())
    )
]
router.routes.extend(import_hardening_router.routes)
router.include_router(provider_status_router)

__all__ = ["configure_document_studio_router", "router"]
