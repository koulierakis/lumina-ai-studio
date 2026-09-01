from __future__ import annotations

import asyncio

from document_studio.document_ai_provider import DocumentAIProvider
from document_studio.generation_orchestrator import DocumentAIProviderRegistry
from document_studio.provider_status import collect_document_provider_status


def run(coro):
    return asyncio.run(coro)


class StubProvider(DocumentAIProvider):
    def __init__(self, name: str, status_payload: dict):
        self.name = name
        self._status_payload = status_payload

    async def generate_document(self, request: str, context: dict):
        raise AssertionError("generation must not run during status checks")

    async def status(self):
        return dict(self._status_payload)


def test_provider_status_reports_readiness_without_credentials():
    registry = DocumentAIProviderRegistry(
        {
            "ollama": StubProvider(
                "ollama",
                {
                    "available": True,
                    "ready": True,
                    "selected_document_model": "qwen2.5-coder:7b",
                },
            ),
            "groq": StubProvider(
                "groq",
                {
                    "available": False,
                    "ready": False,
                    "api_key": "must-not-leak",
                    "secret_token": "must-not-leak",
                },
            ),
        }
    )

    result = run(collect_document_provider_status(registry))

    assert result["default_provider"] == "ollama"
    assert result["any_ready"] is True
    assert result["providers"]["ollama"]["selected_document_model"] == "qwen2.5-coder:7b"
    assert "api_key" not in result["providers"]["groq"]
    assert "secret_token" not in result["providers"]["groq"]
