from types import SimpleNamespace

import pytest

from gold_builder.providers.base import CompletionRequest, Message
from gold_builder.providers.groq_direct import GroqDirect


@pytest.mark.asyncio
async def test_gpt_oss_json_mode_sets_hidden_reasoning_format(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    captured = {}

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
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

        async def close(self):
            pass

    monkeypatch.setitem(
        __import__("sys").modules,
        "openai",
        SimpleNamespace(AsyncOpenAI=FakeClient),
    )

    response = await GroqDirect().complete(
        CompletionRequest(
            messages=[Message(role="user", content="Return JSON.")],
            json_mode=True,
        )
    )

    assert captured["response_format"] == {"type": "json_object"}
    assert captured["reasoning_format"] == "hidden"
    assert response.text == '{"ok": true}'


@pytest.mark.asyncio
async def test_non_gpt_oss_json_mode_does_not_send_reasoning_format(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    captured = {}

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
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

        async def close(self):
            pass

    monkeypatch.setitem(
        __import__("sys").modules,
        "openai",
        SimpleNamespace(AsyncOpenAI=FakeClient),
    )

    await GroqDirect(model="llama-3.3-70b-versatile").complete(
        CompletionRequest(
            messages=[Message(role="user", content="Return JSON.")],
            json_mode=True,
        )
    )

    assert captured["response_format"] == {"type": "json_object"}
    assert "reasoning_format" not in captured
