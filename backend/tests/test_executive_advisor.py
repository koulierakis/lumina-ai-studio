import asyncio
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


def test_role_routing_and_persistent_memory(tmp_path: Path) -> None:
    fake = FakeOllama()
    service = ExecutiveAdvisorService(root=tmp_path / "advisor", ollama=fake)
    assert service.route_role("Review our cash flow, margin and bank liquidity", "auto") == "cfo"
    assert service.route_role("Build a marketing campaign and positioning plan", "auto") == "cmo"
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


class FailingOllama(FakeOllama):
    async def chat(self, **kwargs):
        from code_builder.ollama_service import OllamaServiceError
        raise OllamaServiceError("local unavailable")


def test_greek_auto_routing_and_bounded_document_context(tmp_path: Path) -> None:
    service = ExecutiveAdvisorService(root=tmp_path / "advisor", ollama=FakeOllama())
    assert service.route_role("Θέλω να βελτιώσω τη ρευστότητα και τον τραπεζικό προϋπολογισμό", "auto") == "cfo"
    bounded = service._bounded_context({
        "documents": [
            {"id": str(index), "title": "X" * 700, "text": "A" * 30000}
            for index in range(5)
        ]
    })
    assert len(bounded["documents"]) == 2 or len(bounded["documents"]) == 3
    assert len(bounded["documents"]) <= 3
    assert sum(len(item["text"]) for item in bounded["documents"]) <= 45000
    assert all(len(item["text"]) <= 20000 for item in bounded["documents"])
    assert all(len(item["title"]) <= 500 for item in bounded["documents"])


def test_memory_deduplicates_exact_repeated_fact(tmp_path: Path) -> None:
    service = ExecutiveAdvisorService(root=tmp_path / "advisor", ollama=FakeOllama())
    first = service.remember("owner@example.com", "Prefer liquidity first.", "preference")
    second = service.remember("owner@example.com", " prefer liquidity first. ", "preference")
    assert first["id"] == second["id"]
    assert len(service.memories("owner@example.com")) == 1


def test_auto_provider_falls_back_to_cloud_when_local_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    service = ExecutiveAdvisorService(root=tmp_path / "advisor", ollama=FailingOllama())
    service.model_name = lambda: "test-model"
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    async def fake_openai(**kwargs):
        return "cloud fallback answer", [], "cloud-model"

    service._ask_openai = fake_openai
    result = asyncio.run(
        service.ask(
            "owner@example.com",
            AdvisorRequest(message="Give me the recommendation.", provider="auto"),
        )
    )
    assert result["answer"] == "cloud fallback answer"
    assert result["provider"] == "openai"
    assert result["provider_status"] == "fallback"
