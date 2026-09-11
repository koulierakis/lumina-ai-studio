from __future__ import annotations

import asyncio

import server


def test_backend_health_check_contract(monkeypatch):
    async def fake_statuses():
        return {"mock": {"status": "ok"}}

    async def fake_health_summary():
        return {"healthy": True}

    async def fake_ping():
        return None

    monkeypatch.setattr(server.provider_manager, "statuses", fake_statuses)
    monkeypatch.setattr(server.provider_manager, "health_summary", fake_health_summary)
    monkeypatch.setattr(server, "available_providers", lambda: ["mock"])
    monkeypatch.setattr(server, "now_iso", lambda: "2026-01-01T00:00:00Z")
    monkeypatch.setattr(server.persistence_provider, "ping", fake_ping)
    monkeypatch.setattr(server, "storage_health", lambda: {"status": "OK", "backend": "supabase", "persistent": True})
    monkeypatch.setenv("GIT_COMMIT_SHA", "abcdef1234567890abcdef1234567890abcdef12")

    payload = asyncio.run(server.health())

    assert payload["status"] == "ok"
    assert payload["backend"] == "ok"
    assert payload["database"]["ping"] == "OK"
    assert payload["storage"]["status"] == "OK"
    assert payload["storage"]["persistent"] is True
    assert payload["commit_sha"] == "abcdef1234567890abcdef1234567890abcdef12"
    assert payload["providers_available"] == ["mock"]


def test_backend_health_degrades_when_storage_fails(monkeypatch):
    async def fake_statuses():
        return {}

    async def fake_health_summary():
        return {"healthy": True}

    async def fake_ping():
        return None

    monkeypatch.setattr(server.provider_manager, "statuses", fake_statuses)
    monkeypatch.setattr(server.provider_manager, "health_summary", fake_health_summary)
    monkeypatch.setattr(server.persistence_provider, "ping", fake_ping)
    monkeypatch.setattr(server, "storage_health", lambda: {"status": "FAIL", "backend": "supabase", "persistent": True, "error": "RuntimeError"})

    payload = asyncio.run(server.health())

    assert payload["status"] == "degraded"
    assert payload["database"]["ping"] == "OK"
    assert payload["storage"]["status"] == "FAIL"
