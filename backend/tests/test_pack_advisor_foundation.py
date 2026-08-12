from __future__ import annotations

from document_studio.models import (
    CompanyProfile,
    DocumentRecommendation,
    PackAdvisorRequest,
    PackAdvisorResponse,
)
from document_studio.pack_advisor import (
    CURRENT_DOCUMENT_TYPES,
    advise_documents,
    validate_profile_for_generation,
)
from document_studio.service import DOCUMENT_CLASS_DEFINITIONS


def minimal_profile() -> CompanyProfile:
    return CompanyProfile(
        owner_email="owner@example.com",
        company_name="",
        legal_form="",
        jurisdiction="",
    )


def rich_profile() -> CompanyProfile:
    return CompanyProfile(
        owner_email="owner@example.com",
        company_name="Verified Example Ltd",
        legal_form="Limited Company",
        jurisdiction="Cyprus",
        registration_number="HE 123456",
        registered_office="1 Verified Street, Nicosia",
        business_activities="Corporate advisory services",
        business_model="Fee-based engagements",
        source_of_funds="Operating revenue",
        source_of_wealth="Retained business earnings",
        expected_account_activity="Incoming client fees and operating expenses",
        organizational_structure="Member-managed company",
        aml_controls="Risk-based customer checks",
        beneficial_owners=[{"name": "Verified Owner"}],
        directors=[{"name": "Verified Director"}],
        authorized_signatories=[{"name": "Verified Signatory"}],
    )


def test_basic_profile_and_business_objective_return_typed_recommendations():
    result = advise_documents(
        PackAdvisorRequest(objective="Open a corporate bank account"), rich_profile()
    )

    assert isinstance(result, PackAdvisorResponse)
    assert result.objective_category == "banking"
    assert result.recommendations
    assert all(isinstance(item, DocumentRecommendation) for item in result.recommendations)


def test_required_and_optional_classification_is_deterministic():
    request = PackAdvisorRequest(objective="Complete enhanced due diligence for banking")
    first = advise_documents(request, rich_profile())
    second = advise_documents(request, rich_profile())

    assert first.model_dump() == second.model_dump()
    assert first.total_required == 6
    assert first.total_optional == 4
    assert [item.priority for item in first.recommendations[:6]] == ["required"] * 6
    assert [item.priority for item in first.recommendations[6:]] == ["optional"] * 4


def test_minimal_profile_reports_missing_data_without_inventing_values():
    profile = minimal_profile()
    before = profile.model_dump()
    result = advise_documents("Open a business bank account", profile)

    assert result.can_generate_all is False
    assert result.profile_validation["overall_missing"]
    assert "company name" in result.profile_validation["overall_missing"]
    assert profile.model_dump() == before
    serialized = str(result.model_dump())
    assert "HE 123456" not in serialized
    assert "Verified Owner" not in serialized


def test_richer_profile_improves_readiness_without_assuming_documents_exist():
    minimal = advise_documents("Open a business bank account", minimal_profile())
    rich = advise_documents("Open a business bank account", rich_profile())

    assert (
        rich.profile_validation["completeness_ratio"]
        > minimal.profile_validation["completeness_ratio"]
    )
    assert rich.can_generate_all is True
    assert not hasattr(rich, "generated_documents")


def test_all_recommendations_use_current_canonical_document_types():
    registry_types = set(DOCUMENT_CLASS_DEFINITIONS)
    objectives = [
        "Open a bank account",
        "Complete enhanced due diligence",
        "Prepare a board governance decision",
        "Create a consulting agreement",
        "Prepare general company information",
    ]

    assert registry_types == CURRENT_DOCUMENT_TYPES
    for objective in objectives:
        result = advise_documents(objective, rich_profile())
        assert {item.document_type for item in result.recommendations} <= registry_types


def test_legacy_pack_concepts_map_to_current_canonical_types():
    result = advise_documents("Complete enhanced banking EDD", rich_profile())
    by_title = {item.title: item.document_type for item in result.recommendations}

    assert by_title["Corporate Profile and Business Overview"] == "company_profile"
    assert by_title["KYC and Expected Account Activity Declaration"] == "kyc_declaration"
    assert by_title["Source of Wealth and Compliance Letter"] == "compliance_letter"


def test_duplicate_recommendations_are_prevented():
    result = advise_documents("Complete enhanced banking KYC and EDD", rich_profile())
    identifiers = [item.document_type for item in result.recommendations]

    assert len(identifiers) == len(set(identifiers))


def test_objective_interpretation_supports_corporate_legal_and_general_use_cases():
    corporate = advise_documents("Prepare a board governance decision", rich_profile())
    legal = advise_documents("Protect confidential information with an NDA", rich_profile())
    general = advise_documents("Prepare general company information", rich_profile())

    assert corporate.objective_category == "corporate"
    assert corporate.recommendations[0].document_type == "corporate_resolution"
    assert legal.objective_category == "legal"
    assert legal.recommendations[0].document_type == "nda"
    assert general.objective_category == "general"
    assert general.recommendations[0].document_type == "company_profile"


def test_pack_advisor_models_serialize_and_restore_without_schema_loss():
    request = PackAdvisorRequest(
        objective="Open a corporate bank account", company_profile_id="company-1"
    )
    response = advise_documents(request, rich_profile())
    restored = PackAdvisorResponse.model_validate(response.model_dump())

    assert request.model_dump() == {
        "objective": "Open a corporate bank account",
        "company_profile_id": "company-1",
    }
    assert restored == response


def test_profile_validation_handles_duplicates_and_unknown_types_without_generation():
    validation = validate_profile_for_generation(
        rich_profile(), ["company_profile", "company_profile", "obsolete_pack_document"]
    )

    assert validation["valid"] is False
    assert validation["unknown_document_types"] == ["obsolete_pack_document"]
    assert validation["missing_by_document"] == {}


def test_pack_advisor_has_no_provider_or_network_dependency(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr("socket.create_connection", forbidden)
    result = advise_documents("Open a bank account", rich_profile())

    assert result.recommendations
