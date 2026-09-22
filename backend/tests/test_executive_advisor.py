import asyncio
import json
from pathlib import Path

from ai_runtime.advisor import AdvisorRequest, ExecutiveAdvisorService


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
        return FakeResponse("Use the CFO view: preserve liquidity and model the downside first.")

    async def check_connection(self, include_models=True):
        return FakeHealth()


def test_configured_advisor_storage_is_isolated_and_persistent(tmp_path, monkeypatch):
    storage = tmp_path / "isolated-advisor"
    monkeypatch.setenv("LUMINA_ADVISOR_STATE_DIR", str(storage))
    service = ExecutiveAdvisorService(ollama=FakeOllama())
    assert service.root == storage
    memory = service.remember("test@example.com", "Isolated test memory")
    reloaded = ExecutiveAdvisorService(ollama=FakeOllama())
    assert reloaded.memories("test@example.com")[0]["id"] == memory["id"]
    explicit = ExecutiveAdvisorService(root=tmp_path / "explicit", ollama=FakeOllama())
    assert explicit.memories("test@example.com") == []


def test_role_routing_and_persistent_memory(tmp_path: Path) -> None:
    fake = FakeOllama()
    service = ExecutiveAdvisorService(root=tmp_path / "advisor", ollama=fake)
    assert service.route_role("Review our cash flow, margin and bank liquidity", "auto") == "cfo"
    assert service.route_role("Build a marketing campaign and positioning plan", "auto") == "cmo"
    assert service.route_role("Έλεγξε τη ρευστότητα, τα έσοδα και το κόστος", "auto") == "cfo"
    assert service.route_role("Ποιος είναι ο νομικός κίνδυνος και η συμμόρφωση;", "auto") == "risk"
    memory = service.remember("owner@example.com", "Prefer controlled downside risk.", "preference")
    service.update_profile("owner@example.com", {"company": "JSA", "currency": "EUR"})

    reloaded = ExecutiveAdvisorService(root=tmp_path / "advisor", ollama=FakeOllama())
    assert reloaded.memories("owner@example.com")[0]["id"] == memory["id"]
    assert reloaded.profile("owner@example.com")["company"] == "JSA"


def test_board_mode_uses_one_persistent_session_and_deep_reasoning(tmp_path: Path) -> None:
    fake = FakeOllama()
    service = ExecutiveAdvisorService(root=tmp_path / "advisor", ollama=fake)
    service.model_name = lambda: "test-model"

    first = asyncio.run(
        service.ask(
            "owner@example.com",
            AdvisorRequest(
                message="Should we expand into a new market?",
                role="board",
                deep_reasoning=True,
            ),
        )
    )
    second = asyncio.run(
        service.ask(
            "owner@example.com",
            AdvisorRequest(
                message="What is the biggest downside?",
                session_id=first["session_id"],
                role="board",
                deep_reasoning=True,
            ),
        )
    )

    assert first["role"] == "board"
    assert second["session_id"] == first["session_id"]
    assert len(service.get_session("owner@example.com", first["session_id"])["messages"]) == 4
    assert fake.calls[0]["model"] == "test-model"
    assert fake.calls[0]["think"] == "high"
    system_prompt = fake.calls[0]["messages"][0]["content"]
    assert "CEO, CFO, CMO" in system_prompt
    assert "one unified recommendation" in system_prompt
    assert "When the owner writes in Greek" in system_prompt


def test_auto_role_is_recorded_with_response(tmp_path: Path) -> None:
    service = ExecutiveAdvisorService(root=tmp_path / "advisor", ollama=FakeOllama())
    service.model_name = lambda: "test-model"
    result = asyncio.run(
        service.ask(
            "owner@example.com",
            AdvisorRequest(message="How should we improve cash flow and budget control?", role="auto"),
        )
    )
    assert result["role"] == "cfo"
    assert result["provider_status"] == "ok"
    session = service.get_session("owner@example.com", result["session_id"])
    assert session["messages"][-1]["role_mode"] == "cfo"


def test_document_context_is_grounded_into_model_request(tmp_path: Path) -> None:
    fake = FakeOllama()
    service = ExecutiveAdvisorService(root=tmp_path / "advisor", ollama=fake)
    service.model_name = lambda: "test-model"

    asyncio.run(
        service.ask(
            "owner@example.com",
            AdvisorRequest(
                message="Assess the attached agreement.",
                role="risk",
                context={
                    "documents": [
                        {
                            "id": "doc-1",
                            "title": "Commission Agreement",
                            "text": "Commission is payable within 24 hours after verified settlement.",
                        }
                    ]
                },
            ),
        )
    )

    user_message = fake.calls[0]["messages"][-1]["content"]
    assert "Additional structured context" in user_message
    assert "Commission Agreement" in user_message
    assert "payable within 24 hours" in user_message


def test_sambanova_status_exposes_configured_state(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SAMBANOVA_API_KEY", "sn-status-key")
    monkeypatch.setenv("SAMBANOVA_BASE_URL", "https://api.sambanova.ai/v1")
    monkeypatch.setenv("SAMBANOVA_MODEL", "status-sn-model")
    service = ExecutiveAdvisorService(root=tmp_path / "advisor", ollama=FakeOllama())
    status = asyncio.run(service.status())
    assert status["sambanova_configured"] is True
    assert status["sambanova_model"] == "status-sn-model"
    assert "optional_sambanova" in status["capabilities"]
    assert "sn-status-key" not in json.dumps(status)


def test_sambanova_unconfigured_status_is_false(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SAMBANOVA_API_KEY", raising=False)
    monkeypatch.delenv("SAMBANOVA_BASE_URL", raising=False)
    monkeypatch.delenv("SAMBANOVA_MODEL", raising=False)
    service = ExecutiveAdvisorService(root=tmp_path / "advisor", ollama=FakeOllama())
    status = asyncio.run(service.status())
    assert status["sambanova_configured"] is False


def test_auto_routing_uses_configured_sambanova_cloud_provider(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SAMBANOVA_API_KEY", "detective-wonka-sn")
    monkeypatch.setenv("SAMBANOVA_BASE_URL", "https://api.sambanova.ai/v1")
    monkeypatch.setenv("SAMBANOVA_MODEL", "custom-sn-model")
    service = ExecutiveAdvisorService(root=tmp_path / "advisor", ollama=FakeOllama())
    captured = {}

    async def fake_sambanova(**kwargs):
        captured["messages"] = kwargs["messages"]
        return ("Cloud readiness is verified.", [], "custom-sn-model")

    service._ask_sambanova = fake_sambanova
    result = asyncio.run(
        service.ask(
            "owner@example.com",
            AdvisorRequest(message="Is the platform production-ready for corporate use?"),
        )
    )
    assert result["provider"] == "sambanova"
    assert result["model"] == "custom-sn-model"
    assert result["provider_status"] == "ok"
    assert captured["messages"][-1]["role"] == "user"
    session = service.get_session("owner@example.com", result["session_id"])
    assert session["messages"][-1]["provider"] == "sambanova"
    assert session["messages"][-1]["model"] == "custom-sn-model"
    assert "detective-wonka-sn" not in json.dumps(result)


def test_explicit_sambanova_provider_is_recorded(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SAMBANOVA_API_KEY", "sn-key")
    monkeypatch.setenv("SAMBANOVA_BASE_URL", "https://api.sambanova.ai/v1")
    service = ExecutiveAdvisorService(root=tmp_path / "advisor", ollama=FakeOllama())

    async def fake_sambanova(**kwargs):
        return ("Confirmed.", [], "custom-sn-model")

    service._ask_sambanova = fake_sambanova
    result = asyncio.run(
        service.ask(
            "owner@example.com",
            AdvisorRequest(message="Confirm provider selection.", provider="sambanova"),
        )
    )
    assert result["provider"] == "sambanova"
    assert result["provider_status"] == "ok"


def test_sambanova_failure_is_sanitized_and_unavailable(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SAMBANOVA_API_KEY", "secret-failure-sn")
    monkeypatch.setenv("SAMBANOVA_BASE_URL", "https://api.sambanova.ai/v1")
    service = ExecutiveAdvisorService(root=tmp_path / "advisor", ollama=FakeOllama())

    async def failing(**kwargs):
        raise RuntimeError("HTTP 503 transient failure")

    service._ask_sambanova = failing
    result = asyncio.run(
        service.ask(
            "owner@example.com",
            AdvisorRequest(message="Are we ready?"),
        )
    )
    assert result["provider"] == "sambanova"
    assert result["provider_status"] == "unavailable"
    assert "SambaNova cloud mode is currently unavailable" in result["answer"]
    assert "secret-failure-sn" not in json.dumps(result)
