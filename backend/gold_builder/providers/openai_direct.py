"""Direct OpenAI provider (BYOK). Used when user pastes OPENAI_API_KEY.

Kept small and self-contained so it works outside the Emergent environment.
"""
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


class OpenAIDirect(LLMProvider):
    def __init__(self, model: str = "gpt-4o-mini"):
        self.provider = "openai"
        self.model = model
        self.id = f"byok-openai-{model}"

    def available(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY"))

    async def complete(self, req: CompletionRequest) -> CompletionResponse:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ProviderError("OPENAI_API_KEY not configured")
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise ProviderError("openai package not installed") from e

        client = AsyncOpenAI(api_key=key, timeout=60.0, max_retries=0)
        msgs = self._to_openai(req.messages, req.system)
        try:
            resp = await client.chat.completions.create(
                model=self.model,
                messages=msgs,
                max_tokens=req.max_tokens,
                temperature=req.temperature,
                response_format={"type": "json_object"} if req.json_mode else None,
            )
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
