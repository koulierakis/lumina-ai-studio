"""LUMINA Mind orchestration: intent, approval gating, real execution, advisor integration."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from ai_runtime.advisor import AdvisorRequest, ExecutiveAdvisorService
from ai_runtime.capabilities import (
    CapabilityExecutionError,
    MindCapabilityClient,
    MindOrchestrator,
    detect_confirmation,
    resolve_intent,
)

OWNER = "owner@lumina.local"


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeHealth:
    available = True
    installed_models = ()

    def to_dict(self):
        return {"available": True, "installed_models": []}


class FakeOllama:
    def __init__(self) -> None:
        self.calls = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse("Acknowledged from LUMINA Executive Intelligence.")

    async def check_connection(self, include_models=True):
        return FakeHealth()


class FakeMindClient(MindCapabilityClient):
    """Deterministic, network-free capability executor."""

    def __init__(self, responses: dict | None = None) -> None:
        super().__init__(base_url="http://fake")
        self.calls: list[dict] = []
        self.responses = responses or {}

    async def execute(self, operation, owner, params):
        self.calls.append({"id": operation.id, "path": operation.path, "params": dict(params)})
        if operation.id in self.responses:
            return self.responses[operation.id]
        if operation.id == "create_project":
            return {"id": "project-1", "name": params.get("name", "Mind Project")}
        return {"id": "obj-1", "path": operation.path, "status": "completed"}


def _orchestrator(tmp_path: Path, client: MindCapabilityClient | None = None) -> MindOrchestrator:
    return MindOrchestrator(root=tmp_path / "mind", client=client)


@pytest.mark.parametrize(
    ("message", "capability", "action"),
    [
        ("δημιούργησε μια εικόνα με ένα ηλιοβασίλεμα", "image", "generate"),
        ("φτιάξε ένα βίντεο 5 δευτερολέπτων για το προϊόν", "video", "generate"),
        ("κάνε μια φωνή για το τρέιλερ", "voice", "generate"),
        ("δείξε μου τα έγγραφά μου", "documents", "list"),
        ("δημιούργησε ένα έργο με όνομα Alpha", "studio", "create_project"),
        ("δείξε μου τα έργα μου", "studio", "list_projects"),
        ("φτιάξε κώδικα να προσθέτεις logging", "code_builder", "plan"),
    ],
)
def test_intent_resolution(message: str, capability: str, action: str) -> None:
    intent = resolve_intent(message)
    assert intent is not None
    assert (intent.capability, intent.action) == (capability, action)


def test_intent_parameter_extraction() -> None:
    assert resolve_intent("ναι") is None
    assert resolve_intent("όχι") is None
    video = resolve_intent("φτιάξε ένα βίντεο 5 δευτερολέπτων για το προϊόν")
    assert video.params.get("duration_seconds") == 5
    assert video.params.get("mode") == "text-to-video"
    project = resolve_intent("δημιούργησε ένα έργο με όνομα Alpha")
    assert project.params["name"] == "Alpha"
    doc = resolve_intent("ψάξε για τιμολόγιο")
    assert doc.capability == "documents" and doc.action == "search"
    assert doc.params["text"] == "τιμολογιο"
    image = resolve_intent("δημιούργησε μια εικόνα poster με αφίσα 9:16")
    assert image.capability == "image"
    assert image.params.get("aspect_ratio") == "9:16"


def test_intent_document_analysis_requires_single_attached_document() -> None:
    context = {"documents": [{"id": "doc-1", "title": "Συμφωνητικό"}]}
    analysis = resolve_intent("ανάλυσε το συμφωνητικό", context)
    assert (analysis.capability, analysis.action) == ("documents", "analysis")
    assert analysis.params["document_id"] == "doc-1"
    legal = resolve_intent("ποιος είναι ο νομικός κίνδυνος αυτού του εγγράφου", context)
    assert (legal.capability, legal.action) == ("documents", "legal_review")
    assert resolve_intent("ανάλυσε το συμφωνητικό") is None


def test_intent_conversational_messages_stay_conversational() -> None:
    for message in ("Ποια είναι η πρόβλεψη για τα έσοδα;", "Τι σημαίνει EBITDA;", "Καλημέρα", "γράψε μου κάτι σε παρακαλώ"):
        assert resolve_intent(message) is None


def test_confirmation_detection() -> None:
    assert detect_confirmation("ναι") == "approve"
    assert detect_confirmation("κάνε το") == "approve"
    assert detect_confirmation("όχι") == "decline"
    assert detect_confirmation("ακύρωσε το") == "decline" or detect_confirmation("ακύρωσέ το") == "decline"
    assert detect_confirmation("ναι αλλά εξήγησέ μου πρώτα") is None
    assert detect_confirmation("μπορείς να μου εξηγήσεις;") is None


# ---------------------------------------------------------------------------
# Approval gating
# ---------------------------------------------------------------------------
def test_approval_operations_are_gated_until_confirmed(tmp_path: Path) -> None:
    client = FakeMindClient()
    orchestrator = _orchestrator(tmp_path, client)
    result = asyncio.run(
        orchestrator.execute(OWNER, "code_builder", "execute", {"task_id": "task-9"}, session_id="s1")
    )
    assert result["status"] == "needs_approval"
    assert result["pending_id"]
    assert client.calls == []
    pending = orchestrator.pending(OWNER, "s1")
    assert pending["capability"] == "code_builder"
    assert pending["action"] == "execute"

    approved = asyncio.run(
        orchestrator.execute(OWNER, "code_builder", "execute", {"task_id": "task-9"}, confirmed=True, session_id="s1")
    )
    assert approved["status"] == "executed"
    assert client.calls == [{"id": "execute", "path": "/api/code-builder-v2/tasks/{task_id}/execute", "params": {"task_id": "task-9"}}]
    assert orchestrator.pending(OWNER, "s1") is None


def test_auto_operations_skip_approval(tmp_path: Path) -> None:
    client = FakeMindClient()
    orchestrator = _orchestrator(tmp_path, client)
    result = asyncio.run(
        orchestrator.execute(OWNER, "studio", "create_project", {"name": "Alpha", "description": "test"}, session_id="s2")
    )
    assert result["status"] == "executed"
    assert result["result"]["id"] == "project-1"


def test_missing_required_params_reject_before_execution(tmp_path: Path) -> None:
    client = FakeMindClient()
    orchestrator = _orchestrator(tmp_path, client)
    with pytest.raises(CapabilityExecutionError) as exc_info:
        asyncio.run(orchestrator.execute(OWNER, "documents", "get", {}))
    assert "Missing required parameter" in exc_info.value.message
    assert client.calls == []


def test_unknown_capability_or_action_is_rejected(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path, FakeMindClient())
    with pytest.raises(CapabilityExecutionError):
        asyncio.run(orchestrator.execute(OWNER, "nonexistent", "x", {}))
    with pytest.raises(CapabilityExecutionError):
        asyncio.run(orchestrator.execute(OWNER, "documents", "explode", {}))


def test_code_builder_plan_registers_followup_approval(tmp_path: Path) -> None:
    client = FakeMindClient(responses={"plan": {"id": "task-42", "status": "awaiting_approval"}})
    orchestrator = _orchestrator(tmp_path, client)
    result = asyncio.run(
        orchestrator.execute(OWNER, "code_builder", "plan", {"prompt": "add logging"}, session_id="s3")
    )
    assert result["status"] == "executed"
    assert result["next"] == "approval_required"
    assert result["pending"]["params"] == {"task_id": "task-42"}
    assert orchestrator.pending(OWNER, "s3")["action"] == "execute"

    confirmed = asyncio.run(orchestrator.handle_decision(OWNER, "s3", "ναι"))
    assert confirmed["status"] == "executed"
    assert client.calls[-1]["id"] == "execute"


def test_code_builder_plan_nested_task_polls_to_approval(tmp_path: Path) -> None:
    class AsyncPlanClient(FakeMindClient):
        def __init__(self) -> None:
            super().__init__()
            self.get_task_calls = 0

        async def execute(self, operation, owner, params):
            if operation.id == "plan":
                return {"task": {"id": "task-9", "status": "queued"}}
            if operation.id == "get_task":
                self.get_task_calls += 1
                status = "awaiting_approval" if self.get_task_calls >= 2 else "planning"
                return {"task": {"id": "task-9", "status": status}}
            return await super().execute(operation, owner, params)

    orchestrator = _orchestrator(tmp_path, AsyncPlanClient())
    result = asyncio.run(
        orchestrator.execute(OWNER, "code_builder", "plan", {"prompt": "add logging"}, session_id="s9")
    )
    assert result["status"] == "executed"
    assert result["next"] == "approval_required"
    assert result["pending"]["params"] == {"task_id": "task-9"}
    pending = orchestrator.pending(OWNER, "s9")
    assert pending is not None and pending["action"] == "execute"

    confirmed = asyncio.run(orchestrator.handle_decision(OWNER, "s9", "ναι"))
    assert confirmed["status"] == "executed"


def test_code_builder_plan_terminal_state_skips_approval(tmp_path: Path) -> None:
    class CompletedPlanClient(FakeMindClient):
        async def execute(self, operation, owner, params):
            if operation.id == "plan":
                return {"task": {"id": "task-10", "status": "planning"}}
            if operation.id == "get_task":
                return {"task": {"id": "task-10", "status": "completed"}}
            return await super().execute(operation, owner, params)

    orchestrator = _orchestrator(tmp_path, CompletedPlanClient())
    result = asyncio.run(
        orchestrator.execute(OWNER, "code_builder", "plan", {"prompt": "add docs"}, session_id="s10")
    )
    assert result["status"] == "executed"
    assert result.get("next") is None
    assert orchestrator.pending(OWNER, "s10") is None


# ---------------------------------------------------------------------------
# Real execution over the real FastAPI app (ASGI transport)
# ---------------------------------------------------------------------------
def _real_client():
    from server import app

    # 127.0.0.1 keeps the Host header inside TrustedHostMiddleware allow-list.
    return MindCapabilityClient(base_url="http://127.0.0.1:8000", transport=httpx.ASGITransport(app=app))


def test_real_list_documents_executes(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path, _real_client())
    result = asyncio.run(orchestrator.execute(OWNER, "documents", "list"))
    assert result["status"] == "executed"
    assert isinstance(result["result"], dict)


def test_real_project_create_and_list_roundtrip(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path, _real_client())
    name = "Mind E2E Project"
    created = asyncio.run(orchestrator.execute(OWNER, "studio", "create_project", {"name": name, "description": "orchestrator test"}))
    assert created["status"] == "executed"
    assert created["result"]["id"]
    project_id = created["result"]["id"]

    listed = asyncio.run(orchestrator.execute(OWNER, "studio", "list_projects"))
    assert listed["status"] == "executed"
    names = [item.get("name") for item in listed["result"].get("items", [])]
    assert name in names

    response = asyncio.run(orchestrator.execute(OWNER, "studio", "delete_project", {"project_id": project_id}, confirmed=False))
    assert response["status"] == "needs_approval"
    client = orchestrator.client
    approvals = orchestrator.pending(OWNER, None)
    assert approvals is not None


def test_real_approval_executes_delete_when_confirmed(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path, _real_client())
    name = "Mind E2E Delete Target"
    created = asyncio.run(orchestrator.execute(OWNER, "studio", "create_project", {"name": name}))
    project_id = created["result"]["id"]

    before = asyncio.run(orchestrator.execute(OWNER, "studio", "delete_project", {"project_id": project_id}, confirmed=True))
    assert before["status"] == "executed"

    listed = asyncio.run(orchestrator.execute(OWNER, "studio", "list_projects"))
    names = [item.get("name") for item in listed["result"].get("items", [])]
    assert name not in names


def test_mind_decide_endpoint_approves_and_declines(tmp_path: Path) -> None:
    from server import app

    from auth import issue_token

    headers = {"Authorization": f"Bearer {issue_token(OWNER)}"}
    transport = httpx.ASGITransport(app=app)
    base = "http://127.0.0.1:8000"

    async def run() -> None:
        async with httpx.AsyncClient(transport=transport, base_url=base, headers=headers) as client:
            created = (await client.post("/api/runtime/mind/execute", json={
                "capability": "studio",
                "action": "create_project",
                "params": {"name": "Decide Approve Target"},
            })).json()
            project_id = created["result"]["id"]

            gated = (await client.post("/api/runtime/mind/execute", json={
                "capability": "studio",
                "action": "delete_project",
                "params": {"project_id": project_id},
            })).json()
            assert gated["status"] == "needs_approval"

            approved = (await client.post("/api/runtime/mind/decide", json={"decision": "approve"})).json()
            assert approved["status"] == "executed"
            listed = (await client.get("/api/runtime/mind/actions")).json()["actions"]
            assert any(action["action"] == "delete_project" for action in listed)

            target = "Mind E2E Declined Target"
            created2 = (await client.post("/api/runtime/mind/execute", json={
                "capability": "studio",
                "action": "create_project",
                "params": {"name": target},
            })).json()
            declined_id = created2["result"]["id"]
            await client.post("/api/runtime/mind/execute", json={
                "capability": "studio",
                "action": "delete_project",
                "params": {"project_id": declined_id},
            })
            declined = (await client.post("/api/runtime/mind/decide", json={"decision": "decline"})).json()
            assert declined["status"] == "declined"

            pending = (await client.get("/api/runtime/mind/pending")).json()["pending"]
            assert pending is None

            await client.post("/api/runtime/mind/execute", json={
                "capability": "studio",
                "action": "delete_project",
                "params": {"project_id": declined_id},
            })
            cleaned = (await client.post("/api/runtime/mind/decide", json={"decision": "approve"})).json()
            assert cleaned["status"] == "executed"

            invalid = await client.post("/api/runtime/mind/decide", json={"decision": "maybe"})
            assert invalid.status_code == 400

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Advisor integration (FakeOllama + deterministic capability executor)
# ---------------------------------------------------------------------------
def test_ask_orchestrates_project_create_and_grounds_the_answer(tmp_path: Path) -> None:
    fake_ollama = FakeOllama()
    mind = FakeMindClient()
    orchestrator = _orchestrator(tmp_path, mind)
    service = ExecutiveAdvisorService(root=tmp_path / "advisor", ollama=fake_ollama, mind=orchestrator)
    service.model_name = lambda: "test-model"

    result = asyncio.run(
        service.ask(
            OWNER,
            AdvisorRequest(message="δημιούργησε ένα έργο με όνομα Alpha", orchestrate=True),
        )
    )
    assert result["orchestration"]["status"] == "executed"
    assert result["orchestration"]["capability"] == "studio"
    user_message = fake_ollama.calls[0]["messages"][-1]["content"]
    assert "LUMINA capability results" in user_message
    assert "Alpha" in user_message
    session = service.get_session(OWNER, result["session_id"])
    assert session["messages"][-1]["orchestration"]["status"] == "executed"


def test_ask_requires_approval_then_approves_next_turn(tmp_path: Path) -> None:
    fake_ollama = FakeOllama()
    client = FakeMindClient(responses={"plan": {"id": "task-77", "status": "awaiting_approval"}})
    orchestrator = _orchestrator(tmp_path, client)
    service = ExecutiveAdvisorService(root=tmp_path / "advisor", ollama=fake_ollama, mind=orchestrator)
    service.model_name = lambda: "test-model"

    first = asyncio.run(
        service.ask(
            OWNER,
            AdvisorRequest(message="φτιάξε κώδικα να προσθέτεις logging", orchestrate=True),
        )
    )
    orchestration = first["orchestration"]
    assert orchestration["status"] == "executed"
    assert orchestration["next"] == "approval_required"
    first_user_message = fake_ollama.calls[0]["messages"][-1]["content"]
    assert "requires explicit owner approval" in first_user_message

    second = asyncio.run(
        service.ask(
            OWNER,
            AdvisorRequest(message="ναι", orchestrate=True, session_id=first["session_id"]),
        )
    )
    assert second["orchestration"]["status"] == "executed"
    assert second["orchestration"]["capability"] == "code_builder"
    assert client.calls[-1]["id"] == "execute"
    assert client.calls[-1]["params"]["task_id"] == "task-77"


def test_ask_decline_cancels_pending_action(tmp_path: Path) -> None:
    fake_ollama = FakeOllama()
    client = FakeMindClient(responses={"plan": {"id": "task-5", "status": "awaiting_approval"}})
    orchestrator = _orchestrator(tmp_path, client)
    service = ExecutiveAdvisorService(root=tmp_path / "advisor", ollama=fake_ollama, mind=orchestrator)
    service.model_name = lambda: "test-model"

    first = asyncio.run(
        service.ask(
            OWNER,
            AdvisorRequest(message="φτιάξε κώδικα για νέα σελίδα", orchestrate=True),
        )
    )
    second = asyncio.run(
        service.ask(
            OWNER,
            AdvisorRequest(message="όχι, μην το κάνεις", orchestrate=True, session_id=first["session_id"]),
        )
    )
    assert second["orchestration"]["status"] == "declined"
    assert orchestrator.pending(OWNER, first["session_id"]) is None
    assert all(call["id"] != "execute" for call in client.calls)
    second_user_message = fake_ollama.calls[1]["messages"][-1]["content"]
    assert "declined" in second_user_message


def test_orchestration_never_runs_for_conversational_turns(tmp_path: Path) -> None:
    fake_ollama = FakeOllama()
    client = FakeMindClient()
    orchestrator = _orchestrator(tmp_path, client)
    service = ExecutiveAdvisorService(root=tmp_path / "advisor", ollama=fake_ollama, mind=orchestrator)
    service.model_name = lambda: "test-model"

    result = asyncio.run(
        service.ask(
            OWNER,
            AdvisorRequest(message="Ποια είναι η πρόβλεψη για τα έσοδα αυτού του τριμήνου;", orchestrate=True),
        )
    )
    assert result["orchestration"] is None
    assert client.calls == []
    session = service.get_session(OWNER, result["session_id"])
    assert session["messages"][-1].get("orchestration") is None


def test_ask_propagates_capability_failure_into_grounding(tmp_path: Path) -> None:
    fake_ollama = FakeOllama()

    class FailingClient(FakeMindClient):
        async def execute(self, operation, owner, params):
            from ai_runtime.capabilities import CapabilityExecutionError

            raise CapabilityExecutionError(503, "upstream unavailable")

    orchestrator = _orchestrator(tmp_path, FailingClient())
    service = ExecutiveAdvisorService(root=tmp_path / "advisor", ollama=fake_ollama, mind=orchestrator)
    service.model_name = lambda: "test-model"

    result = asyncio.run(
        service.ask(
            OWNER,
            AdvisorRequest(message="δείξε μου τα έγγραφά μου", orchestrate=True),
        )
    )
    assert result["orchestration"]["status"] == "failed"
    assert "upstream unavailable" in result["orchestration"]["error"]
    first_user_message = fake_ollama.calls[0]["messages"][-1]["content"]
    assert "upstream unavailable" in first_user_message