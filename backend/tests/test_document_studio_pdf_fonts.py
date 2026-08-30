from __future__ import annotations

from reportlab.pdfbase import pdfmetrics

from document_studio.pdf_fonts import (
    PDF_FONT_BOLD_NAME,
    PDF_FONT_NAME,
    ensure_pdf_font_aliases,
)


def test_pdf_font_aliases_are_registered_before_export_service_uses_them():
    status = ensure_pdf_font_aliases()

    registered = set(pdfmetrics.getRegisteredFontNames())
    assert PDF_FONT_NAME in registered
    assert PDF_FONT_BOLD_NAME in registered
    assert status["regular_registered"] is True
    assert status["bold_registered"] is True


def test_pdf_font_bootstrap_reports_whether_unicode_ttf_was_found():
    status = ensure_pdf_font_aliases()

    assert isinstance(status["unicode_font_available"], bool)
    if status["unicode_font_available"]:
        assert status["regular_path"]
