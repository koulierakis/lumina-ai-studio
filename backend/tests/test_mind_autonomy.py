"""LUMINA Mind autonomy dial: levels, safety invariants and gating.

The dial must never be able to relax outbound or destructive operations. These
tests pin that invariant at every level, plus the default and the reversible
local exception.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ai_runtime.capabilities import autonomy
from ai_runtime.capabilities.client import MindCapabilityClient
from ai_runtime.capabilities.orchestrator import MindOrchestrator

OWNER = "owner@lumina.local"


class FakeMindClient(MindCapabilityClient):
    def __init__(self, responses: dict | None = None) -> None:
        super().__init__(base_url="http://fake")
        self.calls: list[dict] = []
        self.responses = responses or {}

    async def execute(self, operation, owner, params):
        self.calls.append({"id": operation.id, "params": dict(params)})
        if operation.id in self.responses:
            return self.responses[operation.id]
        return {"id": "obj-1", "status": "completed"}


def _orchestrator(tmp_path: Path, client: MindCapabilityClient | None = None) -> MindOrchestrator:
    return MindOrchestrator(root=tmp_path / "mind", client=client)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(autonomy.ENV_VAR, raising=False)
    yield


# --------------------------------------------------------------- classification
def test_default_level_is_assisted():
    assert autonomy.current_level() == "assisted"
    assert autonomy.normalise_level(None) == "assisted"
    assert autonomy.normalise_level("garbage") == "assisted"
    assert autonomy.normalise_level("AUTO") == "auto"


@pytest.mark.parametrize("level", ["manual", "assisted", "auto"])
def test_outbound_is_never_automatic(level):
    assert autonomy.requires_approval(level, "approval", "connect", "send_email") is True
    assert autonomy.requires_approval(level, "approval", "connect", "send_whatsapp") is True
    assert autonomy.requires_approval(level, "approval", "connect", "publish_social") is True


@pytest.mark.parametrize("level", ["manual", "assisted", "auto"])
def test_destructive_is_never_automatic(level):
    for capability, action in (
        ("documents", "delete"),
        ("documents", "delete_folder"),
        ("image", "delete_gallery_item"),
        ("video", "delete_job"),
        ("voice", "delete_pack"),
        ("studio", "delete_project"),
        ("studio", "delete_media"),
    ):
        assert autonomy.requires_approval(level, "approval", capability, action) is True


def test_manual_gates_even_safe_operations():
    assert autonomy.requires_approval("manual", "auto", "studio", "create_project") is True
    assert autonomy.requires_approval("assisted", "auto", "studio", "create_project") is False
    assert autonomy.requires_approval("auto", "auto", "studio", "create_project") is False


def test_only_auto_relaxes_reversible_local_operations():
    assert autonomy.requires_approval("assisted", "approval", "code_builder", "execute") is True
    assert autonomy.requires_approval("manual", "approval", "code_builder", "execute") is True
    assert autonomy.requires_approval("auto", "approval", "code_builder", "execute") is False


def test_unknown_approval_operation_stays_gated_at_every_level():
    for level in autonomy.LEVELS:
        assert autonomy.requires_approval(level, "approval", "documents", "some_new_action") is True


def test_describe_reports_level_and_labels():
    described = autonomy.describe("auto")
    assert described["level"] == "auto"
    assert described["default"] == "assisted"
    assert set(described["levels"]) == {"manual", "assisted", "auto"}
    assert described["labels"]["manual"]


# -------------------------------------------------------------------- gating
def test_connector_send_is_gated_even_at_auto(tmp_path):
    client = FakeMindClient()
    orchestrator = _orchestrator(tmp_path, client)
    orchestrator.set_autonomy_level("auto")
    result = asyncio.run(
        orchestrator.execute(
            OWNER, "connect", "send_email",
            {"to": "a@b.com", "body": "hi"}, session_id="s-auto",
        )
    )
    assert result["status"] == "needs_approval"
    assert client.calls == []


def test_delete_is_gated_even_at_auto(tmp_path):
    client = FakeMindClient()
    orchestrator = _orchestrator(tmp_path, client)
    orchestrator.set_autonomy_level("auto")
    result = asyncio.run(
        orchestrator.execute(OWNER, "studio", "delete_project", {"project_id": "p1"}, session_id="s-del")
    )
    assert result["status"] == "needs_approval"
    assert client.calls == []


def test_manual_gates_safe_operations(tmp_path):
    client = FakeMindClient()
    orchestrator = _orchestrator(tmp_path, client)
    orchestrator.set_autonomy_level("manual")
    result = asyncio.run(
        orchestrator.execute(OWNER, "studio", "create_project", {"name": "Alpha"}, session_id="s-man")
    )
    assert result["status"] == "needs_approval"
    assert client.calls == []


def test_assisted_default_keeps_safe_operations_automatic(tmp_path):
    client = FakeMindClient()
    orchestrator = _orchestrator(tmp_path, client)
    assert orchestrator.autonomy_level() == "assisted"
    result = asyncio.run(
        orchestrator.execute(OWNER, "studio", "create_project", {"name": "Alpha"}, session_id="s-def")
    )
    assert result["status"] == "executed"
    assert client.calls and client.calls[0]["id"] == "create_project"


def test_auto_relaxes_reversible_local_execute(tmp_path):
    client = FakeMindClient()
    orchestrator = _orchestrator(tmp_path, client)
    orchestrator.set_autonomy_level("auto")
    result = asyncio.run(
        orchestrator.execute(OWNER, "code_builder", "execute", {"task_id": "t1"}, session_id="s-auto-local")
    )
    assert result["status"] == "executed"
    assert client.calls and client.calls[0]["id"] == "execute"


def test_auto_applies_code_builder_plan_followup_without_prompting(tmp_path):
    client = FakeMindClient(responses={"plan": {"id": "task-7", "status": "awaiting_approval"}})
    orchestrator = _orchestrator(tmp_path, client)
    orchestrator.set_autonomy_level("auto")
    result = asyncio.run(
        orchestrator.execute(OWNER, "code_builder", "plan", {"prompt": "add logging"}, session_id="s-plan")
    )
    assert result["status"] == "executed"
    assert result["next"] == "auto_executed"
    assert client.calls[-1]["id"] == "execute"
    assert orchestrator.pending(OWNER, "s-plan") is None


def test_assisted_still_registers_code_builder_plan_followup(tmp_path):
    client = FakeMindClient(responses={"plan": {"id": "task-8", "status": "awaiting_approval"}})
    orchestrator = _orchestrator(tmp_path, client)
    result = asyncio.run(
        orchestrator.execute(OWNER, "code_builder", "plan", {"prompt": "add logging"}, session_id="s-plan2")
    )
    assert result["next"] == "approval_required"
    assert orchestrator.pending(OWNER, "s-plan2")["action"] == "execute"


def test_environment_sets_default_level(tmp_path, monkeypatch):
    monkeypatch.setenv(autonomy.ENV_VAR, "auto")
    orchestrator = _orchestrator(tmp_path, FakeMindClient())
    assert orchestrator.autonomy_level() == "auto"
    assert orchestrator.autonomy()["level"] == "auto"


def test_runtime_override_wins_over_environment(tmp_path, monkeypatch):
    monkeypatch.setenv(autonomy.ENV_VAR, "auto")
    orchestrator = _orchestrator(tmp_path, FakeMindClient())
    orchestrator.set_autonomy_level("manual")
    assert orchestrator.autonomy_level() == "manual"


# ------------------------------------------------------------- HTTP surface
def test_mind_autonomy_endpoints() -> None:
    import httpx

    from auth import issue_token
    from server import app

    headers = {"Authorization": f"Bearer {issue_token(OWNER)}"}
    transport = httpx.ASGITransport(app=app)
    base = "http://127.0.0.1:8000"

    async def run() -> None:
        async with httpx.AsyncClient(transport=transport, base_url=base, headers=headers) as client:
            current = (await client.get("/api/runtime/mind/autonomy")).json()
            assert current["level"] == "assisted"
            assert set(current["levels"]) == {"manual", "assisted", "auto"}

            updated = (await client.post("/api/runtime/mind/autonomy", json={"level": "auto"})).json()
            assert updated["level"] == "auto"

            status = (await client.get("/api/runtime/advisor/status")).json()
            assert status["autonomy"]["level"] == "auto"

            rejected = await client.post("/api/runtime/mind/autonomy", json={"level": "yolo"})
            assert rejected.status_code == 400

            # Restore the default so this test does not leak into others.
            restored = (await client.post("/api/runtime/mind/autonomy", json={"level": "assisted"})).json()
            assert restored["level"] == "assisted"

    asyncio.run(run())

