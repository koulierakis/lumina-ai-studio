import types

import pytest

from document_studio.import_hardening import (
    DOCX_MIME,
    html_to_plain_text,
    prepare_import_content,
    resolve_document_mime,
    strip_pdf_page_markers,
)


def test_docx_octet_stream_is_normalized_by_extension():
    assert resolve_document_mime("application/octet-stream", "agreement.docx") == DOCX_MIME
    assert resolve_document_mime("application/zip", "agreement.docx") == DOCX_MIME


def test_non_docx_octet_stream_is_not_promoted():
    assert resolve_document_mime("application/octet-stream", "payload.bin") == "application/octet-stream"


def test_html_plain_text_preserves_block_boundaries():
    text = html_to_plain_text("<h1>Title</h1><p>First</p><p>Second &amp; third</p>")
    assert text == "Title\nFirst\nSecond & third"


def test_pdf_page_markers_are_removed_from_visible_text():
    value = "[[LUMINA_PAGE:1]]\nAlpha\n[[LUMINA_PAGE:2]]\nBeta"
    assert strip_pdf_page_markers(value) == "Alpha\n\nBeta"


def test_docx_structure_is_preserved(monkeypatch):
    fake_service = types.SimpleNamespace(
        _parse_docx_to_html=lambda _: "<article><h1>Τίτλος</h1><p>Ελληνικό κείμενο</p></article>",
        extract_text_from_upload=lambda *_: pytest.fail("DOCX fallback must not run"),
    )
    monkeypatch.setattr("document_studio.import_hardening.importlib.import_module", lambda _: fake_service)
    content_html, content_text, fact_source, method, ocr = prepare_import_content(
        b"docx", DOCX_MIME, "δοκιμή.docx", "Δοκιμή"
    )
    assert "<h1>Τίτλος</h1>" in content_html
    assert "Ελληνικό κείμενο" in content_text
    assert fact_source == content_text
    assert method == "docx_structure"
    assert ocr is False


def test_damaged_docx_is_rejected(monkeypatch):
    fake_service = types.SimpleNamespace(
        _parse_docx_to_html=lambda _: None,
        extract_text_from_upload=lambda *_: "",
    )
    monkeypatch.setattr("document_studio.import_hardening.importlib.import_module", lambda _: fake_service)
    with pytest.raises(ValueError, match="damaged"):
        prepare_import_content(b"bad", DOCX_MIME, "broken.docx", "Broken")
