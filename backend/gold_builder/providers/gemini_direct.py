"""Direct Gemini provider using Google's OpenAI-compatible endpoint."""
from __future__ import annotations

import os
from typing import List

from .base import CompletionRequest, CompletionResponse, LLMProvider, Message, ProviderError, provider_exception


class GeminiDirect(LLMProvider):
    def __init__(self, model: str = "gemini-2.5-flash"):
        self.provider = "gemini"
        self.model = model
        self.id = f"byok-gemini-{model}"

    def available(self) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY"))

    async def complete(self, req: CompletionRequest) -> CompletionResponse:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise ProviderError("GEMINI_API_KEY not configured")
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise ProviderError("openai package not installed") from e

        client = AsyncOpenAI(
            api_key=key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            timeout=60.0,
            max_retries=0,
        )
        kwargs = {
            "model": self.model,
            "messages": self._to_openai(req.messages, req.system),
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
        out.extend({"role": m.role, "content": m.content} for m in messages)
        return out
