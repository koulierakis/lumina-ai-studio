from __future__ import annotations

import io
import zipfile

from document_studio.models import CompanyProfile, CorporateDocument
from document_studio.service import render_docx_bytes, render_pdf_bytes


def _greek_document() -> CorporateDocument:
    text = (
        "Επωνυμία: ΕΜΠΟΡΙΚΗ ΕΛΛΑΔΟΣ ΙΚΕ\n"
        "Αριθμός ΓΕΜΗ: 123456789000\n"
        "Έδρα: Ασκληπιού 10, Τρίκαλα\n"
        "Διαχειριστής: ΙΩΑΝΝΗΣ ΚΟΥΛΙΕΡΑΚΗΣ"
    )
    return CorporateDocument(
        owner_email="owner@example.com",
        title="Εταιρική Δήλωση",
        document_type="declaration",
        language="el",
        content_text=text,
        searchable_text=text,
        content_html=(
            "<article><h1>Εταιρική Δήλωση</h1>"
            "<p>Επωνυμία: ΕΜΠΟΡΙΚΗ ΕΛΛΑΔΟΣ ΙΚΕ</p>"
            "<p>Αριθμός ΓΕΜΗ: 123456789000</p>"
            "<p>Έδρα: Ασκληπιού 10, Τρίκαλα</p>"
            "<p>Διαχειριστής: ΙΩΑΝΝΗΣ ΚΟΥΛΙΕΡΑΚΗΣ</p></article>"
        ),
    )


def _profile() -> CompanyProfile:
    return CompanyProfile(
        owner_email="owner@example.com",
        company_name="ΕΜΠΟΡΙΚΗ ΕΛΛΑΔΟΣ ΙΚΕ",
        jurisdiction="Ελλάδα",
        registration_number="123456789000",
        registered_office="Ασκληπιού 10, Τρίκαλα",
    )


def test_greek_document_round_trip_model_preserves_unicode():
    original = _greek_document()
    reopened = CorporateDocument.model_validate(original.model_dump(mode="json"))

    assert reopened.title == "Εταιρική Δήλωση"
    assert "ΕΜΠΟΡΙΚΗ ΕΛΛΑΔΟΣ ΙΚΕ" in reopened.content_text
    assert "Τρίκαλα" in reopened.content_html
    assert "ΙΩΑΝΝΗΣ ΚΟΥΛΙΕΡΑΚΗΣ" in reopened.searchable_text


def test_greek_pdf_export_produces_valid_pdf_without_unicode_font_failure():
    exported = render_pdf_bytes(_greek_document(), _profile())

    assert exported.startswith(b"%PDF-")
    assert len(exported) > 1000
    assert b"%%EOF" in exported[-1024:]


def test_greek_docx_export_preserves_unicode_in_word_xml():
    exported = render_docx_bytes(_greek_document(), _profile())

    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
        names = set(archive.namelist())
        document_xml = archive.read("word/document.xml").decode("utf-8")

    assert "[Content_Types].xml" in names
    assert "word/document.xml" in names
    assert "Εταιρική Δήλωση" in document_xml
    assert "ΕΜΠΟΡΙΚΗ ΕΛΛΑΔΟΣ ΙΚΕ" in document_xml
    assert "Αριθμός ΓΕΜΗ" in document_xml
    assert "Τρίκαλα" in document_xml
