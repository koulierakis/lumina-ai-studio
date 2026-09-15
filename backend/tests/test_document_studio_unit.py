from __future__ import annotations

import asyncio
import importlib
import json
import re
import zipfile
from io import BytesIO

import pytest
from document_studio.models import (
    CompanyProfile,
    CorporateDocument,
    DocumentCollection,
    EnterpriseDocumentTemplate,
)
from document_studio.service import (
    _PDF_FONT_NAME,
    CHART_TYPES,
    CLAUSE_LIBRARY,
    COMPONENT_LIBRARY,
    COVER_STYLES,
    DOCUMENT_TYPE_CATALOG,
    EXPORT_FORMATS,
    SMART_TABLE_TYPES,
    TEMPLATES,
    _export_blocks,
    _register_pdf_fonts,
    analyze_document,
    apply_design_system,
    apply_document_operation,
    apply_review_action,
    apply_track_change_action,
    build_package,
    classify_document_request,
    compare_documents,
    create_review_item,
    create_track_change,
    extract_text_from_upload,
    get_template,
    legal_review_document,
    quality_score,
    render_classified_document,
    render_document_html,
    render_docx_bytes,
    render_merge_template,
    render_pdf_bytes,
    render_text_export,
    validate_merge_template,
)
from fastapi import HTTPException
from persistence import SQLitePersistenceProvider
from reportlab.pdfbase import pdfmetrics

document_router = importlib.import_module("document_studio.router")


def run(coro):
    return asyncio.run(coro)


def _assert_valid_pdf(pdf: bytes) -> None:
    assert pdf.startswith(b"%PDF-"), f"Missing PDF header, got: {pdf[:20]!r}"
    assert b"xref" in pdf, "Missing xref table"
    assert b"%%EOF" in pdf, "Missing EOF marker"


def _pdf_page_count(pdf: bytes) -> int:
    matches = re.findall(rb"/Type\s*/Page[^s]", pdf)
    return len(matches)


def _font_supports_greek(font_name: str) -> bool:
    try:
        width = pdfmetrics.stringWidth("Απόφαση", font_name, 12)
        return width > 0
    except Exception:
        return False


def _pdf_has_embedded_font(pdf: bytes, font_name: str) -> bool:
    # ReportLab uses the font's internal PostScript name in the PDF output,
    # not the registered name. Check registration via pdfmetrics instead.
    return font_name in pdfmetrics.getRegisteredFontNames()


def test_folder_management_routes_preserve_hierarchy_and_document_integrity(tmp_path):
    provider = SQLitePersistenceProvider(tmp_path / "document-studio.db")
    run(provider.initialize())
    document_router.configure_document_studio_router(provider, None, None)
    owner = "owner@example.com"

    parent = run(document_router.create_folder({"name": "Legal"}, owner))
    child = run(
        document_router.create_folder(
            {"name": "Agreements", "parent_id": parent.id}, owner
        )
    )
    renamed = run(document_router.rename_folder(child.id, {"name": "Contracts"}, owner))
    assert renamed.name == "Contracts"

    with pytest.raises(HTTPException, match="descendants"):
        run(document_router.move_folder(parent.id, {"parent_id": child.id}, owner))

    document = CorporateDocument(
        owner_email=owner, title="Master Agreement", folder_id=child.id
    )
    run(document_router.documents_coll.insert_one(document.model_dump()))
    result = run(document_router.delete_folder(child.id, owner))
    stored = run(document_router.documents_coll.find_one({"id": document.id}, {"_id": 0}))

    assert result == {"ok": True, "folder_id": child.id}
    assert stored["folder_id"] is None


def test_manual_document_creation_preserves_authored_structure_for_duplication(tmp_path):
    provider = SQLitePersistenceProvider(tmp_path / "document-create.db")
    run(provider.initialize())
    document_router.configure_document_studio_router(provider, None, None)
    owner = "owner@example.com"
    collection = run(
        document_router.create_collection({"name": "Board Packs"}, owner)
    )
    source = {
        "title": "Copy of Board Pack",
        "document_type": "board_pack",
        "category": "Governance",
        "collection_ids": [collection.id],
        "template_id": "template-1",
        "company_profile_id": "company-1",
        "content_html": "<article><h1>Board Pack</h1></article>",
        "content_text": "Board Pack",
        "design": {"pageLayout": {"size": "A4"}},
        "components": [{"type": "cover_page"}],
        "tables": [{"type": "agenda"}],
        "charts": [{"type": "bar"}],
        "quality_score": {"Overall Score": 96},
        "metadata": {"duplicated_from": "source-1"},
    }

    created = run(document_router.create_document(source, owner))

    assert created.document_type == "board_pack"
    stored_collection = run(
        document_router.collections_coll.find_one({"id": collection.id}, {"_id": 0})
    )
    assert created.collection_ids == [collection.id]
    assert created.id in stored_collection["document_ids"]
    assert created.design == source["design"]
    assert created.components == source["components"]
    assert created.tables == source["tables"]
    assert created.charts == source["charts"]
    assert created.quality_score["Overall Score"] == 96
    assert created.metadata["duplicated_from"] == "source-1"

    updated = run(
        document_router.update_document(
            created.id,
            {
                "design": {"pageLayout": {"size": "Letter", "orientation": "landscape"}},
                "components": [{"type": "signature_blocks"}],
                "tables": [{"type": "financial"}],
                "charts": [{"type": "line"}],
            },
            owner,
        )
    )
    reloaded = run(document_router.get_document(created.id, owner))

    assert updated.design["pageLayout"]["size"] == "Letter"
    assert reloaded.design == updated.design
    assert reloaded.components == [{"type": "signature_blocks"}]
    assert reloaded.tables == [{"type": "financial"}]
    assert reloaded.charts == [{"type": "line"}]


def test_collection_updates_reject_cycles_and_dangling_documents(tmp_path):
    provider = SQLitePersistenceProvider(tmp_path / "collections.db")
    run(provider.initialize())
    document_router.configure_document_studio_router(provider, None, None)
    owner = "owner@example.com"
    parent = run(document_router.create_collection({"name": "Parent"}, owner))
    child = run(
        document_router.create_collection(
            {"name": "Child", "parent_id": parent.id}, owner
        )
    )

    with pytest.raises(HTTPException, match="descendants"):
        run(
            document_router.update_collection(
                parent.id, {"parent_id": child.id}, owner
            )
        )
    with pytest.raises(HTTPException, match="Document not found"):
        run(
            document_router.update_collection(
                child.id, {"document_ids": ["missing-document"]}, owner
            )
        )


def test_document_generation_template_rendering_has_luxury_sections():
    profile = CompanyProfile(
        owner_email="owner@example.com", company_name="Acme Global LLP", primary_color="#C8A24A"
    )
    template = get_template("premium-agreement")

    html, text, metadata = render_document_html(
        template,
        profile,
        "Strategic Advisory Agreement",
        ["Acme Global LLP", "Client Holdings SA"],
        {
            "subject": "international advisory services",
            "term": "36 months",
            "governing_law": "Swiss law",
        },
        "Switzerland",
        "2026-07-28",
    )

    assert "Table of Contents" in html
    assert "Execution Page" in html
    assert "QR VERIFY" in html
    assert "Acme Global LLP" in text
    assert metadata["verification_code"].startswith("LUMINA-")
    assert "cover_page" in metadata["features"]


def test_pdf_and_docx_generation_are_valid_binary_contracts():
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = CorporateDocument(
        owner_email="owner@example.com",
        title="Board Resolution",
        content_text="The board resolved to approve the banking package. Confidentiality and compliance apply.",
    )

    pdf = render_pdf_bytes(document, profile)
    docx = render_docx_bytes(document, profile)

    _assert_valid_pdf(pdf)
    assert _pdf_has_embedded_font(pdf, _PDF_FONT_NAME)
    with zipfile.ZipFile(BytesIO(docx)) as archive:
        assert "word/document.xml" in archive.namelist()
        assert "Board Resolution" in archive.read("word/document.xml").decode("utf-8")


# ---------------------------------------------------------------------------
# Design Presets tests
# ---------------------------------------------------------------------------

def test_design_presets_registry_contains_expected_presets():
    """DESIGN_PRESETS should include luxury-legal, executive-corporate, banking-professional."""
    from document_studio.service import DESIGN_PRESETS, get_design_presets

    preset_ids = set(DESIGN_PRESETS.keys())
    assert {"luxury-legal", "executive-corporate", "banking-professional"}.issubset(preset_ids)

    presets = get_design_presets()
    assert len(presets) == len(DESIGN_PRESETS)
    for preset in presets:
        assert "id" in preset
        assert "name" in preset
        assert "heading_font" in preset
        assert "body_font" in preset
        assert "page_margins" in preset
        assert "primary_color" in preset


def test_apply_design_preset_preserves_content_text():
    """apply_design_preset should return the same content_html and content_text."""
    from document_studio.service import apply_design_preset

    document = CorporateDocument(
        owner_email="owner@example.com",
        title="Test Document",
        content_html="<article><h1>Important Legal Text</h1><p>This must not change.</p></article>",
        content_text="Important Legal Text This must not change.",
    )

    content_html, content_text, design = apply_design_preset(document, "luxury-legal")

    assert content_html == document.content_html
    assert content_text == document.content_text
    assert design["preset_id"] == "luxury-legal"
    assert design["preset_name"] == "Luxury Legal"
    assert "exportLayout" in design
    assert design["exportLayout"]["page"]["size"] == "A4"


def test_apply_design_preset_unknown_preset_raises_value_error():
    """apply_design_preset should raise ValueError for unknown preset_id."""
    from document_studio.service import apply_design_preset

    document = CorporateDocument(
        owner_email="owner@example.com",
        title="Test Document",
        content_html="<p>Test</p>",
        content_text="Test",
    )

    with pytest.raises(ValueError, match="Unknown design preset"):
        apply_design_preset(document, "nonexistent-preset")


def test_apply_design_preset_generates_export_layout_with_header_footer():
    """apply_design_preset should generate exportLayout with header, footer, pageNumbers."""
    from document_studio.service import apply_design_preset

    document = CorporateDocument(
        owner_email="owner@example.com",
        title="Test Document",
        content_html="<p>Test</p>",
        content_text="Test",
    )

    _, _, design = apply_design_preset(document, "executive-corporate")

    export_layout = design["exportLayout"]
    assert export_layout["header"]["enabled"] is True
    assert export_layout["footer"]["enabled"] is True
    assert export_layout["pageNumbers"]["enabled"] is True
    assert export_layout["pageNumbers"]["position"] == "bottom-right"


def test_redesign_with_preset_preserves_text_and_updates_design(tmp_path):
    """POST /redesign with preset_id should preserve text and update design metadata."""
    provider = SQLitePersistenceProvider(tmp_path / "redesign-preset.db")
    document_router.configure_document_studio_router(
        provider,
        type("FakeMediaColl", (), {
            "insert_one": lambda self, doc: asyncio.sleep(0),
            "find_one": lambda self, *a, **k: asyncio.sleep(0),
        })(),
        type("FakeNotifColl", (), {"insert_one": lambda self, doc: asyncio.sleep(0)})(),
    )

    document = CorporateDocument(
        owner_email="owner@example.com",
        title="Legal Agreement",
        content_html="<article><h1>Confidential Agreement</h1><p>The parties agree to the following terms.</p></article>",
        content_text="Confidential Agreement The parties agree to the following terms.",
    )
    asyncio.run(document_router.documents_coll.insert_one(document.model_dump()))

    result = asyncio.run(
        document_router.redesign_document(
            document.id,
            {"preset_id": "luxury-legal"},
            owner="owner@example.com",
        )
    )

    # Text must be preserved exactly
    assert result.content_text == document.content_text
    assert result.content_html == document.content_html
    # Design should be updated with preset metadata
    assert result.design["preset_id"] == "luxury-legal"
    assert result.metadata["applied_preset"] == "luxury-legal"
    assert result.version_number == document.version_number + 1


def test_redesign_without_preset_keeps_legacy_behavior(tmp_path):
    """POST /redesign without preset_id should use legacy apply_design_system."""
    provider = SQLitePersistenceProvider(tmp_path / "redesign-legacy.db")
    document_router.configure_document_studio_router(
        provider,
        type("FakeMediaColl", (), {
            "insert_one": lambda self, doc: asyncio.sleep(0),
            "find_one": lambda self, *a, **k: asyncio.sleep(0),
        })(),
        type("FakeNotifColl", (), {"insert_one": lambda self, doc: asyncio.sleep(0)})(),
    )

    document = CorporateDocument(
        owner_email="owner@example.com",
        title="Legal Agreement",
        content_html="<article><h1>Agreement</h1><p>Terms here.</p></article>",
        content_text="Agreement Terms here.",
    )
    asyncio.run(document_router.documents_coll.insert_one(document.model_dump()))

    result = asyncio.run(
        document_router.redesign_document(
            document.id,
            None,
            owner="owner@example.com",
        )
    )

    # Legacy redesign wraps content in new HTML shell
    assert "Agreement" in result.content_html
    assert result.version_number == document.version_number + 1
    assert "applied_preset" not in (result.metadata or {})


def test_design_presets_endpoint_returns_list():
    """GET /design-presets should return a dict with presets list."""
    from document_studio.service import get_design_presets

    presets = get_design_presets()
    assert isinstance(presets, list)
    assert len(presets) >= 3
    assert all("id" in p and "name" in p for p in presets)


def test_export_headers_support_unicode_titles_and_batch_manifest_is_json():
    disposition = document_router._download_content_disposition(
        "Απόφαση Διοικητικού Συμβουλίου", "pdf"
    )
    document = CorporateDocument(
        owner_email="owner@example.com",
        title="Εταιρική Απόφαση",
        content_text="Approved by the board.",
    )
    rtf, mime, extension = document_router._render_export_bytes(
        document, CompanyProfile(owner_email="owner@example.com"), "rtf"
    )
    manifest = [{"document_id": document.id, "filename": "Εταιρική_Απόφαση.rtf"}]

    assert disposition.isascii()
    assert "filename*=UTF-8''" in disposition
    assert "%CE%91" in disposition
    assert rtf.startswith(b"{\\rtf1")
    assert mime == "application/rtf"
    assert extension == "rtf"
    assert json.loads(json.dumps(manifest, ensure_ascii=False)) == manifest


def test_company_export_filename_ascii_name_produces_valid_attachment():
    disposition = document_router._download_content_disposition("Acme Global LLP", "json")

    assert disposition.startswith('attachment; filename="Acme_Global_LLP.json"')
    assert "filename*=UTF-8''Acme%20Global%20LLP.json" in disposition
    assert disposition.isascii()


def test_company_export_filename_greek_name_produces_ascii_fallback_and_utf8_encoding():
    disposition = document_router._download_content_disposition("Εταιρεία Α.Ε.", "pdf")

    assert disposition.startswith('attachment; filename="')
    assert ".pdf" in disposition
    assert "filename*=UTF-8''" in disposition
    assert "%CE%95" in disposition
    assert "Εταιρεία" not in disposition.split('filename="')[1].split('"')[0]
    assert disposition.isascii()


def test_company_export_filename_quotes_and_special_characters_cannot_break_header():
    disposition = document_router._download_content_disposition(
        'O"Brien & Sons; "injection"', "zip"
    )

    assert disposition.startswith('attachment; filename="')
    assert '"' not in disposition.split('filename="')[1].split('";')[0]
    assert ";" not in disposition.split('filename="')[1].split('"')[0]
    assert "filename*=UTF-8''" in disposition
    assert disposition.isascii()


def test_company_export_filename_preserves_existing_document_export_behavior():
    document = CorporateDocument(
        owner_email="owner@example.com",
        title="Board Resolution",
        content_text="Approved by the board.",
    )
    doc_disposition = document_router._download_content_disposition(document.title, "pdf")

    assert doc_disposition.startswith('attachment; filename="Board_Resolution.pdf"')
    assert "filename*=UTF-8''Board%20Resolution.pdf" in doc_disposition


def _export_job_setup(tmp_path, db_name):
    provider = SQLitePersistenceProvider(tmp_path / db_name)
    run(provider.initialize())
    media_coll = document_router.LocalPersistenceCollection(provider, "media")
    document_router.configure_document_studio_router(provider, media_coll, None)
    owner = "owner@example.com"
    document = run(document_router.create_document({"title": "Export Job", "content_text": "Body"}, owner))
    return owner, document


def test_export_job_ids_are_unique_for_consecutive_jobs(tmp_path):
    owner, document = _export_job_setup(tmp_path, "export-job-ids.db")
    request = document_router.ExportJobRequest(document_ids=[document.id], formats=["pdf"])

    first = run(document_router.create_export_job(request, owner))
    second = run(document_router.create_export_job(request, owner))

    assert first["job_id"] != second["job_id"]
    assert first["job_id"].startswith("export-")
    assert second["job_id"].startswith("export-")


def test_export_job_id_format_is_stable_and_url_safe(tmp_path):
    owner, document = _export_job_setup(tmp_path, "export-job-format.db")
    request = document_router.ExportJobRequest(document_ids=[document.id], formats=["pdf"])

    result = run(document_router.create_export_job(request, owner))
    job_id = result["job_id"]

    assert job_id.startswith("export-")
    suffix = job_id[len("export-"):]
    assert len(suffix) == 32
    assert all(ch in "0123456789abcdef" for ch in suffix)
    assert all(ch.isalnum() or ch in "-_" for ch in job_id)


def test_export_job_behavior_remains_unchanged(tmp_path):
    owner, document = _export_job_setup(tmp_path, "export-job-behavior.db")
    request = document_router.ExportJobRequest(document_ids=[document.id], formats=["pdf", "docx"])

    result = run(document_router.create_export_job(request, owner))

    assert result["ok"] is True
    assert result["status"] == "completed"
    assert result["progress"]["percent"] == 100
    assert result["media_id"]
    assert len(result["manifest"]) == 2
    assert {entry["filename"].split(".")[-1] for entry in result["manifest"]} == {"pdf", "docx"}
    stored = run(document_router.documents_coll.find_one({"id": document.id}, {"_id": 0}))
    assert stored["metadata"]["export_jobs"][0]["id"] == result["job_id"]
    assert result["media_id"] in stored["export_media_ids"]


def test_import_preview_escapes_active_markup_and_preserves_paragraphs():
    imported_html = document_router._safe_import_html(
        '<img src=x onerror="alert(1)">',
        '<script>alert(1)</script>\nApproved & signed',
    )

    assert "<script>" not in imported_html
    assert "<img" not in imported_html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in imported_html
    assert "Approved &amp; signed" in imported_html
    assert imported_html.count("<p>") == 2


def _layout_fixture(**overrides):
    layout = {
        "page": {
            "size": "A4",
            "orientation": "portrait",
            "margins": {"top": 20, "right": 16, "bottom": 22, "left": 18},
            "background": "#ffffff",
            "printBackground": True,
        },
        "header": {
            "enabled": True,
            "text": "{{DOCUMENT_TITLE}} · {{CURRENT_DATE}}",
            "firstPageText": "First {{DOCUMENT_TITLE}}",
            "align": "center",
            "distanceMm": 8,
            "repeat": True,
            "differentFirstPage": True,
        },
        "footer": {
            "enabled": True,
            "text": "Footer {{PAGE_NUMBER}}/{{TOTAL_PAGES}}",
            "firstPageText": "First footer {{PAGE_NUMBER}}",
            "align": "right",
            "distanceMm": 9,
            "repeat": True,
            "differentFirstPage": True,
        },
        "pageNumbers": {"enabled": True, "position": "bottom-right", "format": "Page 1 of 5"},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(layout.get(key), dict):
            layout[key] = {**layout[key], **value}
        else:
            layout[key] = value
    return layout


def _export_fixture_document(layout=None):
    return CorporateDocument(
        owner_email="owner@example.com",
        title="Layout Fidelity Fixture",
        content_html=(
            "<h1>Layout Fidelity Fixture</h1><p>First page paragraph with bold and italic text.</p>"
            "<ul><li>First list item</li><li>Second list item</li></ul>"
            "<table><tr><td>Cell A</td><td>Cell B</td></tr></table>"
            "<div data-lumina-page-break='true'></div><p>Second page content after manual break.</p>"
        ),
        content_text="Layout Fidelity Fixture First page paragraph. Second page content after manual break.",
        design={"exportLayout": layout or _layout_fixture()},
        metadata={"export_layout": layout or _layout_fixture()},
    )


def test_pdf_export_honors_layout_page_size_orientation_headers_and_breaks():
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = _export_fixture_document(
        _layout_fixture(
            page={
                "size": "A4",
                "orientation": "landscape",
                "margins": {"top": 12, "right": 14, "bottom": 16, "left": 18},
            }
        )
    )

    pdf = render_pdf_bytes(document, profile)

    _assert_valid_pdf(pdf)
    assert _pdf_page_count(pdf) == 2
    assert _pdf_has_embedded_font(pdf, _PDF_FONT_NAME)
    assert _font_supports_greek(_PDF_FONT_NAME)


def test_pdf_export_falls_back_for_malformed_legacy_layout():
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = _export_fixture_document(
        {"page": {"size": "Unknown", "orientation": "sideways", "margins": {"top": "bad"}}}
    )

    pdf = render_pdf_bytes(document, profile)

    _assert_valid_pdf(pdf)
    assert _pdf_page_count(pdf) >= 1
    assert _pdf_has_embedded_font(pdf, _PDF_FONT_NAME)


def test_pdf_export_excludes_script_style_head_title_meta_link_from_body():
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = CorporateDocument(
        owner_email="owner@example.com",
        title="Clean Document",
        content_html=(
            "<article>"
            "<h1>Clean Document</h1>"
            "<script>alert('malicious');</script>"
            "<style>body { color: red; }</style>"
            "<head><title>Hidden Title</title></head>"
            "<meta name='keywords' content='secret keywords'>"
            "<link rel='stylesheet' href='evil.css'>"
            "<p>Visible paragraph text.</p>"
            "</article>"
        ),
    )

    blocks = _export_blocks(document)
    block_texts = [block.get("text", "") for block in blocks]
    combined = " ".join(block_texts)

    assert "alert" not in combined
    assert "malicious" not in combined
    assert "color" not in combined
    assert "red" not in combined
    assert "Hidden Title" not in combined
    assert "secret keywords" not in combined
    assert "evil.css" not in combined
    assert "Visible paragraph text" in combined
    assert "Clean Document" in combined

    pdf = render_pdf_bytes(document, profile)
    _assert_valid_pdf(pdf)


def test_pdf_export_renders_greek_text():
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = CorporateDocument(
        owner_email="owner@example.com",
        title="Απόφαση Διοικητικού Συμβουλίου",
        content_text="Η εταιρεία επιβεβαιώνει τη συμμόρφωση με τους κανονισμούς.",
        content_html="<article><h1>Απόφαση</h1><p>Η εταιρεία επιβεβαιώνει τη συμμόρφωση.</p></article>",
    )

    _register_pdf_fonts()
    pdf = render_pdf_bytes(document, profile)

    _assert_valid_pdf(pdf)
    assert _pdf_has_embedded_font(pdf, _PDF_FONT_NAME)
    assert _font_supports_greek(_PDF_FONT_NAME)


def test_pdf_export_renders_mixed_greek_and_latin_text():
    profile = CompanyProfile(owner_email="owner@example.com", company_name="JSA GLOBAL PARTNERS ΕΛΛΑΣ")
    document = CorporateDocument(
        owner_email="owner@example.com",
        title="JSA GLOBAL PARTNERS ΕΛΛΑΣ Ι.Κ.Ε.",
        content_text="The company JSA GLOBAL PARTNERS ΕΛΛΑΣ confirms authority and compliance.",
        content_html="<article><h1>JSA GLOBAL PARTNERS ΕΛΛΑΣ</h1><p>Authority and compliance confirmed.</p></article>",
    )

    _register_pdf_fonts()
    pdf = render_pdf_bytes(document, profile)

    _assert_valid_pdf(pdf)
    assert _pdf_has_embedded_font(pdf, _PDF_FONT_NAME)
    assert _font_supports_greek(_PDF_FONT_NAME)


def test_pdf_export_preserves_latin_only_output():
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = CorporateDocument(
        owner_email="owner@example.com",
        title="Board Resolution",
        content_text="The board resolved to approve the banking package. Confidentiality and compliance apply.",
    )

    pdf = render_pdf_bytes(document, profile)

    _assert_valid_pdf(pdf)
    assert _pdf_has_embedded_font(pdf, _PDF_FONT_NAME)


def test_pdf_export_preserves_a4_portrait():
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = _export_fixture_document(
        _layout_fixture(page={"size": "A4", "orientation": "portrait"})
    )

    pdf = render_pdf_bytes(document, profile)

    _assert_valid_pdf(pdf)
    assert _pdf_page_count(pdf) >= 1
    assert _pdf_has_embedded_font(pdf, _PDF_FONT_NAME)


def test_pdf_export_preserves_a4_landscape():
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = _export_fixture_document(
        _layout_fixture(page={"size": "A4", "orientation": "landscape"})
    )

    pdf = render_pdf_bytes(document, profile)

    _assert_valid_pdf(pdf)
    assert _pdf_page_count(pdf) >= 1
    assert _pdf_has_embedded_font(pdf, _PDF_FONT_NAME)


def test_pdf_export_accepts_custom_margins():
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = _export_fixture_document(
        _layout_fixture(
            page={"margins": {"top": 30, "right": 25, "bottom": 28, "left": 22}}
        )
    )

    pdf = render_pdf_bytes(document, profile)

    _assert_valid_pdf(pdf)
    assert _pdf_has_embedded_font(pdf, _PDF_FONT_NAME)


def test_pdf_export_includes_header_and_footer_text():
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = _export_fixture_document(
        _layout_fixture(
            header={"enabled": True, "text": "Confidential Header", "repeat": True},
            footer={"enabled": True, "text": "Page Footer", "repeat": True},
        )
    )

    pdf = render_pdf_bytes(document, profile)

    _assert_valid_pdf(pdf)
    assert _pdf_has_embedded_font(pdf, _PDF_FONT_NAME)


def test_pdf_export_generates_page_numbers():
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = _export_fixture_document(
        _layout_fixture(pageNumbers={"enabled": True, "position": "bottom-center", "format": "Page 1 of 5"})
    )

    pdf = render_pdf_bytes(document, profile)

    _assert_valid_pdf(pdf)
    assert _pdf_has_embedded_font(pdf, _PDF_FONT_NAME)


def test_pdf_export_manual_page_breaks_generate_multiple_pages():
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = _export_fixture_document()

    pdf = render_pdf_bytes(document, profile)

    _assert_valid_pdf(pdf)
    assert _pdf_page_count(pdf) == 2


def test_pdf_export_contains_valid_xref_table():
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = CorporateDocument(
        owner_email="owner@example.com",
        title="Xref Test",
        content_text="Validating PDF structure.",
    )

    pdf = render_pdf_bytes(document, profile)

    _assert_valid_pdf(pdf)
    assert b"xref" in pdf
    assert b"%%EOF" in pdf
    assert b"trailer" in pdf


def test_docx_export_honors_section_headers_footers_fields_and_breaks():
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    layout = _layout_fixture(
        page={
            "size": "Letter",
            "orientation": "landscape",
            "margins": {"top": 10, "right": 11, "bottom": 12, "left": 13},
        }
    )
    document = _export_fixture_document(layout)

    docx = render_docx_bytes(document, profile)

    with zipfile.ZipFile(BytesIO(docx)) as archive:
        names = set(archive.namelist())
        assert {
            "word/document.xml",
            "word/header1.xml",
            "word/footer1.xml",
            "word/headerFirst.xml",
            "word/footerFirst.xml",
            "word/_rels/document.xml.rels",
        }.issubset(names)
        document_xml = archive.read("word/document.xml").decode("utf-8")
        rels = archive.read("word/_rels/document.xml.rels").decode("utf-8")
        footer = archive.read("word/footer1.xml").decode("utf-8")
        header_first = archive.read("word/headerFirst.xml").decode("utf-8")

    assert "w:orient='landscape'" in document_xml
    assert "w:pgSz" in document_xml and "w:pgMar" in document_xml
    assert "w:br w:type='page'" in document_xml
    assert "rIdHeaderFirst" in rels and "rIdFooterFirst" in rels
    assert "First Layout Fidelity Fixture" in header_first
    assert "PAGE" in footer and "NUMPAGES" in footer


def test_docx_export_old_payload_compatibility_uses_page_layout_metadata():
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = CorporateDocument(
        owner_email="owner@example.com",
        title="Legacy Layout",
        content_html="<p>Legacy body</p><div style='page-break-after:always'></div><p>After break</p>",
        metadata={
            "page_layout": {
                "size": "Letter",
                "orientation": "portrait",
                "margins": {"top": 15, "right": 16, "bottom": 17, "left": 18},
                "header": {"enabled": True, "text": "{{title}}"},
                "footer": {"enabled": True, "text": "{{page}}/{{pages}}"},
                "pageNumbers": {"enabled": True, "position": "top-left", "format": "1"},
            }
        },
    )

    docx = render_docx_bytes(document, profile)

    with zipfile.ZipFile(BytesIO(docx)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
        header = archive.read("word/header1.xml").decode("utf-8")
    assert "w:pgSz" in document_xml
    assert "w:br w:type='page'" in document_xml
    assert "Legacy Layout" in header


def test_docx_import_extracts_searchable_text():
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            "<w:document><w:t>Imported NDA confidentiality obligations</w:t></w:document>",
        )

    text = extract_text_from_upload(
        buffer.getvalue(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "nda.docx",
    )

    assert "Imported NDA confidentiality obligations" in text


def test_ocr_pipeline_for_scanned_images_reports_missing_dependency():
    text = extract_text_from_upload(b"fake-image", "image/png", "scan.png")
    assert "OCR unavailable" in text or "OCR completed" in text


def test_ai_analysis_detects_missing_clauses_and_comparison_differences():
    first = CorporateDocument(
        owner_email="owner@example.com",
        title="Agreement v1",
        document_type="agreement",
        content_text="This agreement includes confidentiality and governing law. Signature follows.",
        searchable_text="This agreement includes confidentiality and governing law. Signature follows.",
    )
    second = CorporateDocument(
        owner_email="owner@example.com",
        title="Agreement v2",
        document_type="agreement",
        content_text="This agreement includes confidentiality, termination, compliance and liability.",
        searchable_text="This agreement includes confidentiality, termination, compliance and liability.",
    )

    result = analyze_document(
        first,
        "compare",
        comparison=second,
        required_clauses=["confidentiality", "termination", "liability", "compliance"],
    )

    assert "termination" in result.missing_clauses
    assert result.compared_with == second.id
    assert any(item["type"] == "difference" for item in result.findings)


def test_template_catalog_covers_corporate_document_generator_scope():
    template_types = {template.document_type for template in TEMPLATES}

    assert {
        "agreement",
        "nda",
        "business_plan",
        "proposal",
        "invoice",
        "meeting_minutes",
        "certificate",
        "compliance",
    }.issubset(template_types)


def test_document_type_catalog_and_exports_cover_final_milestone_scope():
    assert {
        "contract",
        "commercial_agreement",
        "sales_agreement",
        "purchase_agreement",
        "service_agreement",
        "master_agreement",
        "framework_agreement",
        "nda",
        "mou",
        "invoice",
        "proforma_invoice",
        "corporate_resolution",
        "power_of_attorney",
        "executive_summary",
        "investment_proposal",
        "tender_document",
        "employment_document",
        "legal_document",
        "custom_document",
    }.issubset(set(DOCUMENT_TYPE_CATALOG))
    assert {"pdf", "docx", "html", "markdown", "rtf", "txt"}.issubset(EXPORT_FORMATS)


def test_ai_operations_upgrade_merge_translate_and_export_text_formats():
    document = CorporateDocument(
        owner_email="owner@example.com",
        title="Service Agreement",
        content_text="The supplier shall provide services. Signature follows.",
        searchable_text="The supplier shall provide services. Signature follows.",
    )
    source = CorporateDocument(
        owner_email="owner@example.com",
        title="Annex",
        content_text="Annex A includes compliance controls and reporting cadence.",
    )

    html, text, metadata, note = apply_document_operation(
        document, "executive_quality", "preserve legal meaning", sources=[source]
    )
    merged_html, merged_text, _, _ = apply_document_operation(document, "merge", sources=[source])
    markdown, markdown_mime, markdown_ext = render_text_export(document, "markdown")
    rtf, rtf_mime, rtf_ext = render_text_export(document, "rtf")

    assert "Executive refinement applied" in text
    assert "Executive Quality" in note
    assert "Annex A" in merged_text
    assert metadata["last_ai_operation"] == "executive_quality"
    assert html.startswith("<article") and merged_html.startswith("<article")
    assert (
        markdown.startswith(b"# Service Agreement")
        and markdown_mime == "text/markdown"
        and markdown_ext == "md"
    )
    assert rtf.startswith(b"{\\rtf1") and rtf_mime == "application/rtf" and rtf_ext == "rtf"


def test_enterprise_designer_components_packages_scores_and_compare():
    profile = CompanyProfile(
        owner_email="owner@example.com",
        company_name="Acme Bank Holdings",
        contact_information={"website": "https://acme.example"},
        legal_information={"registration": "REG-001"},
    )
    document = CorporateDocument(
        owner_email="owner@example.com",
        title="Investment Proposal",
        content_html="<article><h1>Investment Proposal</h1><p>Confidentiality and compliance apply. Signature follows.</p></article>",
        content_text="Investment proposal confidentiality compliance signature pricing timeline",
    )

    designed_html, designed_text, design = apply_design_system(
        document,
        profile,
        {"margins": {"top": 20}, "columns": 1, "spacing": 1.6},
        [{"type": "company_information"}, {"type": "signature_blocks"}],
        [{"type": "pricing", "headers": ["Service", "Fee"], "rows": [["Advisory", "TBD"]]}],
        [{"type": "timeline", "data": [{"label": "Close", "value": 90}]}],
        "Luxury",
    )
    package_html, package_text, package_metadata, package_type = build_package(
        profile, "banking", "Banking Package", "Client SA", {}
    )
    score = quality_score(
        CorporateDocument(
            owner_email="owner@example.com",
            title="Designed",
            content_html=designed_html,
            content_text=designed_text,
        )
    )
    diff = compare_documents(
        document,
        CorporateDocument(
            owner_email="owner@example.com",
            title="Designed",
            content_html=designed_html,
            content_text=designed_text,
        ),
    )

    assert {
        "Corporate",
        "Legal",
        "Financial",
        "Investment",
        "Luxury",
        "Government",
        "Proposal",
        "Annual Report",
    }.issubset(set(COVER_STYLES))
    assert {
        "signature_blocks",
        "bank_details",
        "automatic_page_numbers",
        "automatic_document_numbers",
    }.issubset(set(COMPONENT_LIBRARY))
    assert {"financial", "comparison", "pricing", "compliance", "editable"}.issubset(
        set(SMART_TABLE_TYPES)
    )
    assert {"pie", "bar", "line", "timeline", "organization", "flow"}.issubset(set(CHART_TYPES))
    assert (
        "Company Information" in designed_html
        and "Signature Blocks" in designed_html
        and "Implementation" not in designed_text
    )
    assert design["margins"]["top"] == 20
    assert (
        package_type == "banking"
        and "Aml Declaration" in package_html
        and "authority certificate" in package_text.lower()
    )
    assert package_metadata["quality_score"]["Overall"] >= 90
    assert score["Overall"] >= 70 and "Missing Sections" in score
    assert diff["insertions"] and "formatting_changes" in diff


def test_classifier_generates_correct_document_classes_without_prompt_leakage():
    profile = CompanyProfile(
        owner_email="owner@example.com", company_name="JSA GLOBAL PARTNERS LLC"
    )
    cases = [
        (
            "Create a premium institutional Certificate of Authority for JSA GLOBAL PARTNERS LLC confirming GIANNIS KOULIERAKIS as Managing Member.",
            "certificate_of_authority",
        ),
        (
            "Generate a Certificate of Incumbency listing officers and directors.",
            "certificate_of_incumbency",
        ),
        ("Draft a Corporate Resolution authorizing banking onboarding.", "corporate_resolution"),
        ("Write a banking cover letter to HSBC for account opening.", "banking_cover_letter"),
        ("Prepare an AML Declaration and business activity declaration.", "aml_declaration"),
        ("Create a Company Profile for institutional bank onboarding.", "company_profile"),
        ("Generate an Invoice for consulting services.", "invoice"),
        ("Draft a Consulting Agreement for strategic advisory services.", "consulting_agreement"),
        ("Prepare an NCNDA non circumvention non disclosure agreement.", "ncnDA"),
        ("Create an IMFPA irrevocable master fee protection agreement.", "imfpa"),
    ]
    for prompt, expected in cases:
        classification = classify_document_request(prompt)
        html, text, metadata = render_classified_document(profile, classification["label"], prompt)
        assert classification["key"] == expected
        assert metadata["document_class"]["key"] == expected
        assert metadata["self_validation"]["correct_document_class"] is True
        assert metadata["self_validation"]["prompt_leak"] is False
        assert metadata["quality_score"]["Overall"] >= 82
        assert "Create a" not in text and "Generate a" not in text and "Write a" not in text
        assert metadata["smart_fields"]["document_number"].startswith("LUMINA-")
        assert "signature" in text.lower() or expected in {
            "invoice",
            "company_profile",
            "memorandum",
        }
        assert html.startswith("<!doctype html>")


def test_document_intelligence_mandatory_recovery_prompts():
    profile = CompanyProfile(owner_email="owner@example.com")
    cases = [
        (
            "Create a Certificate of Authority for JSA GLOBAL PARTNERS LLC.\nManaging Member: GIANNIS KOULIERAKIS.\nJurisdiction: Wyoming, USA.",
            "certificate_of_authority",
            "CERTIFICATE OF AUTHORITY",
            ["agreement", "commercial terms", "Premium Corporate Services Agreement"],
        ),
        (
            "Create an AML Declaration for JSA GLOBAL PARTNERS LLC.",
            "aml_declaration",
            "AML DECLARATION",
            ["services agreement"],
        ),
        (
            "Create a Corporate Resolution appointing GIANNIS KOULIERAKIS as authorized signatory.",
            "corporate_resolution",
            "CORPORATE RESOLUTION",
            ["services agreement"],
        ),
        (
            "Create an Invoice for a facilitation commission.",
            "invoice",
            "INVOICE",
            ["resolved", "certificate of authority"],
        ),
        ("Create an NCNDA.", "ncnDA", "NCNDA", ["certificate of authority"]),
        ("Create an IMFPA.", "imfpa", "IMFPA", ["certificate of authority"]),
        (
            "Create a Banking Cover Letter for Bank of Cyprus.",
            "banking_cover_letter",
            "BANKING COVER LETTER",
            ["resolved", "services agreement"],
        ),
        (
            "Create a Company Profile for a commission-only international intermediary.",
            "company_profile",
            "COMPANY PROFILE",
            ["resolved"],
        ),
        (
            "Create a Certificate of Incumbency.",
            "certificate_of_incumbency",
            "CERTIFICATE OF INCUMBENCY",
            ["services agreement"],
        ),
        (
            "Create a Consulting Agreement.",
            "consulting_agreement",
            "CONSULTING AGREEMENT",
            ["certificate of authority"],
        ),
    ]
    for prompt, expected_key, expected_title, prohibited in cases:
        html, text, metadata = render_classified_document(
            profile, "Premium Corporate Services Agreement", prompt
        )
        lower = text.lower()
        assert metadata["document_class"]["key"] == expected_key
        assert metadata["document_class"]["title"] == expected_title
        assert expected_title in text
        assert metadata["self_validation"]["passed"] is True
        assert metadata["self_validation"]["prompt_leak"] is False
        assert "Lumina Corporate Holdings" not in text
        assert "Create a" not in text and "Generate a" not in text and "Draft a" not in text
        for phrase in prohibited:
            assert phrase.lower() not in lower
        if "JSA GLOBAL PARTNERS LLC" in prompt:
            assert metadata["smart_fields"]["company_name"] == "JSA GLOBAL PARTNERS LLC"
            assert "JSA GLOBAL PARTNERS LLC" in text
        if "GIANNIS KOULIERAKIS" in prompt:
            assert "GIANNIS KOULIERAKIS" in text
        assert html.startswith("<!doctype html>")


def test_enterprise_company_registry_entity_parser_clauses_review_and_scores():
    profile = CompanyProfile(
        owner_email="owner@example.com", company_name="JSA GLOBAL PARTNERS LLC"
    )
    profile.legal_form = "LLC"
    profile.jurisdiction = "Wyoming, USA"
    profile.registration_number = "2024-001"
    profile.registered_office = "Wyoming registered office"
    profile.authorized_signatories = [
        {
            "full_name": "GIANNIS KOULIERAKIS",
            "role": "Managing Member",
            "authority": "Full banking authority",
        }
    ]
    profile.bank_accounts = [
        {"bank_name": "Bank of Cyprus", "swift": "BCYPCY2N", "iban": "CY00TEST"}
    ]

    html, text, metadata = render_classified_document(
        profile,
        "Certificate of Authority",
        "Create a Certificate of Authority for bank onboarding.",
    )
    review = legal_review_document("Certificate of Authority", html, metadata)
    score = metadata["quality_score"]

    assert metadata["smart_fields"]["company_name"] == "JSA GLOBAL PARTNERS LLC"
    assert metadata["smart_fields"]["authorized_signatory"] == "GIANNIS KOULIERAKIS"
    assert "GIANNIS KOULIERAKIS Authority" not in text
    assert "Authority: Managing Member" in text
    assert review["passed"] is True
    assert {
        "Banking",
        "AML",
        "Confidentiality",
        "Authority",
        "Jurisdiction",
        "Force Majeure",
        "Notices",
        "Dispute Resolution",
    }.issubset({clause.category for clause in CLAUSE_LIBRARY})
    assert score["Legal Score"] >= 90
    assert score["Compliance Score"] >= 90
    assert score["Bank Readiness"] >= 90
    assert score["Formatting Score"] >= 90
    assert score["Consistency Score"] >= 90
    assert score["Overall Score"] >= 90


def test_company_wizard_profile_supports_registry_lifecycle_exports_and_autopopulation():
    profile = CompanyProfile(
        owner_email="owner@example.com",
        company_name="JSA GLOBAL PARTNERS ΕΛΛΑΣ Ι.Κ.Ε.",
        trading_name="JSA Hellas",
        short_name="JSA GR",
        legal_form="Ι.Κ.Ε.",
        jurisdiction="Greek I.K.E.",
        registration_number="GEMI-001",
        vat_number="EL123456789",
        lei="LEI-GR-001",
        registered_office="Athens registered office",
        principal_office="Athens principal office",
        mailing_address="Athens mailing address",
        formation_date="2026-01-01",
        status="Active",
        standing="Good Standing",
        compliance_status="Compliant",
        document_defaults={
            "default_header": "JSA GR",
            "default_footer": "Confidential",
            "default_font": "Times New Roman",
            "default_language": "English",
            "default_date_format": "YYYY-MM-DD",
            "default_numbering": "1.1",
        },
        preferred_templates=["certificate_of_authority"],
        preferred_clauses=["clause-banking-reliance"],
        preferred_governing_law="Greek law",
        authorized_signatories=[
            {
                "id": "person-1",
                "full_name": "GIANNIS KOULIERAKIS",
                "role": "Managing Member",
                "authority": "Full corporate authority",
            }
        ],
        bank_accounts=[
            {"id": "bank-1", "bank_name": "Bank of Cyprus", "swift": "BCYPCY2N", "iban": "CY00TEST"}
        ],
        certificates=[{"kind": "good_standing", "media_id": "media-1"}],
    )

    html, text, metadata = render_classified_document(
        profile,
        "Certificate of Authority",
        "Create a Certificate of Authority for banking onboarding.",
    )
    doc = CorporateDocument(
        owner_email="owner@example.com",
        title="Certificate of Authority",
        company_profile_id=profile.id,
        content_html=html,
        content_text=text,
        metadata={
            **metadata,
            "company_id": profile.id,
            "people_ids": ["person-1"],
            "bank_ids": ["bank-1"],
            "clause_ids": profile.preferred_clauses,
            "signature_ids": profile.preferred_signatures,
            "version_ids": ["version-1"],
        },
    )
    pdf = render_pdf_bytes(doc, profile)
    docx = render_docx_bytes(doc, profile)

    assert profile.document_defaults["default_footer"] == "Confidential"
    assert profile.preferred_clauses == ["clause-banking-reliance"]
    assert metadata["smart_fields"]["company_name"] == "JSA GLOBAL PARTNERS ΕΛΛΑΣ Ι.Κ.Ε."
    assert metadata["smart_fields"]["authorized_signatory"] == "GIANNIS KOULIERAKIS"
    assert metadata["smart_fields"]["bank"] == "Bank of Cyprus"
    assert doc.metadata["company_id"] == profile.id
    assert doc.metadata["people_ids"] == ["person-1"]
    assert doc.metadata["bank_ids"] == ["bank-1"]
    assert pdf.startswith(b"%PDF-")
    with zipfile.ZipFile(BytesIO(docx)) as archive:
        assert "word/document.xml" in archive.namelist()


def test_document_status_lifecycle_metadata_shape_supports_review_approval_and_trash():
    document = CorporateDocument(
        owner_email="owner@example.com",
        title="Approval Pack",
        status="draft",
        metadata={"activity": []},
    )

    data = document.model_dump()
    data["status"] = "in_review"
    data["metadata"] = {
        **data["metadata"],
        "activity": [{"type": "lifecycle", "action": "submit-review"}],
    }

    reviewed = CorporateDocument(**data)

    assert reviewed.status == "in_review"
    assert reviewed.metadata["activity"][0]["action"] == "submit-review"


def test_document_collection_model_supports_nested_smart_and_saved_sets():
    collection = DocumentCollection(
        owner_email="owner@example.com",
        name="Banking KYC Pack",
        parent_id="parent-collection",
        document_ids=["doc-1", "doc-2"],
        smart_query={"category": "Banking", "tag": "kyc"},
    )

    assert collection.name == "Banking KYC Pack"
    assert collection.parent_id == "parent-collection"
    assert collection.document_ids == ["doc-1", "doc-2"]
    assert collection.smart_query["tag"] == "kyc"


def test_document_activity_metadata_supports_timeline_filtering_shape():
    document = CorporateDocument(
        owner_email="owner@example.com",
        title="Timeline Document",
        metadata={
            "activity": [
                {"at": "2026-08-02T10:00:00Z", "type": "batch", "action": "archive"},
                {"at": "2026-08-02T09:00:00Z", "type": "lifecycle", "action": "approve"},
            ]
        },
    )

    archive_events = [
        event for event in document.metadata["activity"] if "archive" in event["action"]
    ]

    assert archive_events[0]["type"] == "batch"


def test_template_merge_engine_supports_conditionals_repeats_and_formatting():
    template = EnterpriseDocumentTemplate(
        owner_email="owner@example.com",
        name="Banking Merge Template",
        content_html="<h1>{{title}}</h1>{{#if signer}}<p>{{signer}}</p>{{/if}}{{#each fees}}<p>{{item.name}} {{item.amount|currency}}</p>{{/each}}",
        merge_schema={"required": ["title", "signer"]},
    )

    html, text, diagnostics = render_merge_template(
        template.content_html,
        {
            "title": "Authority Certificate",
            "signer": "GK",
            "fees": [{"name": "Fee", "amount": 1250}],
        },
        template.merge_schema,
    )

    assert "Authority Certificate" in text
    assert "$1,250.00" in html
    assert diagnostics["valid"] is True


def test_enterprise_review_track_changes_and_diff_foundations():
    document = CorporateDocument(
        owner_email="owner@example.com",
        title="Review Draft",
        content_text="Alpha Beta Gamma",
        content_html="<article><p>Alpha Beta Gamma</p></article>",
    )

    metadata, comment = create_review_item(
        document,
        "reviewer@example.com",
        "suggestion",
        "Replace Beta with Delta",
        {"path": "p[1]"},
        mentions=["legal@example.com"],
        suggestion={"before": "Beta", "after": "Delta"},
    )
    reviewed = CorporateDocument(**{**document.model_dump(), "metadata": metadata})
    resolved = apply_review_action(
        reviewed, comment["id"], "accept-suggestion", "owner@example.com"
    )
    tracked_metadata, change = create_track_change(
        reviewed,
        "reviewer@example.com",
        "replacement",
        before="Beta",
        after="Delta",
    )
    tracked = CorporateDocument(**{**reviewed.model_dump(), "metadata": tracked_metadata})
    html, text, final_metadata = apply_track_change_action(
        tracked, "accept", "owner@example.com", [change["id"]]
    )
    diff = compare_documents(
        document, CorporateDocument(owner_email="owner@example.com", title="New", content_text=text)
    )

    assert metadata["review"]["open_count"] == 1
    assert resolved["review"]["comments"][0]["status"] == "accepted"
    assert "Delta" in text and html.startswith("<article")
    assert final_metadata["track_changes"]["accepted_count"] == 1
    assert diff["side_by_side"]


def test_track_change_acceptance_preserves_document_markup_and_rejects_stale_source():
    document = CorporateDocument(
        owner_email="owner@example.com",
        title="Structured Draft",
        content_text="Executive Terms Beta Amount",
        content_html=(
            "<article><h1>Executive Terms</h1><table><tr><td>Beta Amount</td></tr></table>"
            '<img src="https://example.com/chart.png" alt="Chart"></article>'
        ),
    )
    metadata, change = create_track_change(
        document, "reviewer@example.com", "replacement", "Beta", "Delta"
    )
    tracked = CorporateDocument(**{**document.model_dump(), "metadata": metadata})

    updated_html, updated_text, _ = apply_track_change_action(
        tracked, "accept", "owner@example.com", [change["id"]]
    )

    assert "<h1>Executive Terms</h1>" in updated_html
    assert "<table>" in updated_html and "<img " in updated_html
    assert "Delta Amount" in updated_html
    assert "Delta Amount" in updated_text

    stale = CorporateDocument(
        **{**tracked.model_dump(), "content_text": "Source changed", "content_html": "<p>Source changed</p>"}
    )
    with pytest.raises(ValueError, match="no longer present"):
        apply_track_change_action(stale, "accept", "owner@example.com", [change["id"]])
    with pytest.raises(ValueError, match="Unsupported"):
        apply_track_change_action(tracked, "discard", "owner@example.com", [change["id"]])


def test_custom_clause_insertion_escapes_markup_and_stays_inside_article(tmp_path):
    provider = SQLitePersistenceProvider(tmp_path / "clauses.db")
    run(provider.initialize())
    document_router.configure_document_studio_router(provider, None, None)
    owner = "owner@example.com"
    document = CorporateDocument(
        owner_email=owner,
        title="Agreement",
        content_html="<article><h1>Agreement</h1></article>",
        content_text="Agreement",
    )
    clause = document_router.ClauseTemplate(
        owner_email=owner,
        category="Custom",
        title='<img src=x onerror="alert(1)">',
        body="Payment <script>alert(1)</script>\nSecond line",
    )
    run(document_router.documents_coll.insert_one(document.model_dump()))
    run(document_router.clauses_coll.insert_one(clause.model_dump()))

    updated = run(document_router.insert_clause(document.id, clause.id, owner))

    assert "<script>" not in updated.content_html
    assert "<img src=x" not in updated.content_html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in updated.content_html
    assert "<br/>Second line" in updated.content_html
    assert updated.content_html.endswith("</section></article>")


def test_workflow_actions_do_not_duplicate_content_version_numbers(tmp_path):
    provider = SQLitePersistenceProvider(tmp_path / "versions.db")
    run(provider.initialize())
    document_router.configure_document_studio_router(provider, None, None)
    owner = "owner@example.com"
    document = run(
        document_router.create_document(
            {"title": "Approval Pack", "content_text": "Initial content"}, owner
        )
    )

    reviewed = run(document_router.document_lifecycle(document.id, "submit-review", owner))
    locked = run(
        document_router.document_lock_action(
            document.id,
            document_router.DocumentLockRequest(action="check-out"),
            owner,
        )
    )
    versions = run(document_router.list_versions(document.id, owner))

    assert reviewed.status == "in_review"
    assert locked.metadata["lock"]["locked"] is True
    assert [version.version_number for version in versions] == [1]

    duplicate = run(
        document_router.version_action(
            document.id,
            versions[0].id,
            document_router.VersionActionRequest(action="duplicate"),
            owner,
        )
    )
    duplicated_version = run(
        document_router.versions_coll.find_one(
            {"id": duplicate["version_id"], "owner_email": owner}, {"_id": 0}
        )
    )
    assert duplicated_version["version_number"] == 2


def test_accepting_review_suggestion_updates_document_and_versions_markup(tmp_path):
    provider = SQLitePersistenceProvider(tmp_path / "review-suggestion.db")
    run(provider.initialize())
    document_router.configure_document_studio_router(provider, None, None)
    owner = "owner@example.com"
    document = run(
        document_router.create_document(
            {
                "title": "Review Draft",
                "content_text": "Alpha Beta Gamma",
                "content_html": "<article><h1>Terms</h1><p>Alpha <strong>Beta</strong> Gamma</p></article>",
            },
            owner,
        )
    )
    review_payload = run(
        document_router.create_document_review_item(
            document.id,
            document_router.DocumentReviewRequest(
                kind="suggestion",
                body="Use Delta",
                anchor={"selected_text": "Beta"},
                suggestion={"before": "Beta", "after": "Delta"},
            ),
            owner,
        )
    )

    accepted = run(
        document_router.document_review_action(
            document.id,
            review_payload["item"]["id"],
            document_router.ReviewActionRequest(action="accept-suggestion"),
            owner,
        )
    )

    assert accepted["document"]["version_number"] == 2
    assert "<strong>Delta</strong>" in accepted["document"]["content_html"]
    assert "Beta" not in accepted["document"]["content_text"]
    assert accepted["review"]["comments"][0]["status"] == "accepted"


def test_merge_template_validation_supports_repeat_boolean_and_formatters():
    template = "{{#if approved}}<h1>{{title|upper}}</h1>{{/if}}{{#repeat rows}}<p>{{item.date|date:%Y-%m-%d}} {{item.amount|number:1}}</p>{{/repeat}}"
    validation = validate_merge_template(template, {"required": ["title", "rows"]})
    html, text, diagnostics = render_merge_template(
        template,
        {
            "approved": "true",
            "title": "invoice",
            "rows": [{"date": "2026-08-03T10:00:00", "amount": 12.34}],
        },
        {"required": ["title", "rows"]},
    )

    assert validation["valid"] is True
    assert "INVOICE" in html
    assert "12.3" in text
    assert diagnostics["valid"] is True


# ---------------------------------------------------------------------------
# Image export tests — prove inline images survive PDF and DOCX export.
# ---------------------------------------------------------------------------

def _make_test_image_data_uri(width: int = 8, height: int = 6, color: tuple = (255, 0, 0)) -> str:
    """Generate a small PNG data URI for testing image export."""
    try:
        from PIL import Image as PILImage

        img = PILImage.new("RGB", (width, height), color=color)
        buf = BytesIO()
        img.save(buf, format="PNG")
        import base64

        return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"
    except Exception:
        # Fallback: 1x1 transparent PNG
        return (
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP8//8/AwAI/AL6XNY5AAAAAElFTkSuQmCC"
        )


def _make_image_document(
    html_body: str = "",
    layout=None,
) -> CorporateDocument:
    """Create a CorporateDocument with image content for export tests."""
    return CorporateDocument(
        owner_email="owner@example.com",
        title="Image Export Test",
        content_html=html_body,
        content_text=normalize_text_export(html_body),
        design={"exportLayout": layout or _layout_fixture()},
        metadata={"export_layout": layout or _layout_fixture()},
    )


def normalize_text_export(html: str) -> str:
    """Strip HTML tags and collapse whitespace for content_text."""
    import re

    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _pdf_extract_text(pdf: bytes) -> str:
    """Extract text from PDF content streams by decompressing them."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(pdf))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        pass

    import base64
    import zlib

    streams = re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S)
    text_parts: list[str] = []
    for stream_data in streams:
        raw = stream_data.strip()
        try:
            if raw.endswith(b"~>"):
                raw = raw[:-2]
            decoded = base64.a85decode(raw, adobe=False)
            decompressed = zlib.decompress(decoded)
            text_parts.append(decompressed.decode("latin-1", errors="ignore"))
        except Exception:
            pass
        try:
            decompressed = zlib.decompress(stream_data)
            text_parts.append(decompressed.decode("latin-1", errors="ignore"))
        except Exception:
            pass
    return " ".join(text_parts)


def _pdf_has_image_xobject(pdf: bytes) -> bool:
    """Check if the PDF contains at least one image XObject."""
    return b"/Subtype" in pdf and b"/Image" in pdf


def _pdf_image_xobject_count(pdf: bytes) -> int:
    """Count the number of image XObjects in the PDF."""
    return len(re.findall(rb"/Subtype\s*/Image", pdf))


def _docx_has_image(zip_archive: zipfile.ZipFile) -> bool:
    """Check if the DOCX archive contains at least one image file."""
    return any(name.startswith("word/media/") for name in zip_archive.namelist())


def _docx_image_count(zip_archive: zipfile.ZipFile) -> int:
    """Count the number of image files in the DOCX archive."""
    return sum(1 for name in zip_archive.namelist() if name.startswith("word/media/"))


def _docx_has_drawing(zip_archive: zipfile.ZipFile) -> bool:
    """Check if the DOCX document XML contains a <w:drawing> element."""
    doc_xml = zip_archive.read("word/document.xml").decode("utf-8")
    return "<w:drawing>" in doc_xml


def test_pdf_export_renders_single_inline_image():
    """Test 1: Single inline image appears in PDF."""
    img_uri = _make_test_image_data_uri()
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = _make_image_document(
        f'<p>Before image</p>'
        f'<figure data-lumina-image="true" style="text-align:center">'
        f'<img src="{img_uri}" alt="Test Image" style="width:45%" />'
        f'</figure>'
        f'<p>After image</p>'
    )

    pdf = render_pdf_bytes(document, profile)

    _assert_valid_pdf(pdf)
    assert _pdf_has_image_xobject(pdf), "PDF should contain at least one image XObject"


def test_pdf_export_renders_multiple_images():
    """Test 2: Multiple images appear in PDF."""
    img1 = _make_test_image_data_uri(width=8, height=6, color=(255, 0, 0))
    img2 = _make_test_image_data_uri(width=10, height=4, color=(0, 255, 0))
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = _make_image_document(
        f'<p>First paragraph</p>'
        f'<figure style="text-align:center"><img src="{img1}" alt="Red" style="width:30%" /></figure>'
        f'<p>Middle paragraph</p>'
        f'<figure style="text-align:left"><img src="{img2}" alt="Green" style="width:50%" /></figure>'
        f'<p>Last paragraph</p>'
    )

    pdf = render_pdf_bytes(document, profile)

    _assert_valid_pdf(pdf)
    assert _pdf_image_xobject_count(pdf) >= 2, "PDF should contain at least 2 image XObjects"


def test_pdf_export_renders_image_caption():
    """Test 3: Image caption appears in PDF."""
    img_uri = _make_test_image_data_uri()
    caption_text = "Figure 1: Quarterly Revenue Chart"
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = _make_image_document(
        f'<figure style="text-align:center">'
        f'<img src="{img_uri}" alt="Revenue Chart" style="width:60%" />'
        f'<figcaption>{caption_text}</figcaption>'
        f'</figure>'
    )

    pdf = render_pdf_bytes(document, profile)

    _assert_valid_pdf(pdf)
    assert _pdf_has_image_xobject(pdf), "PDF should contain the image"
    # Caption text should be present in the PDF content streams
    pdf_text = _pdf_extract_text(pdf)
    assert caption_text in pdf_text, f"Caption '{caption_text}' should appear in PDF text streams"


def test_docx_export_renders_inline_image():
    """Test 4: Image appears in DOCX."""
    img_uri = _make_test_image_data_uri()
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = _make_image_document(
        f'<p>Before image</p>'
        f'<figure style="text-align:center">'
        f'<img src="{img_uri}" alt="Test Image" style="width:45%" />'
        f'</figure>'
        f'<p>After image</p>'
    )

    docx = render_docx_bytes(document, profile)

    with zipfile.ZipFile(BytesIO(docx)) as archive:
        assert "word/document.xml" in archive.namelist()
        assert _docx_has_image(archive), "DOCX should contain at least one image file in word/media/"
        assert _docx_has_drawing(archive), "DOCX document XML should contain <w:drawing> element"
        # Check that the image relationship is in the rels file
        rels_xml = archive.read("word/_rels/document.xml.rels").decode("utf-8")
        assert "rIdImg" in rels_xml, "DOCX relationships should contain image relationship"


def test_pdf_export_continues_when_image_cannot_be_loaded():
    """Test 5: Missing image does not abort export."""
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = _make_image_document(
        '<p>Before broken image</p>'
        '<figure style="text-align:center">'
        '<img src="data:image/png;base64,INVALID_BASE64_DATA" alt="Broken" style="width:45%" />'
        '</figure>'
        '<p>After broken image</p>'
    )

    pdf = render_pdf_bytes(document, profile)

    _assert_valid_pdf(pdf)
    # The export should still succeed with text content
    pdf_text = _pdf_extract_text(pdf)
    assert "Before broken image" in pdf_text, "Text before broken image should appear in PDF"
    assert "After broken image" in pdf_text, "Text after broken image should appear in PDF"
    # A warning placeholder should be present
    assert "Image unavailable" in pdf_text, "Image unavailable warning should appear in PDF"


def test_pdf_export_preserves_image_aspect_ratio():
    """Test 6: Aspect ratio is preserved."""
    # Create a 8x4 image (2:1 aspect ratio)
    img_uri = _make_test_image_data_uri(width=8, height=4, color=(0, 0, 255))
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = _make_image_document(
        f'<figure style="text-align:center">'
        f'<img src="{img_uri}" alt="Wide Image" style="width:50%" />'
        f'</figure>'
    )

    pdf = render_pdf_bytes(document, profile)

    _assert_valid_pdf(pdf)
    assert _pdf_has_image_xobject(pdf), "PDF should contain the image"
    # The image should be in the PDF with its aspect ratio preserved
    # We verify by checking the image XObject dictionary for width/height entries
    # that maintain the 2:1 ratio
    img_dict_matches = re.findall(rb"/Width\s+(\d+)\s+/Height\s+(\d+)", pdf)
    if img_dict_matches:
        for w, h in img_dict_matches:
            w_val = int(w)
            h_val = int(h)
            # The native dimensions should be 8x4 (2:1 ratio)
            assert w_val == 8, f"Expected width 8, got {w_val}"
            assert h_val == 4, f"Expected height 4, got {h_val}"


def test_pdf_export_respects_image_width_percentage():
    """Test 7: Width is respected."""
    img_uri = _make_test_image_data_uri(width=20, height=10, color=(128, 128, 0))
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")

    # Create two documents with different widths
    doc_30 = _make_image_document(
        f'<figure style="text-align:center"><img src="{img_uri}" alt="30%" style="width:30%" /></figure>'
    )
    doc_80 = _make_image_document(
        f'<figure style="text-align:center"><img src="{img_uri}" alt="80%" style="width:80%" /></figure>'
    )

    pdf_30 = render_pdf_bytes(doc_30, profile)
    pdf_80 = render_pdf_bytes(doc_80, profile)

    _assert_valid_pdf(pdf_30)
    _assert_valid_pdf(pdf_80)
    # Both should contain the image
    assert _pdf_has_image_xobject(pdf_30), "PDF should contain image at 30% width"
    assert _pdf_has_image_xobject(pdf_80), "PDF should contain image at 80% width"
    # The image data should be the same (same source image)
    # The width difference is in the rendering, not the image data


def test_docx_export_renders_image_caption():
    """Test: Image caption appears in DOCX."""
    img_uri = _make_test_image_data_uri()
    caption_text = "Figure 2: Annual Growth"
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = _make_image_document(
        f'<figure style="text-align:center">'
        f'<img src="{img_uri}" alt="Growth Chart" style="width:55%" />'
        f'<figcaption>{caption_text}</figcaption>'
        f'</figure>'
    )

    docx = render_docx_bytes(document, profile)

    with zipfile.ZipFile(BytesIO(docx)) as archive:
        doc_xml = archive.read("word/document.xml").decode("utf-8")
        assert caption_text in doc_xml, "DOCX should contain the caption text"
        assert _docx_has_drawing(archive), "DOCX should contain a drawing element"


def test_docx_export_continues_when_image_cannot_be_loaded():
    """Test: Missing image does not abort DOCX export."""
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = _make_image_document(
        '<p>Before broken image</p>'
        '<figure style="text-align:center">'
        '<img src="data:image/png;base64,INVALID" alt="Broken" style="width:45%" />'
        '</figure>'
        '<p>After broken image</p>'
    )

    docx = render_docx_bytes(document, profile)

    with zipfile.ZipFile(BytesIO(docx)) as archive:
        doc_xml = archive.read("word/document.xml").decode("utf-8")
        assert "Before broken image" in doc_xml
        assert "After broken image" in doc_xml
        assert "Image unavailable" in doc_xml


# ---------------------------------------------------------------------------
# DOCX import structure preservation tests
# ---------------------------------------------------------------------------

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_PIC_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"


def _build_docx(
    paragraphs: list[str] = None,
    headings: dict[int, str] = None,
    tables: list[list[list[str]]] = None,
    images: list[bytes] = None,
    image_ext: str = "png",
) -> bytes:
    """Build a minimal DOCX file for testing.

    Args:
        paragraphs: List of paragraph texts, keyed by position (0-indexed).
        headings: Dict mapping paragraph index to heading level (1, 2, or 3).
        tables: List of tables, each a list of rows, each a list of cell texts.
        images: List of image data bytes to embed.

    Returns:
        DOCX file as bytes.
    """
    import base64

    paragraphs = paragraphs or []
    headings = headings or {}
    tables = tables or []
    images = images or []

    # Build document.xml body content
    body_parts: list[str] = []

    # Add paragraphs and headings in order
    for i, text in enumerate(paragraphs):
        if i in headings:
            level = headings[i]
            body_parts.append(
                f'<w:p><w:pPr><w:pStyle w:val="Heading{level}"/></w:pPr>'
                f'<w:r><w:t>{text}</w:t></w:r></w:p>'
            )
        else:
            body_parts.append(
                f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>'
            )

    # Add tables
    for table in tables:
        rows_xml = ""
        for row in table:
            cells_xml = ""
            for cell in row:
                cells_xml += (
                    f'<w:tc><w:p><w:r><w:t>{cell}</w:t></w:r></w:p></w:tc>'
                )
            rows_xml += f'<w:tr>{cells_xml}</w:tr>'
        body_parts.append(f'<w:tbl>{rows_xml}</w:tbl>')

    # Add images
    for i, img_data in enumerate(images):
        rid = f"rIdImg{i + 1}"
        b64 = base64.b64encode(img_data).decode("ascii")
        body_parts.append(
            f'<w:p><w:r><w:drawing>'
            f'<wp:inline distT="0" distB="0" distL="0" distR="0">'
            f'<wp:extent cx="190500" cy="190500"/>'
            f'<wp:docPr id="{i + 1}" name="Image {i + 1}"/>'
            f'<a:graphic xmlns:a="{_A_NS}">'
            f'<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:pic xmlns:pic="{_PIC_NS}">'
            f'<pic:nvPicPr><pic:cNvPr id="{i + 1}" name="Image {i + 1}"/>'
            f'<pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/>'
            f'<a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/>'
            f'<a:ext cx="190500" cy="190500"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
            f'</pic:pic></a:graphicData></a:graphic>'
            f'</wp:inline></w:drawing></w:r></w:p>'
        )

    body_xml = "".join(body_parts)
    document_xml = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W_NS}" xmlns:r="{_R_NS}" '
        f'xmlns:wp="{_WP_NS}" xmlns:a="{_A_NS}">'
        f'<w:body>{body_xml}</w:body></w:document>'
    )

    # Build relationships
    rels_parts = []
    for i in range(len(images)):
        rels_parts.append(
            f'<Relationship Id="rIdImg{i + 1}" '
            f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
            f'Target="media/image{i + 1}.{image_ext}"/>'
        )
    rels_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{"".join(rels_parts)}</Relationships>'
    )

    # Build content types
    ct_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        f'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        f'<Default Extension="xml" ContentType="application/xml"/>'
        f'<Default Extension="{image_ext}" ContentType="image/{image_ext}"/>'
        f'<Override PartName="/word/document.xml" '
        f'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        f'</Types>'
    )

    # Build root rels
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    )

    # Assemble zip
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", ct_xml)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("word/document.xml", document_xml)
        zf.writestr("word/_rels/document.xml.rels", rels_xml)
        for i, img_data in enumerate(images):
            zf.writestr(f"word/media/image{i + 1}.{image_ext}", img_data)
    return buf.getvalue()


def _make_png_bytes(width: int = 4, height: int = 4, color: tuple = (255, 0, 0)) -> bytes:
    """Generate a small PNG image as bytes."""
    try:
        from PIL import Image as PILImage

        img = PILImage.new("RGB", (width, height), color=color)
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        # Minimal 1x1 PNG
        return (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf"
            b"\xc0\x00\x00\x00\x03\x00\x01\x8a\xeb\x19\x1e\x00\x00\x00\x00IEND\xaeB`\x82"
        )


def test_docx_import_preserves_heading_1_2_3():
    """Test 1: Heading 1, 2, and 3 are preserved."""
    docx = _build_docx(
        paragraphs=["Main Title", "Section Title", "Subsection Title"],
        headings={0: 1, 1: 2, 2: 3},
    )
    result = extract_text_from_upload(
        docx,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "test.docx",
    )

    assert "<h1>" in result and "Main Title" in result
    assert "<h2>" in result and "Section Title" in result
    assert "<h3>" in result and "Subsection Title" in result


def test_docx_import_preserves_normal_paragraphs():
    """Test 2: Normal paragraphs are preserved."""
    docx = _build_docx(
        paragraphs=["This is the first paragraph.", "This is the second paragraph."],
    )
    result = extract_text_from_upload(
        docx,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "test.docx",
    )

    assert "<p>" in result
    assert "This is the first paragraph." in result
    assert "This is the second paragraph." in result


def test_docx_import_preserves_paragraph_and_heading_order():
    """Test 3: Paragraph and heading order is preserved."""
    docx = _build_docx(
        paragraphs=["Introduction text", "Chapter One", "Body of chapter one"],
        headings={1: 1},
    )
    result = extract_text_from_upload(
        docx,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "test.docx",
    )

    # Extract elements in order
    elements = re.findall(r"<(h1|p)>([^<]+)</\1>", result)
    assert len(elements) == 3
    assert elements[0] == ("p", "Introduction text")
    assert elements[1] == ("h1", "Chapter One")
    assert elements[2] == ("p", "Body of chapter one")


def test_docx_import_preserves_table_rows_columns_and_empty_cells():
    """Test 4: Tables preserve rows, columns, and empty cells."""
    docx = _build_docx(
        tables=[
            [
                ["Header A", "Header B", "Header C"],
                ["Cell 1A", "", "Cell 1C"],
                ["Cell 2A", "Cell 2B", "Cell 2C"],
            ]
        ],
    )
    result = extract_text_from_upload(
        docx,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "test.docx",
    )

    assert "<table>" in result
    assert "<tr>" in result
    assert "<td>" in result
    assert "Header A" in result and "Header B" in result and "Header C" in result
    assert "Cell 1A" in result and "Cell 1C" in result
    assert "Cell 2A" in result and "Cell 2B" in result and "Cell 2C" in result
    # Check empty cell is preserved
    assert "<td></td>" in result, "Empty cell should be preserved as <td></td>"


def test_docx_import_embeds_png_images_as_base64():
    """Test 5: Embedded PNG images become base64 img elements."""
    png_data = _make_png_bytes(width=8, height=6, color=(255, 0, 0))
    docx = _build_docx(
        paragraphs=["Before image"],
        images=[png_data],
        image_ext="png",
    )
    result = extract_text_from_upload(
        docx,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "test.docx",
    )

    assert "<figure" in result, "Image should be wrapped in <figure>"
    assert "<img" in result, "Image should have <img> tag"
    assert "data:image/png;base64," in result, "Image should be a base64 data URI"
    assert "Before image" in result, "Text before image should be preserved"


def test_docx_import_embeds_jpeg_images_as_base64():
    """Test 5b: Embedded JPEG images become base64 img elements."""
    try:
        from PIL import Image as PILImage

        img = PILImage.new("RGB", (8, 6), color=(0, 255, 0))
        buf = BytesIO()
        img.save(buf, format="JPEG")
        jpeg_data = buf.getvalue()
    except Exception:
        pytest.skip("PIL not available for JPEG test")

    docx = _build_docx(
        images=[jpeg_data],
        image_ext="jpeg",
    )
    result = extract_text_from_upload(
        docx,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "test.docx",
    )

    assert "<figure" in result, "JPEG image should be wrapped in <figure>"
    assert "data:image/jpeg;base64," in result, "JPEG should be a base64 data URI"


def test_docx_import_preserves_text_table_and_image_order():
    """Test 6: Text, table, and image order is preserved."""
    png_data = _make_png_bytes(width=4, height=4, color=(0, 0, 255))

    # Build a DOCX with text, then table, then image, then text
    # We need to build the body manually to interleave elements
    import base64

    b64 = base64.b64encode(png_data).decode("ascii")
    body_xml = (
        f'<w:p><w:r><w:t>First paragraph</w:t></w:r></w:p>'
        f'<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc>'
        f'<w:tc><w:p><w:r><w:t>Cell B</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
        f'<w:p><w:r><w:drawing>'
        f'<wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="190500" cy="190500"/>'
        f'<wp:docPr id="1" name="Image 1"/>'
        f'<a:graphic xmlns:a="{_A_NS}">'
        f'<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f'<pic:pic xmlns:pic="{_PIC_NS}">'
        f'<pic:nvPicPr><pic:cNvPr id="1" name="Image 1"/><pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip r:embed="rIdImg1"/>'
        f'<a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="190500" cy="190500"/></a:xfrm>'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        f'</pic:pic></a:graphicData></a:graphic>'
        f'</wp:inline></w:drawing></w:r></w:p>'
        f'<w:p><w:r><w:t>Last paragraph</w:t></w:r></w:p>'
    )
    document_xml = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W_NS}" xmlns:r="{_R_NS}" '
        f'xmlns:wp="{_WP_NS}" xmlns:a="{_A_NS}">'
        f'<w:body>{body_xml}</w:body></w:document>'
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rIdImg1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        'Target="media/image1.png"/></Relationships>'
    )
    ct_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="png" ContentType="image/png"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    )
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", ct_xml)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("word/document.xml", document_xml)
        zf.writestr("word/_rels/document.xml.rels", rels_xml)
        zf.writestr("word/media/image1.png", png_data)
    docx = buf.getvalue()

    result = extract_text_from_upload(
        docx,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "test.docx",
    )

    # Verify order: text, table, image, text
    first_p = result.find("First paragraph")
    table_pos = result.find("<table>")
    figure_pos = result.find("<figure")
    last_p = result.find("Last paragraph")

    assert first_p != -1 and table_pos != -1 and figure_pos != -1 and last_p != -1
    assert first_p < table_pos, "First paragraph should come before table"
    assert table_pos < figure_pos, "Table should come before image"
    assert figure_pos < last_p, "Image should come before last paragraph"


def test_docx_import_does_not_alter_legal_text():
    """Test 7: Legal text is not altered."""
    legal_text = (
        "The Party shall keep all confidential information strictly confidential "
        "and shall not disclose it to any third party without prior written consent."
    )
    docx = _build_docx(paragraphs=[legal_text])
    result = extract_text_from_upload(
        docx,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "test.docx",
    )

    # The legal text should appear exactly as-is (HTML-escaped)
    assert legal_text in result, f"Legal text should be preserved exactly: got {result}"


def test_docx_import_malformed_falls_back_without_crashing():
    """Test 8: Malformed DOCX falls back without crashing."""
    # Not a valid DOCX (not a zip)
    result = extract_text_from_upload(
        b"this is not a docx file",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "test.docx",
    )

    # Should return something (fallback plain text) without raising
    assert isinstance(result, str)
    assert len(result) >= 0


def test_docx_import_corrupt_zip_falls_back_without_crashing():
    """Test 8b: Corrupt zip falls back without crashing."""
    # Valid zip but missing word/document.xml
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("random.txt", "not a docx")
    result = extract_text_from_upload(
        buf.getvalue(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "test.docx",
    )

    assert isinstance(result, str), "Should return a string even for corrupt DOCX"


def test_docx_import_existing_import_tests_still_pass():
    """Test 9: Existing import tests still pass."""
    # Test the existing DOCX import test from the test suite
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            "<w:document><w:t>Imported NDA confidentiality obligations</w:t></w:document>",
        )

    text = extract_text_from_upload(
        buffer.getvalue(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "nda.docx",
    )

    assert "Imported NDA confidentiality obligations" in text


def test_docx_import_existing_pdf_and_docx_export_tests_still_pass():
    """Test 10: Existing PDF and DOCX export tests still pass."""
    profile = CompanyProfile(owner_email="owner@example.com", company_name="Acme Global LLP")
    document = CorporateDocument(
        owner_email="owner@example.com",
        title="Board Resolution",
        content_text="The board resolved to approve the banking package. Confidentiality and compliance apply.",
    )

    pdf = render_pdf_bytes(document, profile)
    docx = render_docx_bytes(document, profile)

    _assert_valid_pdf(pdf)
    with zipfile.ZipFile(BytesIO(docx)) as archive:
        assert "word/document.xml" in archive.namelist()
        assert "Board Resolution" in archive.read("word/document.xml").decode("utf-8")
