"""Document Intelligence and Corporate Studio backend module."""

from .pdf_fonts import ensure_pdf_font_aliases

# The router imports the export service, which expects these aliases to exist.
# Bootstrap them first so PDF export is safe on Windows, Linux and macOS.
ensure_pdf_font_aliases()

from .router import configure_document_studio_router, router  # noqa: E402

__all__ = ["configure_document_studio_router", "router"]
