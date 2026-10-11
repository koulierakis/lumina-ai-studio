"""LLM provider backed by Emergent Universal Key (emergentintegrations lib).

Supports OpenAI, Anthropic, Gemini through one key. Non-streaming completion
via send_message. Streaming is available in the library but the engine uses
buffered completions for reliability during codegen.
"""
from __future__ import annotations

import os
import uuid
from typing import List

try:
    from emergentintegrations.llm.chat import LlmChat, UserMessage
except ImportError:
    LlmChat = None
    UserMessage = None

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


class EmergentLLM(LLMProvider):
    def __init__(self, provider: str, model: str, id: str | None = None):
        self.provider = provider
        self.model = model
        self.id = id or f"emergent-{provider}-{model}"

    def available(self) -> bool:
        return bool(LlmChat is not None and os.environ.get("EMERGENT_LLM_KEY"))

    async def complete(self, req: CompletionRequest) -> CompletionResponse:
        key = os.environ.get("EMERGENT_LLM_KEY")
        if not key:
            raise ProviderError("EMERGENT_LLM_KEY not configured")

        system = req.system or self._extract_system(req.messages) or "You are a helpful assistant."
        session_id = f"gb-{uuid.uuid4().hex[:12]}"
        try:
            chat = LlmChat(
                api_key=key,
                session_id=session_id,
                system_message=system,
            ).with_model(self.provider, self.model)
            try:
                chat = chat.with_max_tokens(req.max_tokens)
            except AttributeError:
                pass

            # Build combined user text (engine calls are single-turn per request)
            user_text = self._concat_user(req.messages)
            resp = await chat.send_message(UserMessage(text=user_text))
            if not isinstance(resp, str) or not resp.strip():
                raise ProviderError("Malformed or empty Emergent response")
            text = resp
            return CompletionResponse(
                text=text,
                provider=self.provider,
                model=self.model,
                usage={},
            )
        except Exception as e:  # noqa: BLE001
            raise provider_exception(self.id, e) from None

    @staticmethod
    def _extract_system(messages: List[Message]) -> str:
        for m in messages:
            if m.role == "system":
                return m.content
        return ""

    @staticmethod
    def _concat_user(messages: List[Message]) -> str:
        parts: List[str] = []
        for m in messages:
            if m.role == "system":
                continue
            prefix = "USER:" if m.role == "user" else "ASSISTANT:"
            parts.append(f"{prefix}\n{m.content}")
        return "\n\n".join(parts) if parts else ""
