"""Direct Groq provider using Groq's OpenAI-compatible API."""
from __future__ import annotations

import os
from typing import List

from .base import (
    CompletionRequest,
    CompletionResponse,
    LLMProvider,
    Message,
    ProviderError,
    TransientProviderError,
    classify_transient,
    provider_exception,
)


class GroqDirect(LLMProvider):
    def __init__(self, model: str = "openai/gpt-oss-120b"):
        self.provider = "groq"
        self.model = model
        self.id = f"byok-groq-{model}"

    def available(self) -> bool:
        return bool(os.environ.get("GROQ_API_KEY"))

    async def complete(self, req: CompletionRequest) -> CompletionResponse:
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            raise ProviderError("GROQ_API_KEY not configured")
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise ProviderError("openai package not installed") from e

        client = AsyncOpenAI(api_key=key, base_url="https://api.groq.com/openai/v1",
                                 timeout=60.0, max_retries=0)
        msgs = self._to_openai(req.messages, req.system)
        kwargs = {
            "model": self.model,
            "messages": msgs,
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
        }
        if req.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = await client.chat.completions.create(**kwargs)
            text = resp.choices[0].message.content or ""
            return CompletionResponse(
                text=text,
                finish_reason=getattr(resp.choices[0], "finish_reason", None),
                provider=self.provider,
                model=self.model,
                usage={
                    "prompt_tokens": getattr(resp.usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(resp.usage, "completion_tokens", 0),
                },
            )
        except Exception as e:  # noqa: BLE001
            raise provider_exception(self.id, e) from None
        finally:
            await client.close()

    @staticmethod
    def _to_openai(messages: List[Message], system: str | None):
        out = []
        if system:
            out.append({"role": "system", "content": system})
        for m in messages:
            out.append({"role": m.role, "content": m.content})
        return out
