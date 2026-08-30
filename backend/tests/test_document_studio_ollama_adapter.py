from __future__ import annotations

import asyncio

import httpx
from document_studio.ollama_adapter import OllamaDocumentAdapter


def run(coro):
    return asyncio.run(coro)


def test_structured_model_defaults_to_document_model(monkeypatch):
    monkeypatch.setenv("OLLAMA_DOCUMENT_MODEL", "qwen2.5-coder:7b")
    monkeypatch.delenv("OLLAMA_STRUCTURED_DOCUMENT_MODEL", raising=False)

    adapter = OllamaDocumentAdapter()

    assert adapter.document_model == "qwen2.5-coder:7b"
    assert adapter.structured_document_model == "qwen2.5-coder:7b"


def test_structured_model_can_be_overridden(monkeypatch):
    monkeypatch.setenv("OLLAMA_DOCUMENT_MODEL", "qwen2.5-coder:7b")
    monkeypatch.setenv("OLLAMA_STRUCTURED_DOCUMENT_MODEL", "qwen2.5:7b")

    adapter = OllamaDocumentAdapter()

    assert adapter.structured_document_model == "qwen2.5:7b"


def test_availability_reports_models_and_readiness(monkeypatch):
    monkeypatch.setenv("OLLAMA_DOCUMENT_MODEL", "qwen2.5-coder:7b")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"version": "0.11.0"}
            if request.url.path == "/api/version"
            else {"models": [{"name": "qwen2.5-coder:7b"}]},
        )
    )
    client = httpx.AsyncClient(base_url="http://ollama.test", transport=transport)
    adapter = OllamaDocumentAdapter(client=client, ollama_url="http://ollama.test")

    try:
        status = run(adapter.check_availability())
    finally:
        run(client.aclose())

    assert status["available"] is True
    assert status["ready"] is True
    assert status["model_installed"] is True
    assert status["structured_model_installed"] is True
    assert status["installed_models"] == ["qwen2.5-coder:7b"]


def test_generation_uses_native_ollama_api(monkeypatch):
    monkeypatch.setenv("OLLAMA_DOCUMENT_MODEL", "qwen2.5-coder:7b")
    captured = {}

    def handler(request):
        captured.update(request.read() and __import__("json").loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={"model": "qwen2.5-coder:7b", "response": "Document draft"},
        )

    client = httpx.AsyncClient(
        base_url="http://ollama.test", transport=httpx.MockTransport(handler)
    )
    adapter = OllamaDocumentAdapter(client=client, ollama_url="http://ollama.test")

    try:
        result = run(adapter.generate_document("Create an NDA"))
    finally:
        run(client.aclose())

    assert result.success is True
    assert result.content == "Document draft"
    assert captured["model"] == "qwen2.5-coder:7b"
    assert captured["stream"] is False


def test_generation_handles_missing_model(monkeypatch):
    monkeypatch.setenv("OLLAMA_DOCUMENT_MODEL", "missing:7b")
    client = httpx.AsyncClient(
        base_url="http://ollama.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(404, json={"error": "not found"})),
    )
    adapter = OllamaDocumentAdapter(client=client, ollama_url="http://ollama.test")

    try:
        result = run(adapter.generate_document("test"))
    finally:
        run(client.aclose())

    assert result.success is False
    assert result.error == "Ollama model is not installed: missing:7b"
