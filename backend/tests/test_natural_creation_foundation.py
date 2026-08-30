from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest
from document_studio.document_ai_provider import (
    DocumentAIProvider,
    DocumentAIProviderError,
    DocumentAIProviderTimeout,
    MalformedDocumentAIResponse,
)
from document_studio.models import CompanyProfile, NaturalDocumentCreationRequest
from document_studio.natural_creation import (
    InvalidNaturalCreationRequest,
    NaturalCreationProviderError,
    create_natural_document,
    interpret_natural_document_request,
)


def run(coro):
    return asyncio.run(coro)


class NaturalStubProvider(DocumentAIProvider):
    name = "natural-stub"

    def __init__(self, output=None, error: Exception | None = None, delay: float = 0):
        self.output = output
        self.error = error
        self.delay = delay
        self.calls: list[tuple[str, dict]] = []

    async def generate_document(self, request: str, context: dict):
        self.calls.append((request, deepcopy(context)))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return deepcopy(self.output)

    async def status(self):
        return {"name": self.name, "available": self.error is None}


def profile() -> CompanyProfile:
    return CompanyProfile(
        id="company-1",
        owner_email="owner@example.com",
        company_name="Verified Example Ltd",
        legal_form="Limited Company",
        jurisdiction="Cyprus",
        registration_number="HE 123456",
        fact_provenance={
            "registration_number": [
                {
                    "source_document_id": "registry-1",
                    "source_document_name": "registry.pdf",
                    "verification_status": "VERIFIED",
                }
            ]
        },
    )


def valid_output() -> dict:
    return {
        "title": "Service Agreement",
        "document_type": "service_agreement",
        "category": "Legal",
        "language": "en",
        "content": "Verified Example Ltd will provide [SERVICE DESCRIPTION].",
        "claims": [
            {
                "field_name": "company_name",
                "value": "Verified Example Ltd",
                "origin": "verified",
            },
            {
                "field_name": "draft_remedy",
                "value": "Thirty-day cure period",
                "origin": "generated",
            },
        ],
        "unresolved_fields": ["SERVICE DESCRIPTION"],
    }


def test_valid_natural_creation_request_is_interpreted_without_service_dependency():
    interpretation = interpret_natural_document_request(
        "Create a service agreement and leave the fee blank.", profile()
    )

    assert interpretation["status"] == "ready"
    assert interpretation["document_type"] == "service_agreement"
    assert interpretation["intentional_blank_fields"] == ["FEE"]
    assert interpretation["review_status"] == "LEGAL_REVIEW_RECOMMENDED"


def test_valid_mocked_provider_output_produces_typed_deterministic_result():
    request = NaturalDocumentCreationRequest(request="Create a service agreement")
    first_provider = NaturalStubProvider(valid_output())
    second_provider = NaturalStubProvider(valid_output())

    first = run(create_natural_document(request, profile(), first_provider))
    second = run(create_natural_document(request, profile(), second_provider))

    assert first.model_dump() == second.model_dump()
    assert first.document.title == "Service Agreement"
    assert first.generated_claims[0].field_name == "draft_remedy"
    assert first_provider.calls[0][1]["verified_facts"]["registration_number"] == "HE 123456"


def test_natural_creation_timeout_is_explicit_and_bounded():
    provider = NaturalStubProvider(valid_output(), delay=1)
    with pytest.raises(DocumentAIProviderTimeout, match="timed out after 0.1s"):
        run(
            create_natural_document(
                NaturalDocumentCreationRequest(request="Create a service agreement"),
                profile(),
                provider,
                timeout_seconds=0.01,
            )
        )


def test_natural_creation_provider_failure_is_explicit():
    provider = NaturalStubProvider(error=DocumentAIProviderError("provider unavailable"))
    with pytest.raises(NaturalCreationProviderError, match="provider unavailable"):
        run(
            create_natural_document(
                NaturalDocumentCreationRequest(request="Create a service agreement"),
                profile(),
                provider,
            )
        )


def test_natural_creation_rejects_non_structured_provider_output():
    provider = NaturalStubProvider("unstructured prose")
    with pytest.raises(MalformedDocumentAIResponse, match="structured object"):
        run(
            create_natural_document(
                NaturalDocumentCreationRequest(request="Create a service agreement"),
                profile(),
                provider,
            )
        )


def test_natural_creation_rejects_missing_required_generated_structure():
    output = valid_output()
    del output["content"]
    with pytest.raises(MalformedDocumentAIResponse, match="malformed"):
        run(
            create_natural_document(
                NaturalDocumentCreationRequest(request="Create a service agreement"),
                profile(),
                NaturalStubProvider(output),
            )
        )


def test_verified_source_facts_and_provenance_are_preserved_without_mutation():
    company = profile()
    original = company.model_dump()
    result = run(
        create_natural_document(
            NaturalDocumentCreationRequest(request="Create a service agreement"),
            company,
            NaturalStubProvider(valid_output()),
        )
    )

    assert company.model_dump() == original
    assert result.verified_facts["registration_number"] == "HE 123456"
    assert result.fact_provenance == company.fact_provenance
    assert result.generated_claims[0].origin == "generated"


def test_provider_cannot_promote_unsupported_claim_to_verified():
    output = valid_output()
    output["claims"].append(
        {
            "field_name": "bank_account",
            "value": "Invented account",
            "origin": "verified",
        }
    )
    with pytest.raises(MalformedDocumentAIResponse, match="unsupported claim as verified"):
        run(
            create_natural_document(
                NaturalDocumentCreationRequest(request="Create a service agreement"),
                profile(),
                NaturalStubProvider(output),
            )
        )


def test_explicit_user_fact_stays_separate_from_verified_profile_facts():
    output = valid_output()
    output["claims"].append({"field_name": "amount", "value": "EUR 5,000", "origin": "user"})
    result = run(
        create_natural_document(
            NaturalDocumentCreationRequest(
                request="Create a service agreement. Amount: EUR 5,000."
            ),
            profile(),
            NaturalStubProvider(output),
        )
    )

    assert result.user_supplied_facts == {"amount": "EUR 5,000"}
    assert "amount" not in result.verified_facts
    assert result.document.claims[-1].origin == "user"


def test_mismatched_document_type_and_ambiguous_request_fail_explicitly():
    output = valid_output()
    output["document_type"] = "invoice"
    with pytest.raises(MalformedDocumentAIResponse, match="changed"):
        run(
            create_natural_document(
                NaturalDocumentCreationRequest(request="Create a service agreement"),
                profile(),
                NaturalStubProvider(output),
            )
        )
    with pytest.raises(InvalidNaturalCreationRequest, match="What kind of agreement"):
        run(
            create_natural_document(
                NaturalDocumentCreationRequest(request="Create an agreement"),
                profile(),
                NaturalStubProvider(valid_output()),
            )
        )


def test_natural_creation_uses_only_injected_provider_and_no_network():
    provider = NaturalStubProvider(valid_output())
    result = run(
        create_natural_document(
            NaturalDocumentCreationRequest(request="Create a service agreement"),
            profile(),
            provider,
        )
    )

    assert result.status == "created"
    assert len(provider.calls) == 1


def test_greek_service_agreement_intent_is_classified_as_legal_document():
    interpretation = interpret_natural_document_request(
        "Δημιούργησε σύμβαση παροχής υπηρεσιών και άφησε την αμοιβή κενή.",
        profile(),
    )

    assert interpretation["document_type"] == "service_agreement"
    assert interpretation["category"] == "Legal"
    assert interpretation["intentional_blank_fields"] == ["FEE"]
    assert interpretation["review_status"] == "LEGAL_REVIEW_RECOMMENDED"


def test_greek_invoice_extracts_explicit_amount_without_promoting_it_to_verified():
    interpretation = interpret_natural_document_request(
        "Δημιούργησε τιμολόγιο. Ποσό: EUR 5.000.",
        profile(),
    )

    assert interpretation["document_type"] == "invoice"
    assert interpretation["user_supplied_facts"]["amount"] == "EUR 5.000"


def test_greek_ambiguous_agreement_requires_clarification():
    interpretation = interpret_natural_document_request("Δημιούργησε μια σύμβαση", profile())

    assert interpretation["status"] == "needs_clarification"


def test_greek_official_document_request_is_template_only_without_source():
    interpretation = interpret_natural_document_request(
        "Δημιούργησε επίσημο πιστοποιητικό γέννησης",
        profile(),
    )

    assert interpretation["official_document_safety"] == "template_only"
