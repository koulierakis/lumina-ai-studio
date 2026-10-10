"""Focused Groq recovery tests: provider JSON 400 and bounded 429."""
import sys
import types
from unittest.mock import patch

import pytest

from code_builder_v2.ollama import OllamaClient, RateLimitError


class _APIError(Exception):
    def __init__(self, status_code, body=None, headers=None):
        super().__init__(str(body))
        self.status_code = status_code
        self.body = body
        self.response = types.SimpleNamespace(headers=headers or {})


class _RateLimitError(_APIError):
    pass


def _fake_groq_module(completions):
    class Groq:
        def __init__(self, **kwargs):
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=completions)
            )
    return types.SimpleNamespace(Groq=Groq, APIError=_APIError, RateLimitError=_RateLimitError)


def test_groq_json_validate_failed_recovers_with_local_validation(monkeypatch):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise _APIError(400, {"error": {"code": "json_validate_failed"}})
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(
                content='{"changes":[{"path":"app.py","operation":"create","content":"print(1)\\n"}]}'
            ))]
        )

    monkeypatch.setenv("GROQ_API_KEY", "fixture-only")
    monkeypatch.setitem(sys.modules, "groq", _fake_groq_module(create))
    result = OllamaClient()._generate_with_groq("create app", "openai/gpt-oss-120b")
    assert result["changes"][0]["path"] == "app.py"
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in calls[1]


def test_groq_json_retry_does_not_accept_invalid_json(monkeypatch):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise _APIError(400, {"error": {"code": "json_validate_failed"}})
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="not-json"))]
        )

    monkeypatch.setenv("GROQ_API_KEY", "fixture-only")
    monkeypatch.setitem(sys.modules, "groq", _fake_groq_module(create))
    with pytest.raises(Exception, match="JSON|json"):
        OllamaClient()._generate_with_groq("create app", "openai/gpt-oss-120b")


def test_groq_429_retry_after_is_bounded(monkeypatch):
    calls = []
    sleeps = []

    def create(**kwargs):
        calls.append(kwargs)
        raise _RateLimitError(429, {"error": "rate limit"}, {"retry-after": "999999"})

    monkeypatch.setenv("GROQ_API_KEY", "fixture-only")
    monkeypatch.setitem(sys.modules, "groq", _fake_groq_module(create))
    monkeypatch.setattr("code_builder_v2.ollama.time.sleep", sleeps.append)
    with pytest.raises(RateLimitError):
        OllamaClient()._generate_with_groq("create app", "openai/gpt-oss-120b")
    assert len(calls) == 3
    assert sleeps == [30, 30]
