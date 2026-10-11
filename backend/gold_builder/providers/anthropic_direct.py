"""Direct Anthropic provider (BYOK). Used when ANTHROPIC_API_KEY is set."""
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


class AnthropicDirect(LLMProvider):
    def __init__(self, model: str = "claude-3-5-sonnet-latest"):
        self.provider = "anthropic"
        self.model = model
        self.id = f"byok-anthropic-{model}"

    def available(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    async def complete(self, req: CompletionRequest) -> CompletionResponse:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderError("ANTHROPIC_API_KEY not configured")
        try:
            from anthropic import AsyncAnthropic
        except ImportError as e:
            raise ProviderError("anthropic package not installed") from e

        client = AsyncAnthropic(api_key=key, timeout=60.0, max_retries=0)
        system = req.system or self._extract_system(req.messages) or ""
        msgs = [
            {"role": m.role, "content": m.content}
            for m in req.messages
            if m.role != "system"
        ]
        try:
            resp = await client.messages.create(
                model=self.model,
                system=system if system else None,
                messages=msgs,
                max_tokens=req.max_tokens,
                temperature=req.temperature,
            )
            text = "".join(
                block.text for block in resp.content if getattr(block, "type", "") == "text"
            )
            return CompletionResponse(
                text=text,
                finish_reason=getattr(resp, "stop_reason", None),
                provider=self.provider,
                model=self.model,
                usage={
                    "input_tokens": getattr(resp.usage, "input_tokens", 0),
                    "output_tokens": getattr(resp.usage, "output_tokens", 0),
                },
            )
        except Exception as e:  # noqa: BLE001
            raise provider_exception(self.id, e) from None
        finally:
            await client.close()

    @staticmethod
    def _extract_system(messages: List[Message]) -> str:
        for m in messages:
            if m.role == "system":
                return m.content
        return ""
