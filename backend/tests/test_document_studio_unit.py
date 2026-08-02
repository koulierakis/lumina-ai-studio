from __future__ import annotations

import zipfile
from io import BytesIO

from document_studio.models import CompanyProfile, CorporateDocument, DocumentCollection
from document_studio.service import (
    CHART_TYPES,
    CLAUSE_LIBRARY,
    COMPONENT_LIBRARY,
    COVER_STYLES,
    DOCUMENT_TYPE_CATALOG,
    EXPORT_FORMATS,
    SMART_TABLE_TYPES,
    TEMPLATES,
    analyze_document,
    apply_design_system,
    apply_document_operation,
    build_package,
    classify_document_request,
    compare_documents,
    extract_text_from_upload,
    get_template,
    legal_review_document,
    quality_score,
    render_classified_document,
    render_document_html,
    render_docx_bytes,
    render_pdf_bytes,
    render_text_export,
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

    assert pdf.startswith(b"%PDF-1.4")
    assert b"Board Resolution" in pdf
    with zipfile.ZipFile(BytesIO(docx)) as archive:
        assert "word/document.xml" in archive.namelist()
        assert "Board Resolution" in archive.read("word/document.xml").decode("utf-8")


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
    assert pdf.startswith(b"%PDF-1.4")
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
