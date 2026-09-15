from __future__ import annotations

import asyncio
import functools
import inspect

import pytest
from document_studio.document_ai_provider import (
    DocumentAIProvider,
    DocumentAIProviderError,
    DocumentAIProviderTimeout,
)
from document_studio.generation_orchestrator import DocumentAIProviderRegistry
from document_studio.models import (
    CompanyProfile,
    CorporateDocument,
    NaturalDocumentCreationRequest,
    PackAdvisorRequest,
    PackGenerationRequest,
)
from document_studio.natural_creation import NaturalProviderOutput
from document_studio.service import (
    DOCUMENT_CLASS_DEFINITIONS,
    AIFactIntegrityViolation,
    AIProviderTimedOut,
    AIProviderUnavailable,
    InvalidAIProvider,
    InvalidAIServiceRequest,
    MalformedAIGeneration,
    UnsupportedAIDocumentType,
    advise_document_pack,
    classify_document_request,
    create_natural_document_preview,
    generate_ai_document_preview,
    generate_document_pack_preview,
)


def async_test(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapped


class StubProvider(DocumentAIProvider):
    name = "ollama"

    def __init__(self, failure: Exception | None = None, *, unsupported: bool = False):
        self.failure = failure
        self.unsupported = unsupported
        self.calls: list[tuple[str, dict]] = []

    async def status(self):
        return {"name": self.name, "configured": True}

    async def generate_document(self, request: str, context: dict):
        self.calls.append((request, context))
        if self.failure:
            raise self.failure
        claims = []
        content = f"Draft for {context['verified_facts'].get('company_name', 'company')}"
        if self.unsupported:
            claims = [
                {"field_name": "registration_number", "value": "FAKE-999", "origin": "generated"}
            ]
        for placeholder in context["intentional_blank_fields"]:
            content += f" [{placeholder}]"
        return NaturalProviderOutput(
            title=context["document_title"],
            document_type=context["document_type"],
            category=context["category"],
            language=context["language"],
            content=content,
            claims=claims,
            unresolved_fields=context["intentional_blank_fields"],
        )


def profile(**changes) -> CompanyProfile:
    values = {
        "owner_email": "owner@example.com",
        "company_name": "Verified Holdings Ltd",
        "registration_number": "REG-123",
        "jurisdiction": "Cyprus",
        "legal_form": "Ltd",
        "registered_office": "1 Verified Street",
        "fact_provenance": {
            "registration_number": [{"source_document_id": "source-1", "status": "VERIFIED"}]
        },
    }
    values.update(changes)
    return CompanyProfile(**values)


def registry(provider: DocumentAIProvider) -> DocumentAIProviderRegistry:
    return DocumentAIProviderRegistry({"ollama": provider})


def request(
    document_type: str = "consulting_agreement", text: str = "Create a consulting agreement"
):
    return NaturalDocumentCreationRequest(
        request=text, requested_type=document_type, allow_fallback=False
    )


def test_legacy_service_registry_and_classifier_are_unchanged():
    assert "consulting_agreement" in DOCUMENT_CLASS_DEFINITIONS
    assert classify_document_request("Create an NDA")["key"] == "nda"


def test_pack_advisor_service_handles_minimal_and_rich_profiles_without_persistence():
    body = PackAdvisorRequest(objective="Open a corporate bank account")
    minimal = advise_document_pack(body, profile(company_name="", registration_number=""))
    rich = advise_document_pack(body, profile(business_activities="Consulting", aml_controls="CDD"))
    assert minimal.profile_validation["overall_missing"]
    assert len(rich.recommendations) == len({item.document_type for item in rich.recommendations})
    assert all(item.document_type in DOCUMENT_CLASS_DEFINITIONS for item in rich.recommendations)


@async_test
async def test_natural_creation_service_returns_typed_fact_safe_preview():
    provider = StubProvider()
    result = await create_natural_document_preview(request(), profile(), provider)
    assert result.verified_facts["registration_number"] == "REG-123"
    assert result.fact_provenance["registration_number"][0]["source_document_id"] == "source-1"
    assert provider.calls


@async_test
async def test_natural_creation_service_translates_timeout():
    with pytest.raises(AIProviderTimedOut, match="timed out"):
        await create_natural_document_preview(
            request(), profile(), StubProvider(DocumentAIProviderTimeout("secret details"))
        )


@async_test
async def test_natural_creation_service_translates_provider_failure_without_leakage():
    with pytest.raises(AIProviderUnavailable) as raised:
        await create_natural_document_preview(
            request(), profile(), StubProvider(DocumentAIProviderError("api-key-secret"))
        )
    assert "api-key-secret" not in str(raised.value)


@async_test
async def test_natural_creation_service_rejects_malformed_output():
    class MalformedProvider(StubProvider):
        async def generate_document(self, request: str, context: dict):
            return {"title": "missing required structure"}

    with pytest.raises(MalformedAIGeneration):
        await create_natural_document_preview(request(), profile(), MalformedProvider())


@async_test
async def test_ai_generation_adapts_to_canonical_document_and_preserves_provenance():
    result = await generate_ai_document_preview(
        request(), profile(), registry=registry(StubProvider())
    )
    assert isinstance(result.document, CorporateDocument)
    assert result.persisted is False
    assert result.document.owner_email == "owner@example.com"
    assert result.document.document_type == "consulting_agreement"
    assert (
        result.document.metadata["ai_fact_context"]["fact_provenance"] == profile().fact_provenance
    )
    assert result.generation.metadata.provider_used == "ollama"


@async_test
async def test_ai_generation_preserves_existing_document_identity_and_layout_state():
    existing = CorporateDocument(
        id="stable-id",
        owner_email="owner@example.com",
        title="Old",
        document_type="consulting_agreement",
        design={"columns": 2},
        version_number=7,
    )
    result = await generate_ai_document_preview(
        request(), profile(), registry=registry(StubProvider()), existing_document=existing
    )
    assert result.document.id == "stable-id"
    assert result.document.design == {"columns": 2}
    assert result.document.version_number == 7


@async_test
async def test_ai_generation_rejects_invalid_provider_and_document_type():
    with pytest.raises(InvalidAIProvider, match="not supported"):
        await generate_ai_document_preview(request(), profile(), provider_name="arbitrary")
    with pytest.raises(UnsupportedAIDocumentType):
        await generate_ai_document_preview(request("obsolete_type"), profile())


@async_test
async def test_ai_generation_rejects_unsupported_high_risk_claim():
    with pytest.raises(AIFactIntegrityViolation):
        await generate_ai_document_preview(
            request(), profile(), registry=registry(StubProvider(unsupported=True))
        )


@async_test
async def test_ai_generation_preserves_intentional_placeholder():
    body = request(text="Create a consulting agreement and leave client details blank")
    result = await generate_ai_document_preview(body, profile(), registry=registry(StubProvider()))
    assert "[CLIENT DETAILS]" in result.document.content_text
    assert result.generation.metadata.placeholder_status["valid"] is True


@async_test
async def test_ai_generation_requires_explicit_type_and_explicit_fallback_policy():
    with pytest.raises(InvalidAIServiceRequest, match="explicit canonical"):
        await generate_ai_document_preview(
            NaturalDocumentCreationRequest(request="Write something"), profile()
        )
    with pytest.raises(InvalidAIServiceRequest, match="disabled"):
        await generate_ai_document_preview(request(), profile(), fallback_provider_name="groq")


@async_test
async def test_pack_generation_is_ordered_and_reports_duplicates_without_persistence():
    result = await generate_document_pack_preview(
        PackGenerationRequest(
            objective="Prepare transaction documents",
            selected_document_types=["nda", "consulting_agreement", "nda"],
        ),
        profile(),
        registry=registry(StubProvider()),
    )
    assert [item.document_type for item in result.items] == [
        "nda",
        "consulting_agreement",
        "nda",
    ]
    assert [item.status for item in result.items] == ["generated", "generated", "skipped"]
    assert result.overall_status == "complete"
    assert result.persisted is False


@async_test
async def test_pack_generation_rejects_invalid_or_implicit_type_selection():
    with pytest.raises(UnsupportedAIDocumentType):
        await generate_document_pack_preview(
            PackGenerationRequest(objective="Pack", selected_document_types=["bad"]), profile()
        )
    with pytest.raises(InvalidAIServiceRequest, match="Explicit selected"):
        await generate_document_pack_preview(
            PackGenerationRequest(objective="Pack", generate_all=True), profile()
        )


@async_test
async def test_pack_generation_reports_one_document_failure_and_no_silent_success():
    class SelectiveProvider(StubProvider):
        async def generate_document(self, request: str, context: dict):
            if context["document_type"] == "nda":
                raise DocumentAIProviderError("provider detail")
            return await super().generate_document(request, context)

    result = await generate_document_pack_preview(
        PackGenerationRequest(
            objective="Prepare agreements",
            selected_document_types=["nda", "consulting_agreement"],
        ),
        profile(),
        registry=registry(SelectiveProvider()),
    )
    assert [item.status for item in result.items] == ["failed", "generated"]
    assert result.overall_status == "partial_failure"
    assert result.failed_count == 1
    assert result.items[0].error_message == "The document AI provider is unavailable"


def test_service_ai_boundary_has_no_route_or_persistence_dependencies():
    import document_studio.service as service

    source = inspect.getsource(service)
    assert "document_studio.router" not in source
    assert "from .router" not in source
    assert "database" not in inspect.getsource(generate_ai_document_preview).casefold()
    assert "persist" not in inspect.getsource(advise_document_pack).casefold()
