from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from document_studio.document_ai_provider import (
    DocumentAIProvider,
    DocumentAIProviderError,
    DocumentAIProviderTimeout,
    MalformedDocumentAIResponse,
)
from document_studio.models import CompanyProfile, SourceCorporateFact
from document_studio.ollama_adapter import OllamaDocumentAdapter
from document_studio.source_facts import (
    apply_verified_source_facts,
    detect_source_fact_conflicts,
    extract_source_corporate_facts,
)


def run(coro):
    return asyncio.run(coro)


class StubProvider(DocumentAIProvider):
    name = "stub"

    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.requests: list[tuple[str, dict]] = []

    async def generate_document(self, request: str, context: dict):
        self.requests.append((request, context))
        if self.error:
            raise self.error
        return self.response

    async def status(self):
        return {"name": self.name, "available": self.error is None}


def test_provider_contract_supports_valid_response_and_mocking():
    document = SimpleNamespace(intent={"type": "agreement"}, blocks=[{"id": "body"}])
    provider = StubProvider(document)

    assert run(provider.analyze_intent("Create an agreement", {"verified": {}})) == {
        "type": "agreement"
    }
    assert run(provider.regenerate_section("Revise body", {})) == [{"id": "body"}]
    assert provider.requests[0][0] == "Create an agreement"


def test_provider_contract_propagates_explicit_failure_and_timeout():
    failure = StubProvider(error=DocumentAIProviderError("provider failed"))
    timeout = StubProvider(error=DocumentAIProviderTimeout("provider timed out"))

    with pytest.raises(DocumentAIProviderError, match="provider failed"):
        run(failure.revise_document("Revise", {}))
    with pytest.raises(DocumentAIProviderTimeout, match="timed out"):
        run(timeout.analyze_intent("Analyze", {}))


def test_provider_contract_rejects_malformed_response():
    with pytest.raises(MalformedDocumentAIResponse, match="intent"):
        run(StubProvider(SimpleNamespace(blocks=[])).analyze_intent("Analyze", {}))
    with pytest.raises(MalformedDocumentAIResponse, match="blocks must be a list"):
        run(StubProvider(SimpleNamespace(blocks="invalid")).regenerate_section("Revise", {}))


class MockOllamaService:
    def __init__(self, *, response=None, error: Exception | None = None, delay: float = 0):
        self.response = response
        self.error = error
        self.delay = delay
        self.calls = []
        self.closed = False

    async def check_connection(self, *, include_models=True):
        if self.error:
            raise self.error
        return SimpleNamespace(
            available=True,
            base_url="http://127.0.0.1:11434",
            version="test",
            installed_models=[SimpleNamespace(name="qwen2.5-coder:7b")],
            response_time_ms=1,
            error=None,
        )

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.response

    async def close(self):
        self.closed = True


def test_ollama_adapter_has_no_startup_dependency():
    calls = []

    def factory(configuration):
        calls.append(configuration)
        return MockOllamaService()

    adapter = OllamaDocumentAdapter(service_factory=factory)
    assert calls == []
    assert adapter.document_model
    assert calls == []


def test_ollama_adapter_reports_unavailable_service_without_raising():
    adapter = OllamaDocumentAdapter(service=MockOllamaService(error=OSError("offline")))
    status = run(adapter.check_availability())

    assert status["available"] is False
    assert status["ollama_reachable"] is False
    assert status["error"] == "Ollama availability check failed: OSError"


def test_ollama_adapter_returns_valid_mocked_response():
    service = MockOllamaService(
        response=SimpleNamespace(content="<p>Verified document</p>", model="test-model")
    )
    result = run(
        OllamaDocumentAdapter(service=service).generate_document(
            "Use verified facts", timeout_seconds=2
        )
    )

    assert result.success is True
    assert result.content == "<p>Verified document</p>"
    assert result.model_used == "test-model"
    assert service.calls[0]["timeout_seconds"] == 2


def test_ollama_adapter_returns_deterministic_timeout_failure():
    service = MockOllamaService(delay=1)
    result = run(
        OllamaDocumentAdapter(service=service).generate_document(
            "Slow request", timeout_seconds=0.01
        )
    )

    assert result.success is False
    assert result.error == "Generation timed out after 0.1s"


def test_ollama_adapter_rejects_malformed_mocked_response():
    result = run(
        OllamaDocumentAdapter(
            service=MockOllamaService(response={"content": "text"})
        ).generate_structured_document("Return JSON")
    )

    assert result.success is False
    assert result.error == "Malformed Ollama response"


def _fact(
    field_name: str,
    value,
    *,
    status: str = "VERIFIED",
    source_id: str = "source-1",
) -> SourceCorporateFact:
    return SourceCorporateFact(
        field_name=field_name,
        value=value,
        source_document_id=source_id,
        source_document_name=f"{source_id}.pdf",
        source_page_or_location="page 1, line 1",
        confidence=0.99,
        verification_status=status,
    )


def test_source_fact_extraction_preserves_provenance_and_verification_boundary():
    facts = extract_source_corporate_facts(
        "[[LUMINA_PAGE:2]]\nCompany Name: Helios Ltd\nDirector: Elena Markou",
        "source-1",
        "registry.pdf",
    )

    company = next(fact for fact in facts if fact.field_name == "company_name")
    director = next(fact for fact in facts if fact.field_name == "directors")
    assert company.value == "Helios Ltd"
    assert company.verification_status == "VERIFIED"
    assert company.source_page_or_location == "page 2, line 1"
    assert director.verification_status == "CANDIDATE"


def test_source_fact_extraction_ignores_unlabeled_unsupported_claims_and_duplicates():
    facts = extract_source_corporate_facts(
        "Helios Ltd is certainly licensed everywhere.\n"
        "Registration Number: HE 778899\nRegistration Number: HE-778899",
        "source-1",
        "registry.txt",
    )

    assert [(fact.field_name, fact.value) for fact in facts] == [
        ("registration_number", "HE 778899")
    ]


def test_source_fact_conflicts_do_not_overwrite_existing_profile_value():
    profile = CompanyProfile(owner_email="owner@example.com", registration_number="HE 111111")
    updated, conflicts, applied = apply_verified_source_facts(
        profile, [_fact("registration_number", "HE 778899")]
    )

    assert updated.registration_number == "HE 111111"
    assert applied == []
    assert conflicts[0].current_company_profile_value == "HE 111111"


def test_source_fact_application_is_idempotent_and_serializable():
    fact = _fact("registration_number", "HE 778899")
    profile = CompanyProfile(owner_email="owner@example.com", registration_number="")
    first, first_conflicts, first_applied = apply_verified_source_facts(profile, [fact])
    second, second_conflicts, second_applied = apply_verified_source_facts(first, [fact])
    restored = CompanyProfile.model_validate(second.model_dump())

    assert first_conflicts == second_conflicts == []
    assert first_applied == ["registration_number"]
    assert second_applied == []
    assert len(restored.fact_provenance["registration_number"]) == 1


def test_only_supported_verified_facts_are_applied():
    profile = CompanyProfile(owner_email="owner@example.com", company_name="")
    updated, conflicts, applied = apply_verified_source_facts(
        profile,
        [
            _fact("company_name", "Generated Name", status="GENERATED"),
            _fact("unsupported_license_claim", "Licensed everywhere"),
        ],
    )

    assert updated.company_name == ""
    assert updated.fact_provenance == {}
    assert conflicts == []
    assert applied == []


def test_distinct_source_values_are_reported_as_conflicts():
    conflicts = detect_source_fact_conflicts(
        [
            _fact("registration_number", "HE 111111", source_id="source-1"),
            _fact("registration_number", "HE 222222", source_id="source-2"),
        ]
    )

    assert len(conflicts) == 1
    assert len(conflicts[0].conflicting_values) == 2
