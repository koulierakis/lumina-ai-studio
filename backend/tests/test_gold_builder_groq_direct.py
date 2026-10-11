import asyncio
import sys
from types import SimpleNamespace

from gold_builder.providers.base import CompletionRequest, Message
from gold_builder.providers.groq_direct import GroqDirect


def _fake_openai_module(captured):
    async def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"ok": true}'),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3),
        )

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

        async def close(self):
            pass

    return SimpleNamespace(AsyncOpenAI=FakeClient)


def test_gpt_oss_json_mode_sets_hidden_reasoning_format(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    captured = {}
    monkeypatch.setitem(sys.modules, "openai", _fake_openai_module(captured))

    response = asyncio.run(
        GroqDirect().complete(
            CompletionRequest(
                messages=[Message(role="user", content="Return JSON.")],
                json_mode=True,
            )
        )
    )

    assert captured["response_format"] == {"type": "json_object"}
    assert captured["reasoning_format"] == "hidden"
    assert response.text == '{"ok": true}'


def test_non_gpt_oss_json_mode_does_not_send_reasoning_format(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    captured = {}
    monkeypatch.setitem(sys.modules, "openai", _fake_openai_module(captured))

    asyncio.run(
        GroqDirect(model="llama-3.3-70b-versatile").complete(
            CompletionRequest(
                messages=[Message(role="user", content="Return JSON.")],
                json_mode=True,
            )
        )
    )

    assert captured["response_format"] == {"type": "json_object"}
    assert "reasoning_format" not in captured
