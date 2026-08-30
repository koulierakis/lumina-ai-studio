"""Document Intelligence and Corporate Studio backend module."""

from importlib import import_module

from .pdf_fonts import ensure_pdf_font_aliases
from .safe_smart_fields import extract_fact_safe_smart_fields

# The router imports the export service, which expects these aliases to exist.
# Bootstrap them first so PDF export is safe on Windows, Linux and macOS.
ensure_pdf_font_aliases()

from .provider_status import router as provider_status_router  # noqa: E402
from .router import configure_document_studio_router, router  # noqa: E402

# Replace the legacy field extractor after the existing modules load. Service
# render functions resolve their module global at call time, so deterministic
# generation now uses placeholders instead of invented "on file" facts.
_service_module = import_module(".service", __name__)
_router_module = import_module(".router", __name__)
_service_module.extract_smart_fields = extract_fact_safe_smart_fields
_router_module.extract_smart_fields = extract_fact_safe_smart_fields

router.include_router(provider_status_router)

__all__ = ["configure_document_studio_router", "router"]
