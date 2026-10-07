import httpx
import pytest

from code_builder.gold_builder_engine import (
    GoldBuilderEngine,
    GoldBuilderUnavailable,
    gold_builder_base_url,
)
from code_builder.engine_registry import (
    GOLD_BUILDER_ENGINE,
    NATIVE_ENGINE,
    OPENHANDS_ENGINE,
    CodingEngineRegistry,
)


def _engine(handler) -> GoldBuilderEngine:
    return GoldBuilderEngine("http://gb.test", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_health_makes_engine_available():
    def handler(request):
        assert request.url.path == "/api/gb/health"
        return httpx.Response(200, json={"status": "ok"})

    assert _engine(handler).status().available is True


def test_unreachable_service_reports_unavailable_not_crash():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    status = _engine(handler).status()
    assert status.available is False
    assert "not reachable" in status.detail


def test_http_error_raises_unavailable():
    def handler(request):
        return httpx.Response(503, json={"detail": "down"})

    with pytest.raises(GoldBuilderUnavailable):
        _engine(handler).get_status("job-1")


def test_job_lifecycle_uses_expected_endpoints():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.url.path == "/api/gb/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/api/gb/jobs":
            return httpx.Response(200, json={"id": "job-1", "status": "draft"})
        if request.url.path == "/api/gb/jobs/job-1/start":
            return httpx.Response(200, json={"id": "job-1", "status": "running"})
        if request.url.path == "/api/gb/jobs/job-1":
            return httpx.Response(200, json={"id": "job-1", "status": "completed"})
        if request.url.path == "/api/gb/jobs/job-1/review":
            return httpx.Response(200, json={"review": "ok"})
        if request.url.path == "/api/gb/jobs/job-1/screenshot":
            return httpx.Response(200, json={"screenshots": []})
        return httpx.Response(404)

    engine = _engine(handler)
    created = engine.create_job({"prompt": "site"})
    assert created["id"] == "job-1"
    engine.start_job("job-1")
    report = engine.final_report("job-1")
    assert report["status"] == "completed"
    assert ("POST", "/api/gb/jobs") in seen
    assert ("POST", "/api/gb/jobs/job-1/start") in seen


def test_final_report_survives_missing_subresources():
    def handler(request):
        if request.url.path == "/api/gb/jobs/job-2":
            return httpx.Response(200, json={"id": "job-2", "status": "completed"})
        return httpx.Response(404)

    report = _engine(handler).final_report("job-2")
    assert report["status"] == "completed"
    assert report["review"] is None


def test_base_url_is_env_driven(monkeypatch):
    monkeypatch.setenv("GOLD_BUILDER_URL", "http://localhost:9999/")
    assert gold_builder_base_url() == "http://localhost:9999"


class _StubGold:
    def __init__(self, available):
        from code_builder.gold_builder_engine import GoldBuilderEngineStatus

        self._available = available
        self._status_cls = GoldBuilderEngineStatus

    def status(self):
        return self._status_cls("gold_builder", self._available, "http://gb.test", True, "" if self._available else "unreachable")


def test_registry_reports_primary_secondary_legacy():
    status = CodingEngineRegistry(gold_builder=_StubGold(True)).public_status()
    roles = status["roles"]
    assert roles[GOLD_BUILDER_ENGINE] == "primary"
    assert roles[OPENHANDS_ENGINE] == "secondary"
    assert roles[NATIVE_ENGINE] == "legacy_fallback"
    assert status["order"] == [GOLD_BUILDER_ENGINE, OPENHANDS_ENGINE, NATIVE_ENGINE]
    # native remains the safe default even when Gold Builder is available
    assert status["default"] == NATIVE_ENGINE
    assert status["preferred"] == GOLD_BUILDER_ENGINE


def test_auto_routing_prefers_available_gold_builder():
    registry = CodingEngineRegistry(gold_builder=_StubGold(True))
    assert registry.suggest_engine() == GOLD_BUILDER_ENGINE


def test_auto_routing_falls_back_to_native_when_gold_unavailable():
    registry = CodingEngineRegistry(gold_builder=_StubGold(False))
    assert registry.suggest_engine() == NATIVE_ENGINE


def test_explicit_selection_wins_when_available():
    registry = CodingEngineRegistry(gold_builder=_StubGold(True))
    assert registry.suggest_engine("gold_builder") == GOLD_BUILDER_ENGINE
    assert registry.suggest_engine("native") == NATIVE_ENGINE


def test_selecting_unreachable_gold_builder_raises():
    registry = CodingEngineRegistry(gold_builder=_StubGold(False))
    with pytest.raises(RuntimeError, match="not reachable"):
        registry.validate_selection("gold_builder")
