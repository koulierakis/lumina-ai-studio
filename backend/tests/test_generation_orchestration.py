from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path

import httpx
import pytest
from document_studio.document_ai_provider import (
    DocumentAIProvider,
    DocumentAIProviderError,
    DocumentAIProviderTimeout,
    MalformedDocumentAIResponse,
)
from document_studio.generation_orchestrator import (
    DEFAULT_PROVIDER,
    DocumentAIProviderRegistry,
    GenerationFallbackError,
    GenerationValidationError,
    OllamaNaturalDocumentProvider,
    UnknownDocumentAIProvider,
    generate_document,
)
from document_studio.groq_provider import (
    GroqDocumentProvider,
    GroqProviderHTTPError,
    GroqProviderUnavailable,
)
from document_studio.models import CompanyProfile, NaturalDocumentCreationRequest
from document_studio.natural_creation import NaturalCreationProviderError


def run(coro):
    return asyncio.run(coro)


def profile() -> CompanyProfile:
    return CompanyProfile(
        owner_email="owner@example.com",
        company_name="Verified Example Ltd",
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


def valid_document_payload() -> dict:
    return {
        "title": "Service Agreement",
        "document_type": "service_agreement",
        "category": "Legal",
        "language": "en",
        "content": (
            "Verified Example Ltd, registration number HE 123456, will provide "
            "[SERVICE DESCRIPTION]."
        ),
        "claims": [
            {
                "field_name": "company_name",
                "value": "Verified Example Ltd",
                "origin": "verified",
            },
            {
                "field_name": "registration_number",
                "value": "HE 123456",
                "origin": "verified",
            },
            {
                "field_name": "draft_obligation",
                "value": "Perform the agreed services",
                "origin": "generated",
            },
        ],
        "unresolved_fields": ["SERVICE DESCRIPTION"],
    }


def groq_envelope(payload: dict | None = None) -> dict:
    return {
        "id": "completion-1",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps(payload or valid_document_payload()),
                }
            }
        ],
    }


def mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_groq_configured_and_unconfigured_state_is_lazy(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    unconfigured = GroqDocumentProvider()
    assert run(unconfigured.status()) == {
        "name": "groq",
        "configured": False,
        "available": False,
        "model": "openai/gpt-oss-120b",
        "network_checked": False,
        "error": "Groq is not configured",
    }
    with pytest.raises(GroqProviderUnavailable, match="not configured"):
        run(unconfigured.generate_document("Create", {}))

    configured = GroqDocumentProvider(api_key="server-only-key")
    status = run(configured.status())
    assert status["configured"] is True
    assert "server-only-key" not in str(status)


def test_groq_import_and_construction_make_no_network_request():
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(200, json=groq_envelope())

    client = mock_client(handler)
    GroqDocumentProvider(api_key="key", client=client)
    assert calls == []
    run(client.aclose())


def test_groq_successful_mocked_request_is_strict_and_credential_safe():
    captured = {}

    async def handler(request):
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=groq_envelope())

    client = mock_client(handler)
    provider = GroqDocumentProvider(api_key="private-key", client=client, max_attempts=1)
    result = run(provider.generate_document("Create a service agreement", {}))

    assert result.document_type == "service_agreement"
    assert captured["authorization"] == "Bearer private-key"
    assert captured["payload"]["response_format"]["type"] == "json_schema"
    assert "private-key" not in str(result.model_dump())
    run(client.aclose())


def test_groq_timeout_and_connection_failure_are_sanitized():
    async def slow_handler(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json=groq_envelope())

    slow_client = mock_client(slow_handler)
    timeout_provider = GroqDocumentProvider(
        api_key="secret-timeout",
        client=slow_client,
        max_attempts=1,
        overall_timeout_seconds=0.1,
    )
    with pytest.raises(DocumentAIProviderTimeout) as timeout_error:
        run(timeout_provider.generate_document("Create", {}))
    assert "secret-timeout" not in str(timeout_error.value)
    run(slow_client.aclose())

    async def connection_handler(request):
        raise httpx.ConnectError("internal host secret", request=request)

    connection_client = mock_client(connection_handler)
    connection_provider = GroqDocumentProvider(
        api_key="secret-connect", client=connection_client, max_attempts=1
    )
    with pytest.raises(GroqProviderUnavailable, match="unavailable") as connection_error:
        run(connection_provider.generate_document("Create", {}))
    assert "secret-connect" not in str(connection_error.value)
    assert "internal host" not in str(connection_error.value)
    run(connection_client.aclose())


@pytest.mark.parametrize(
    ("status_code", "message", "retryable"),
    [
        (400, "rejected", False),
        (401, "authentication failed", False),
        (403, "access was denied", False),
        (429, "rate limit", True),
        (500, "service failed", True),
    ],
)
def test_groq_http_failures_are_explicit_and_sanitized(status_code, message, retryable):
    async def handler(request):
        return httpx.Response(
            status_code,
            json={"error": {"message": "raw private provider details"}},
            headers={"Retry-After": "0"},
        )

    client = mock_client(handler)
    provider = GroqDocumentProvider(api_key="secret-http", client=client, max_attempts=1)
    with pytest.raises(GroqProviderHTTPError) as captured:
        run(provider.generate_document("Create", {}))

    assert captured.value.status_code == status_code
    assert captured.value.retryable is retryable
    assert message in str(captured.value)
    assert "secret-http" not in str(captured.value)
    assert "raw private" not in str(captured.value)
    run(client.aclose())


def test_groq_transient_retry_is_bounded_and_can_succeed():
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(200, json=groq_envelope())

    async def no_sleep(delay):
        return None

    client = mock_client(handler)
    provider = GroqDocumentProvider(api_key="key", client=client, max_attempts=2, sleeper=no_sleep)
    result = run(provider.generate_document("Create", {}))
    assert result.title == "Service Agreement"
    assert calls == 2
    run(client.aclose())


def test_groq_overall_deadline_bounds_retries():
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.07)
        return httpx.Response(503, json={"error": "temporary"})

    client = mock_client(handler)
    provider = GroqDocumentProvider(
        api_key="key",
        client=client,
        max_attempts=4,
        overall_timeout_seconds=0.1,
    )
    started = asyncio.get_event_loop_policy().new_event_loop().time()
    with pytest.raises(DocumentAIProviderTimeout, match="overall deadline"):
        run(provider.generate_document("Create", {}))
    elapsed = asyncio.get_event_loop_policy().new_event_loop().time() - started
    assert elapsed < 0.5
    assert calls == 1
    run(client.aclose())


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(200, text="not-json"), "malformed JSON"),
        (httpx.Response(200, json={"choices": []}), "invalid response envelope"),
        (
            httpx.Response(
                200,
                json={"choices": [{"message": {"content": "not-json"}}]},
            ),
            "malformed structured content",
        ),
        (
            httpx.Response(
                200,
                json={"choices": [{"message": {"content": json.dumps({"title": "Only"})}}]},
            ),
            "invalid typed document output",
        ),
    ],
)
def test_groq_rejects_malformed_json_envelope_and_typed_output(response, message):
    async def handler(request):
        return response

    client = mock_client(handler)
    provider = GroqDocumentProvider(api_key="key", client=client, max_attempts=1)
    with pytest.raises(MalformedDocumentAIResponse, match=message):
        run(provider.generate_document("Create", {}))
    run(client.aclose())


class StubProvider(DocumentAIProvider):
    def __init__(self, name: str, output=None, error: Exception | None = None):
        self.name = name
        self.output = output or valid_document_payload()
        self.error = error
        self.calls = 0

    async def generate_document(self, request: str, context: dict):
        self.calls += 1
        if self.error:
            raise self.error
        return self.output

    async def status(self):
        return {"name": self.name, "available": self.error is None}


def request() -> NaturalDocumentCreationRequest:
    return NaturalDocumentCreationRequest(request="Create a service agreement")


def test_provider_registry_is_allowlisted_and_default_is_deterministic():
    ollama = StubProvider("ollama")
    groq = StubProvider("groq")
    registry = DocumentAIProviderRegistry({"ollama": ollama, "groq": groq})

    assert DEFAULT_PROVIDER == "ollama"
    assert registry.get() is ollama
    assert registry.get("ollama") is ollama
    assert registry.get("groq") is groq
    assert isinstance(DocumentAIProviderRegistry().get("ollama"), OllamaNaturalDocumentProvider)
    assert isinstance(DocumentAIProviderRegistry().get("groq"), GroqDocumentProvider)
    with pytest.raises(UnknownDocumentAIProvider, match="unknown"):
        registry.get("unknown")


def test_fallback_disabled_preserves_selected_provider_failure():
    primary = StubProvider("groq", error=GroqProviderUnavailable("unavailable"))
    fallback = StubProvider("ollama")
    registry = DocumentAIProviderRegistry({"groq": primary, "ollama": fallback})

    with pytest.raises(NaturalCreationProviderError, match="unavailable"):
        run(generate_document(request(), profile(), provider_name="groq", registry=registry))
    assert primary.calls == 1
    assert fallback.calls == 0


def test_explicit_eligible_fallback_is_successful_and_observable():
    primary = StubProvider("groq", error=GroqProviderUnavailable("unavailable"))
    fallback = StubProvider("ollama")
    registry = DocumentAIProviderRegistry({"groq": primary, "ollama": fallback})

    result = run(
        generate_document(
            request(),
            profile(),
            provider_name="groq",
            fallback_provider_name="ollama",
            registry=registry,
        )
    )
    assert result.metadata.fallback_used is True
    assert result.metadata.fallback_from == "groq"
    assert result.metadata.provider_used == "ollama"
    assert result.metadata.attempt_count == 2


def test_failed_fallback_is_explicit_and_sanitized():
    primary = StubProvider("groq", error=GroqProviderUnavailable("primary details"))
    fallback = StubProvider("ollama", error=DocumentAIProviderError("fallback details"))
    registry = DocumentAIProviderRegistry({"groq": primary, "ollama": fallback})

    with pytest.raises(GenerationFallbackError, match="ollama.*failed") as captured:
        run(
            generate_document(
                request(),
                profile(),
                provider_name="groq",
                fallback_provider_name="ollama",
                registry=registry,
            )
        )
    assert "primary details" not in str(captured.value)
    assert "fallback details" not in str(captured.value)


def test_schema_or_fact_failure_never_silently_falls_back():
    unsafe = valid_document_payload()
    unsafe["claims"].append(
        {"field_name": "bank_account", "value": "Invented Account", "origin": "generated"}
    )
    primary = StubProvider("groq", output=unsafe)
    fallback = StubProvider("ollama")
    registry = DocumentAIProviderRegistry({"groq": primary, "ollama": fallback})

    with pytest.raises(GenerationValidationError, match="unsupported"):
        run(
            generate_document(
                request(),
                profile(),
                provider_name="groq",
                fallback_provider_name="ollama",
                registry=registry,
            )
        )
    assert fallback.calls == 0


def test_malformed_provider_response_never_silently_falls_back():
    primary = StubProvider("groq", error=MalformedDocumentAIResponse("malformed provider response"))
    fallback = StubProvider("ollama")
    registry = DocumentAIProviderRegistry({"groq": primary, "ollama": fallback})

    with pytest.raises(NaturalCreationProviderError, match="malformed provider response"):
        run(
            generate_document(
                request(),
                profile(),
                provider_name="groq",
                fallback_provider_name="ollama",
                registry=registry,
            )
        )
    assert fallback.calls == 0


def test_typed_result_preserves_facts_provenance_placeholders_and_metrics():
    provider = StubProvider("groq")
    registry = DocumentAIProviderRegistry({"groq": provider})
    company = profile()
    original = company.model_dump()

    first = run(generate_document(request(), company, provider_name="groq", registry=registry))
    second = run(generate_document(request(), company, provider_name="groq", registry=registry))

    assert company.model_dump() == original
    assert first.generation.fact_provenance == company.fact_provenance
    assert first.generation.generated_claims[0].origin == "generated"
    assert first.metadata.generated_claim_count == 1
    assert first.metadata.unsupported_claim_count == 0
    assert first.metadata.placeholder_status["found"] == ["SERVICE_DESCRIPTION"]
    assert first.metadata.verified_fact_coverage == second.metadata.verified_fact_coverage
    assert first.metadata.verified_fact_coverage["covered"] == [
        "company_name",
        "registration_number",
    ]
    assert "private" not in str(first.model_dump()).casefold()


def test_provider_cannot_promote_unsupported_claim_to_verified():
    unsafe = valid_document_payload()
    unsafe["claims"].append(
        {"field_name": "licence", "value": "Invented Licence", "origin": "verified"}
    )
    registry = DocumentAIProviderRegistry({"groq": StubProvider("groq", output=unsafe)})

    with pytest.raises(MalformedDocumentAIResponse, match="unsupported claim as verified"):
        run(generate_document(request(), profile(), provider_name="groq", registry=registry))


@pytest.mark.parametrize(
    "content",
    [
        "Verified Example Ltd will pay EUR 9,999,999 for the services.",
        "Verified Example Ltd is licensed by the Global Banking Regulator.",
        "The expected account activity is monthly international transfers.",
    ],
)
def test_unsupported_high_risk_text_claim_is_rejected(content):
    unsafe = valid_document_payload()
    unsafe["content"] = content + " [SERVICE DESCRIPTION]"
    registry = DocumentAIProviderRegistry({"groq": StubProvider("groq", output=unsafe)})
    with pytest.raises(GenerationValidationError, match="unsupported"):
        run(generate_document(request(), profile(), provider_name="groq", registry=registry))


def test_placeholder_invention_or_omission_is_rejected():
    missing = valid_document_payload()
    missing["content"] = "Verified Example Ltd will provide invented consulting services."
    registry = DocumentAIProviderRegistry({"groq": StubProvider("groq", output=missing)})
    with pytest.raises(GenerationValidationError, match="placeholder"):
        run(generate_document(request(), profile(), provider_name="groq", registry=registry))

    undeclared = valid_document_payload()
    undeclared["content"] += " Signed on [DATE]."
    registry = DocumentAIProviderRegistry({"groq": StubProvider("groq", output=undeclared)})
    with pytest.raises(GenerationValidationError, match="placeholder"):
        run(generate_document(request(), profile(), provider_name="groq", registry=registry))


def test_orchestrator_has_no_route_or_persistence_imports():
    source = Path("backend/document_studio/generation_orchestrator.py").read_text(encoding="utf-8")
    imports = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any("router" in value for value in imports)
    assert not any("persistence" in value for value in imports)
