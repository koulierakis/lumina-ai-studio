import asyncio

from ai_health import (
    AiCapability,
    ErrorDisposition,
    HealthState,
    classify_provider_error,
    collect_ai_health,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_classify_transient_statuses():
    for code in (408, 429, 500, 502, 503, 504):
        disposition = classify_provider_error(code)
        assert disposition in {ErrorDisposition.TRANSIENT, ErrorDisposition.QUOTA}


def test_classify_permanent_and_auth():
    assert classify_provider_error(401) == ErrorDisposition.AUTH
    assert classify_provider_error(403) == ErrorDisposition.AUTH
    assert classify_provider_error(402) == ErrorDisposition.QUOTA
    assert classify_provider_error(404) == ErrorDisposition.PERMANENT
    assert classify_provider_error(400) == ErrorDisposition.PERMANENT


def test_classify_by_message():
    assert classify_provider_error(message="connection timed out") == ErrorDisposition.TRANSIENT
    assert classify_provider_error(message="Invalid API key provided") == ErrorDisposition.AUTH
    assert classify_provider_error(message="rate limit exceeded") == ErrorDisposition.QUOTA
    assert classify_provider_error(message="unknown model") == ErrorDisposition.PERMANENT


def test_collect_health_shapes_every_capability():
    payload = _run(collect_ai_health())
    for cap in AiCapability:
        assert cap.value in payload["capabilities"]
        summary = payload["capabilities"][cap.value]
        assert summary["state"] in {s.value for s in HealthState}
    assert "providers" in payload
    assert isinstance(payload["any_ready"], bool)


def test_health_entries_are_credential_safe():
    payload = _run(collect_ai_health())
    for provider in payload["providers"]:
        assert set(provider) >= {
            "provider",
            "capability",
            "model",
            "configured",
            "healthy",
            "available",
            "state",
            "cooldown",
            "quota_state",
            "last_error",
            "detail",
        }
        # No secret-bearing payloads leaked into the status objects.
        assert "api_key" not in str(provider).lower()
        assert "secret" not in str(provider).lower()


def test_simulation_provider_is_not_labelled_ready_as_real():
    payload = _run(collect_ai_health())
    talking = [p for p in payload["providers"] if p["capability"] == "TALKING_FACE"]
    simulated = [p for p in talking if p["detail"] == "simulation only"]
    assert simulated, "expected the talking-face mock to be labelled as simulation only"
