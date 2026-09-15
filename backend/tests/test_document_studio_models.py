from __future__ import annotations

import asyncio

from document_studio.models import (
    CompanyProfile,
    DocumentGenerationRequest,
    DocumentRecommendation,
    NaturalDocumentCreationRequest,
    PackAdvisorRequest,
    PackAdvisorResponse,
    PackGenerationRequest,
    SourceCorporateFact,
    SourceFactConflict,
)
from persistence import SQLitePersistenceProvider


def run(coro):
    return asyncio.run(coro)


def test_legacy_company_profile_payload_uses_safe_advanced_defaults():
    profile = CompanyProfile(
        owner_email="owner@example.com",
        company_name="Existing Company Ltd",
    )

    assert profile.fact_provenance == {}
    assert profile.business_activities == ""
    assert profile.business_model == ""
    assert profile.source_of_funds == ""
    assert profile.source_of_wealth == ""
    assert profile.expected_account_activity == ""
    assert profile.organizational_structure == ""
    assert profile.aml_controls == ""


def test_advanced_company_profile_fields_round_trip_without_shared_defaults():
    first = CompanyProfile(
        owner_email="owner@example.com",
        business_activities="Corporate advisory services",
        fact_provenance={"registration_number": [{"source_document_id": "source-1"}]},
    )
    restored = CompanyProfile.model_validate(first.model_dump())
    second = CompanyProfile(owner_email="other@example.com")

    assert restored.business_activities == "Corporate advisory services"
    assert restored.fact_provenance == first.fact_provenance
    assert second.fact_provenance == {}


def test_source_fact_models_serialize_provenance_and_conflicts():
    fact = SourceCorporateFact(
        field_name="registration_number",
        value="HE 778899",
        source_document_id="source-1",
        source_document_name="registry.pdf",
        source_page_or_location="page 1",
        confidence=0.99,
    )
    conflict = SourceFactConflict(
        field_name="registration_number",
        conflicting_values=[fact.model_dump()],
        current_company_profile_value="HE 111111",
    )

    restored = SourceCorporateFact.model_validate(fact.model_dump())
    assert restored.id == fact.id
    assert restored.verification_status == "CANDIDATE"
    assert conflict.model_dump()["current_company_profile_value"] == "HE 111111"


def test_advanced_request_and_response_models_keep_additive_defaults():
    natural = NaturalDocumentCreationRequest(request="Create a service agreement")
    advisor = PackAdvisorRequest(objective="Open a business bank account")
    recommendation = DocumentRecommendation(
        document_type="business_nature",
        title="Business Nature Statement",
        reason="Required for onboarding",
    )
    response = PackAdvisorResponse(
        objective=advisor.objective,
        objective_category="banking",
        recommendations=[recommendation],
    )
    generation = PackGenerationRequest(objective=advisor.objective)

    assert natural.allow_fallback is True
    assert natural.structured_fields == {}
    assert response.recommendations[0].priority == "required"
    assert response.profile_validation == {}
    assert generation.selected_document_types == []
    assert generation.generate_all is False


def test_existing_document_generation_request_schema_is_unchanged():
    request = DocumentGenerationRequest(title="Legacy agreement")

    assert request.model_dump() == {
        "template_id": "premium-agreement",
        "title": "Legacy agreement",
        "prompt": "",
        "creation_mode": "template",
        "parties": [],
        "jurisdiction": "International",
        "effective_date": "Upon signature",
        "fields": {},
        "tags": [],
        "folder_id": None,
        "country": "GR",
        "language": "el",
        "company_profile_id": None,
    }


def test_company_profile_advanced_fields_persist_across_sqlite_restart(tmp_path):
    database = tmp_path / "document-studio-models.db"
    profile = CompanyProfile(
        id="company-advanced-1",
        owner_email="owner@example.com",
        company_name="Advanced Company Ltd",
        business_model="Fee-based engagements",
        source_of_funds="Operating revenue",
        fact_provenance={"company_name": [{"source_document_id": "source-1"}]},
    )

    first = SQLitePersistenceProvider(database)
    run(first.initialize())
    run(first.insert_one("company_profiles", profile.model_dump()))

    second = SQLitePersistenceProvider(database)
    run(second.initialize())
    stored = run(second.find_one("company_profiles", {"id": profile.id}))
    restored = CompanyProfile.model_validate(stored)

    assert restored.id == profile.id
    assert restored.business_model == "Fee-based engagements"
    assert restored.source_of_funds == "Operating revenue"
    assert restored.fact_provenance == profile.fact_provenance
