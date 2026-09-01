from __future__ import annotations

import document_studio.service as service
from document_studio.models import CompanyProfile
from document_studio.safe_smart_fields import extract_fact_safe_smart_fields

OWNER = "owner@example.com"


def test_missing_profile_facts_are_explicit_placeholders_not_on_file_claims():
    profile = CompanyProfile(owner_email=OWNER)

    fields = extract_fact_safe_smart_fields("Create a certificate of authority", profile)

    assert fields["company_name"] == "[COMPANY NAME]"
    assert fields["jurisdiction"] == "[JURISDICTION]"
    assert fields["registration_number"] == "[REGISTRATION NUMBER]"
    assert fields["tax_number"] == "[TAX NUMBER]"
    assert fields["currency"] == "[CURRENCY]"
    assert fields["authorized_signatory"] == "[AUTHORIZED SIGNATORY]"
    assert all("on file" not in str(value).casefold() for value in fields.values())


def test_profile_and_explicit_prompt_facts_are_preserved():
    profile = CompanyProfile(
        owner_email=OWNER,
        company_name="Verified Example Ltd",
        legal_form="Limited Company",
        jurisdiction="Cyprus",
        registration_number="HE 123456",
    )

    fields = extract_fact_safe_smart_fields(
        "Purpose: Bank onboarding\nAmount EUR 5000", profile
    )

    assert fields["company_name"] == "Verified Example Ltd"
    assert fields["legal_form"] == "Limited Company"
    assert fields["jurisdiction"] == "Cyprus"
    assert fields["registration_number"] == "HE 123456"
    assert fields["requested_purpose"] == "Bank onboarding"
    assert fields["currency"] == "EUR"


def test_document_studio_service_uses_fact_safe_extractor_after_package_import():
    assert service.extract_smart_fields is extract_fact_safe_smart_fields
