from __future__ import annotations

import pytest

from document_studio import router as document_router
from document_studio.import_hardening import (
    DOCX_MIME,
    html_to_plain_text,
    prepare_import_content,
    resolve_document_mime,
)
from document_studio.models import CompanyProfile, CorporateDocument
from document_studio.service import render_docx_bytes


def _document() -> CorporateDocument:
    return CorporateDocument(
        owner_email="owner@example.com",
        title="Εταιρική Δήλωση",
        document_type="declaration",
        language="el",
        content_html=(
            "<article><h1>Εταιρική Δήλωση</h1>"
            "<p>Επωνυμία: ΕΜΠΟΡΙΚΗ ΕΛΛΑΔΟΣ ΙΚΕ</p>"
            "<p>Καλημέρα – αξία €1.250,50 — Ελληνικά &amp; English</p>"
            "<p>Αριθμός ΓΕΜΗ: 123456789000</p>"
            "<table><tr><th>Πεδίο</th><th>Τιμή</th></tr>"
            "<tr><td>Έδρα</td><td>Ασκληπιού 10, Τρίκαλα</td></tr></table></article>"
        ),
        content_text=(
            "Εταιρική Δήλωση\nΕπωνυμία: ΕΜΠΟΡΙΚΗ ΕΛΛΑΔΟΣ ΙΚΕ\n"
            "Καλημέρα – αξία €1.250,50 — Ελληνικά & English\n"
            "Αριθμός ΓΕΜΗ: 123456789000\nΈδρα: Ασκληπιού 10, Τρίκαλα"
        ),
    )


def _profile() -> CompanyProfile:
    return CompanyProfile(
        owner_email="owner@example.com",
        company_name="ΕΜΠΟΡΙΚΗ ΕΛΛΑΔΟΣ ΙΚΕ",
        jurisdiction="Ελλάδα",
    )


def test_docx_import_keeps_structured_html_and_clean_unicode_text():
    docx = render_docx_bytes(_document(), _profile())

    content_html, content_text, fact_source, method, ocr = prepare_import_content(
        docx, DOCX_MIME, "εταιρική-δήλωση.docx", "Εταιρική Δήλωση"
    )

    assert content_html.startswith("<article>")
    assert "<p>" in content_html or "<h1>" in content_html
    assert "&lt;article" not in content_html
    assert "ΕΜΠΟΡΙΚΗ ΕΛΛΑΔΟΣ ΙΚΕ" in content_html
    assert "ΕΜΠΟΡΙΚΗ ΕΛΛΑΔΟΣ ΙΚΕ" in content_text
    assert "Καλημέρα – αξία €1.250,50 — Ελληνικά & English" in content_text
    assert "<article" not in content_text
    assert fact_source == content_text
    assert method == "docx_structure"
    assert ocr is False


def test_html_to_plain_text_preserves_table_boundaries_and_greek():
    text = html_to_plain_text(
        "<article><h1>Στοιχεία</h1><table><tr><th>Πεδίο</th><th>Τιμή</th></tr>"
        "<tr><td>Έδρα</td><td>Τρίκαλα</td></tr></table></article>"
    )

    assert "Στοιχεία" in text
    assert "Πεδίο" in text
    assert "Τρίκαλα" in text
    assert "<table" not in text


def test_docx_extension_normalizes_generic_browser_mime():
    assert resolve_document_mime("application/octet-stream", "Σύμβαση.docx") == DOCX_MIME
    assert resolve_document_mime("application/zip", "Σύμβαση.docx") == DOCX_MIME
    assert resolve_document_mime("", "Σύμβαση.docx") == DOCX_MIME


def test_malformed_docx_is_rejected_instead_of_decoded_as_garbled_text():
    with pytest.raises(ValueError, match="damaged|parsed safely"):
        prepare_import_content(
            b"PK\x03\x04not-a-valid-word-package\xff\xfe\x80",
            DOCX_MIME,
            "broken.docx",
            "Broken",
        )


def test_active_router_exposes_exactly_one_hardened_import_endpoint():
    import_routes = [
        route
        for route in document_router.routes
        if getattr(route, "path", None) == "/api/documents/import"
        and "POST" in (getattr(route, "methods", set()) or set())
    ]

    assert len(import_routes) == 1
    assert import_routes[0].endpoint.__name__ == "import_document_hardened"
