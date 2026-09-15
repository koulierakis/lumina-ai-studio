from __future__ import annotations

import asyncio
import importlib

import pytest
from auth import issue_token
from document_studio.document_ai_provider import (
    DocumentAIProvider,
    DocumentAIProviderError,
    DocumentAIProviderTimeout,
)
from document_studio.generation_orchestrator import DocumentAIProviderRegistry
from document_studio.models import CompanyProfile
from document_studio.natural_creation import NaturalProviderOutput
from fastapi import FastAPI
from fastapi.testclient import TestClient
from persistence import SQLitePersistenceProvider

document_router = importlib.import_module("document_studio.router")


def run(coro):
    return asyncio.run(coro)


class RouteProvider(DocumentAIProvider):
    name = "ollama"

    def __init__(
        self,
        failure: Exception | None = None,
        *,
        unsupported: bool = False,
        malformed: bool = False,
        fail_type: str | None = None,
    ) -> None:
        self.failure = failure
        self.unsupported = unsupported
        self.malformed = malformed
        self.fail_type = fail_type
        self.calls: list[str] = []

    async def status(self):
        return {"name": self.name, "configured": True}

    async def generate_document(self, request: str, context: dict):
        self.calls.append(context["document_type"])
        if self.failure or context["document_type"] == self.fail_type:
            raise self.failure or DocumentAIProviderError("sensitive provider detail")
        if self.malformed:
            return {"title": "Incomplete"}
        content = f"Draft for {context['verified_facts'].get('company_name', 'company')}"
        claims = []
        if self.unsupported:
            claims.append(
                {
                    "field_name": "registration_number",
                    "value": "INVENTED-999",
                    "origin": "generated",
                }
            )
        for field in context["intentional_blank_fields"]:
            content += f" [{field}]"
        return NaturalProviderOutput(
            title=context["document_title"],
            document_type=context["document_type"],
            category=context["category"],
            language=context["language"],
            content=content,
            claims=claims,
            unresolved_fields=context["intentional_blank_fields"],
        )


@pytest.fixture
def api(tmp_path, monkeypatch):
    owner = "owner@example.com"
    monkeypatch.setenv("JWT_SECRET", "phase-5-test-" + ("x" * 32))
    monkeypatch.setenv("OWNER_EMAIL", owner)
    monkeypatch.setenv("LUMINA_LOCAL_PASSWORDLESS", "0")
    provider = SQLitePersistenceProvider(tmp_path / "phase-5-router.db")
    run(provider.initialize())
    document_router.configure_document_studio_router(provider, None, None)
    profile = CompanyProfile(
        id="owner-profile",
        owner_email=owner,
        company_name="Verified Owner Ltd",
        legal_form="Ltd",
        jurisdiction="Cyprus",
        registration_number="REG-123",
        registered_office="1 Verified Street",
        fact_provenance={
            "registration_number": [
                {"source_document_id": "source-1", "verification_status": "VERIFIED"}
            ]
        },
    )
    foreign = CompanyProfile(
        id="foreign-profile",
        owner_email="other@example.com",
        company_name="Other Owner Ltd",
    )
    run(document_router.profiles_coll.insert_one(profile.model_dump()))
    run(document_router.profiles_coll.insert_one(foreign.model_dump()))
    app = FastAPI()
    app.include_router(document_router.router)
    client = TestClient(app, base_url="http://testserver")
    headers = {"Authorization": f"Bearer {issue_token(owner)}"}
    return client, headers


def use_registry(monkeypatch, **providers):
    registry = DocumentAIProviderRegistry(providers)
    monkeypatch.setattr(document_router, "_ai_provider_registry", lambda: registry)
    return registry


def counts():
    return {
        "profiles": run(document_router.profiles_coll.count_documents({})),
        "documents": run(document_router.documents_coll.count_documents({})),
        "versions": run(document_router.versions_coll.count_documents({})),
    }


def test_pack_advisor_api_is_authenticated_deterministic_and_non_persistent(api):
    client, headers = api
    before = counts()
    payload = {"objective": "Open a corporate bank account", "company_profile_id": "owner-profile"}
    first = client.post("/api/documents/pack-advisor", json=payload, headers=headers)
    second = client.post("/api/documents/pack-advisor", json=payload, headers=headers)
    assert first.status_code == 200
    assert first.json() == second.json()
    assert first.json()["profile_validation"]["required_total"] > 0
    assert counts() == before


def test_pack_advisor_rejects_invalid_input(api):
    client, headers = api
    response = client.post("/api/documents/pack-advisor", json={}, headers=headers)
    assert response.status_code == 422
    empty = client.post("/api/documents/pack-advisor", json={"objective": "   "}, headers=headers)
    assert empty.status_code == 400


def test_new_routes_require_authentication(api):
    client, _ = api
    response = client.post("/api/documents/pack-advisor", json={"objective": "Bank onboarding"})
    assert response.status_code == 401


def test_owner_profile_isolation_and_owner_spoofing(api, monkeypatch):
    client, headers = api
    use_registry(monkeypatch, ollama=RouteProvider())
    denied = client.post(
        "/api/documents/pack-advisor",
        json={"objective": "Bank onboarding", "company_profile_id": "foreign-profile"},
        headers=headers,
    )
    assert denied.status_code == 404
    spoofed = client.post(
        "/api/documents/natural-create/preview",
        json={
            "request": "Create a consulting agreement",
            "requested_type": "consulting_agreement",
            "company_profile_id": "owner-profile",
            "owner_email": "other@example.com",
            "provider": "ollama",
        },
        headers=headers,
    )
    assert spoofed.status_code == 200
    assert spoofed.json()["verified_facts"]["company_name"] == "Verified Owner Ltd"


def test_natural_creation_success_and_no_persistence(api, monkeypatch):
    client, headers = api
    provider = RouteProvider()
    use_registry(monkeypatch, ollama=provider)
    before = counts()
    response = client.post(
        "/api/documents/natural-create/preview",
        json={
            "request": "Create a consulting agreement",
            "requested_type": "consulting_agreement",
            "company_profile_id": "owner-profile",
            "provider": "ollama",
        },
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["document"]["document_type"] == "consulting_agreement"
    assert response.json()["fact_provenance"]["registration_number"]
    assert provider.calls == ["consulting_agreement"]
    assert counts() == before


@pytest.mark.parametrize(
    ("provider", "status"),
    [
        (RouteProvider(DocumentAIProviderError("api-key-secret")), 503),
        (RouteProvider(DocumentAIProviderTimeout("api-key-secret")), 504),
        (RouteProvider(malformed=True), 502),
        (RouteProvider(unsupported=True), 422),
    ],
)
def test_natural_creation_errors_are_sanitized(api, monkeypatch, provider, status):
    client, headers = api
    use_registry(monkeypatch, ollama=provider)
    response = client.post(
        "/api/documents/natural-create/preview",
        json={
            "request": "Create a consulting agreement",
            "requested_type": "consulting_agreement",
            "company_profile_id": "owner-profile",
            "provider": "ollama",
        },
        headers=headers,
    )
    assert response.status_code == status
    assert "api-key-secret" not in response.text
    assert "sensitive provider detail" not in response.text


def test_natural_creation_rejects_unknown_provider(api):
    client, headers = api
    response = client.post(
        "/api/documents/natural-create/preview",
        json={"request": "Create an NDA", "requested_type": "nda", "provider": "evil"},
        headers=headers,
    )
    assert response.status_code == 400
    assert "not supported" in response.json()["detail"]


def test_ai_generation_valid_type_provider_placeholder_and_no_persistence(api, monkeypatch):
    client, headers = api
    use_registry(monkeypatch, ollama=RouteProvider())
    before = counts()
    response = client.post(
        "/api/documents/generate-ai/preview",
        json={
            "objective": "Create a consulting agreement and leave client details blank",
            "document_type": "consulting_agreement",
            "company_profile_id": "owner-profile",
            "provider": "ollama",
        },
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["document"]["document_type"] == "consulting_agreement"
    assert "[CLIENT DETAILS]" in data["document"]["content_text"]
    assert data["generation"]["metadata"]["provider_used"] == "ollama"
    assert data["persisted"] is False
    assert counts() == before


def test_ai_generation_rejects_type_provider_and_disabled_fallback(api, monkeypatch):
    client, headers = api
    use_registry(monkeypatch, ollama=RouteProvider())
    unsupported = client.post(
        "/api/documents/generate-ai/preview",
        json={"objective": "Draft", "document_type": "obsolete"},
        headers=headers,
    )
    invalid_provider = client.post(
        "/api/documents/generate-ai/preview",
        json={"objective": "Draft", "document_type": "nda", "provider": "evil"},
        headers=headers,
    )
    disabled = client.post(
        "/api/documents/generate-ai/preview",
        json={
            "objective": "Draft",
            "document_type": "nda",
            "fallback_provider": "groq",
            "allow_fallback": False,
        },
        headers=headers,
    )
    assert unsupported.status_code == 422
    assert invalid_provider.status_code == 400
    assert disabled.status_code == 400


def test_ai_generation_explicit_fallback_is_observable(api, monkeypatch):
    client, headers = api
    use_registry(
        monkeypatch,
        ollama=RouteProvider(DocumentAIProviderTimeout("primary timeout")),
        groq=RouteProvider(),
    )
    response = client.post(
        "/api/documents/generate-ai/preview",
        json={
            "objective": "Create an NDA",
            "document_type": "nda",
            "provider": "ollama",
            "fallback_provider": "groq",
            "allow_fallback": True,
        },
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["generation"]["metadata"]["fallback_used"] is True
    assert response.json()["generation"]["metadata"]["provider_used"] == "groq"


def test_ai_generation_rejects_high_risk_claim(api, monkeypatch):
    client, headers = api
    use_registry(monkeypatch, ollama=RouteProvider(unsupported=True))
    response = client.post(
        "/api/documents/generate-ai/preview",
        json={"objective": "Create an NDA", "document_type": "nda", "provider": "ollama"},
        headers=headers,
    )
    assert response.status_code == 422


def test_pack_preview_order_duplicates_and_no_persistence(api, monkeypatch):
    client, headers = api
    use_registry(monkeypatch, ollama=RouteProvider())
    before = counts()
    response = client.post(
        "/api/documents/generate-pack/preview",
        json={
            "objective": "Prepare agreements",
            "selected_document_types": ["nda", "consulting_agreement", "nda"],
            "provider": "ollama",
        },
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert [item["document_type"] for item in data["items"]] == [
        "nda",
        "consulting_agreement",
        "nda",
    ]
    assert [item["status"] for item in data["items"]] == [
        "generated",
        "generated",
        "skipped",
    ]
    assert counts() == before


def test_pack_preview_rejects_invalid_type(api, monkeypatch):
    client, headers = api
    use_registry(monkeypatch, ollama=RouteProvider())
    response = client.post(
        "/api/documents/generate-pack/preview",
        json={"objective": "Pack", "selected_document_types": ["invalid"]},
        headers=headers,
    )
    assert response.status_code == 422


def test_pack_preview_rejects_unknown_provider(api, monkeypatch):
    client, headers = api
    use_registry(monkeypatch, ollama=RouteProvider())
    response = client.post(
        "/api/documents/generate-pack/preview",
        json={
            "objective": "Pack",
            "selected_document_types": ["nda"],
            "provider": "arbitrary",
        },
        headers=headers,
    )
    assert response.status_code == 400


def test_pack_preview_reports_partial_failure(api, monkeypatch):
    client, headers = api
    use_registry(monkeypatch, ollama=RouteProvider(fail_type="nda"))
    response = client.post(
        "/api/documents/generate-pack/preview",
        json={
            "objective": "Prepare agreements",
            "selected_document_types": ["nda", "consulting_agreement"],
            "provider": "ollama",
        },
        headers=headers,
    )
    assert response.status_code == 200
    assert [item["status"] for item in response.json()["items"]] == [
        "failed",
        "generated",
    ]
    assert response.json()["overall_status"] == "partial_failure"


def test_legacy_templates_route_contract_is_unchanged(api):
    client, headers = api
    response = client.get("/api/documents/templates", headers=headers)
    assert response.status_code == 200
    assert {"templates", "document_types", "export_formats"}.issubset(response.json())
