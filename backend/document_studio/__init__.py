"""Document Intelligence and Corporate Studio backend module."""

from .pdf_fonts import ensure_pdf_font_aliases

# The router imports the export service, which expects these aliases to exist.
# Bootstrap them first so PDF export is safe on Windows, Linux and macOS.
ensure_pdf_font_aliases()

from .provider_status import router as provider_status_router  # noqa: E402
from .router import configure_document_studio_router, router  # noqa: E402

router.include_router(provider_status_router)

__all__ = ["configure_document_studio_router", "router"]
