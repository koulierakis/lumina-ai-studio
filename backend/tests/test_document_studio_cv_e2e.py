from __future__ import annotations

import asyncio
import importlib
import zipfile
from copy import deepcopy
from io import BytesIO

from document_studio.document_ai_provider import DocumentAIProvider
from document_studio.models import CompanyProfile, CorporateDocument, NaturalDocumentCreationRequest
from document_studio.natural_creation import create_natural_document
from document_studio.service import render_docx_bytes, render_pdf_bytes
from persistence import SQLitePersistenceProvider


document_router = importlib.import_module("document_studio.router")


def run(coro):
    return asyncio.run(coro)


class GreekCvStubProvider(DocumentAIProvider):
    name = "greek-cv-e2e-stub"

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def generate_document(self, request: str, context: dict):
        self.calls.append((request, deepcopy(context)))
        return {
            "title": "Επαγγελματικό Βιογραφικό — Μαρία Παπαδοπούλου",
            "document_type": "professional_cv",
            "category": "Career",
            "language": "el",
            "content": (
                "ΜΑΡΙΑ ΠΑΠΑΔΟΠΟΥΛΟΥ\n"
                "Επαγγελματικό Προφίλ\n"
                "Στέλεχος διοίκησης με εμπειρία στην οργάνωση έργων.\n\n"
                "ΕΠΑΓΓΕΛΜΑΤΙΚΗ ΕΜΠΕΙΡΙΑ\n"
                "Project Coordinator — Example AE — 2022–2026\n"
                "• Συντόνισε έργα και ομάδες με σαφή χρονοδιαγράμματα.\n\n"
                "ΕΚΠΑΙΔΕΥΣΗ\n"
                "Πτυχίο Διοίκησης Επιχειρήσεων — 2021\n\n"
                "ΔΕΞΙΟΤΗΤΕΣ\n"
                "Οργάνωση έργων, επικοινωνία, Microsoft Office\n\n"
                "ΓΛΩΣΣΕΣ\n"
                "Ελληνικά, Αγγλικά"
            ),
            "claims": [],
            "unresolved_fields": ["EMAIL", "PHONE"],
        }

    async def status(self):
        return {"name": self.name, "available": True}


def test_greek_cv_full_chain_preview_save_reload_pdf_docx(tmp_path):
    """Acceptance gate: Greek CV request -> AI draft -> persistence -> valid PDF + DOCX."""
    provider = GreekCvStubProvider()
    profile = CompanyProfile(
        id="cv-profile",
        owner_email="owner@example.com",
        company_name="Personal CV Workspace",
    )
    request = NaturalDocumentCreationRequest(
        request=(
            "Create a complete professional CV/resume in Greek.\n"
            "Visual style: modern. Layout: two-column. Length: 2-pages. "
            "Photo preference: without-photo.\n"
            "Do not invent employers, dates, qualifications, skills or contact details. "
            "Keep missing facts as explicit placeholders.\n"
            "Candidate information:\n"
            "Μαρία Παπαδοπούλου; Project Coordinator at Example AE, 2022-2026; "
            "Πτυχίο Διοίκησης Επιχειρήσεων, 2021; Ελληνικά και Αγγλικά."
        ),
        requested_type="professional_cv",
        language="el",
        tone="professional",
        style="modern",
        structured_fields={
            "cv_style": "modern",
            "cv_layout": "two-column",
            "cv_length": "2-pages",
            "photo_preference": "without-photo",
            "fact_integrity_required": True,
        },
    )

    preview = run(create_natural_document(request, profile, provider))

    assert preview.status == "created"
    assert preview.document.document_type == "professional_cv"
    assert preview.document.language == "el"
    assert "Επαγγελματικό Προφίλ" in preview.document.content
    assert "ΕΠΑΓΓΕΛΜΑΤΙΚΗ ΕΜΠΕΙΡΙΑ" in preview.document.content
    assert preview.document.unresolved_fields == ["EMAIL", "PHONE"]

    sent_request, sent_context = provider.calls[0]
    assert "Visual style: modern" in sent_request
    assert "Layout: two-column" in sent_request
    assert "Photo preference: without-photo" in sent_request
    assert "Do not invent employers" in sent_request
    assert sent_context["document_type"] == "professional_cv"
    assert sent_context["language"] == "el"
    assert sent_context["style"] == "modern"

    persistence = SQLitePersistenceProvider(tmp_path / "cv-e2e.db")
    run(persistence.initialize())
    document_router.configure_document_studio_router(persistence, None, None)

    document_payload = {
        "title": preview.document.title,
        "document_type": preview.document.document_type,
        "category": preview.document.category,
        "language": preview.document.language,
        "content_text": preview.document.content,
        "searchable_text": preview.document.content,
        "content_html": (
            "<article><h1>Επαγγελματικό Βιογραφικό</h1>"
            "<p>Μαρία Παπαδοπούλου</p>"
            "<h2>Επαγγελματικό Προφίλ</h2>"
            "<p>Στέλεχος διοίκησης με εμπειρία στην οργάνωση έργων.</p></article>"
        ),
        "design": {
            "cv_style": "modern",
            "cv_layout": "two-column",
            "cv_length": "2-pages",
            "photo_preference": "without-photo",
        },
        "metadata": {
            "persisted_from_preview": True,
            "intentional_blank_fields": preview.document.unresolved_fields,
            "fact_integrity_required": True,
        },
    }

    saved = run(document_router.create_document(document_payload, "owner@example.com"))
    reloaded = run(document_router.get_document(saved.id, "owner@example.com"))

    assert reloaded.document_type == "professional_cv"
    assert reloaded.language == "el"
    assert reloaded.design["cv_style"] == "modern"
    assert reloaded.design["cv_layout"] == "two-column"
    assert reloaded.metadata["fact_integrity_required"] is True
    assert "Μαρία Παπαδοπούλου" in reloaded.content_text
    assert "EMAIL" in reloaded.metadata["intentional_blank_fields"]

    pdf = render_pdf_bytes(reloaded, profile)
    docx = render_docx_bytes(reloaded, profile)

    assert pdf.startswith(b"%PDF-")
    assert b"xref" in pdf
    assert b"%%EOF" in pdf
    assert len(pdf) > 1000

    with zipfile.ZipFile(BytesIO(docx)) as archive:
        names = set(archive.namelist())
        assert "word/document.xml" in names
        xml = archive.read("word/document.xml").decode("utf-8")
        assert "Επαγγελματικό Βιογραφικό" in xml or "ΜΑΡΙΑ ΠΑΠΑΔΟΠΟΥΛΟΥ" in xml
        assert "Επαγγελματικό Προφίλ" in xml
        assert "ΕΠΑΓΓΕΛΜΑΤΙΚΗ ΕΜΠΕΙΡΙΑ" in xml

    assert len(docx) > 1000
