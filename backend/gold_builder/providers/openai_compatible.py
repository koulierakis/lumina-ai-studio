"""Config-driven OpenAI-compatible provider adapters.

Covers NVIDIA NIM, OpenRouter, Mistral, Hugging Face router, Ollama and arbitrary
OpenAI-compatible endpoints without adding vendor-specific engine coupling.
"""
from __future__ import annotations

import os
from typing import Iterable

from .base import CompletionRequest, CompletionResponse, LLMProvider, ProviderError, provider_exception

# Cloudflare Workers AI models that officially support JSON Mode (OpenAI-style
# `response_format={"type": "json_object"}`). The engine's planner and diagnosis
# flows depend on structured output, so the Cloudflare default must be in this
# set. Source: https://developers.cloudflare.com/workers-ai/features/json-mode/
CLOUDFLARE_JSON_MODE_MODELS = frozenset({
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "@cf/meta/llama-3-8b-instruct",
    "@cf/meta/llama-3.1-8b-instruct",
    "@hf/nousresearch/hermes-2-pro-mistral-7b",
    "@hf/thebloke/deepseek-coder-6.7b-instruct-awq",
    "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b",
})
CLOUDFLARE_DEFAULT_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        *,
        provider: str,
        model: str,
        base_url: str,
        api_key_env: str | None = None,
        enabled_env: str | None = None,
        capabilities: Iterable[str] = ("text", "json", "coding", "reasoning"),
    ):
        self.provider = provider
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.enabled_env = enabled_env
        self.capabilities = frozenset(capabilities)
        self.id = f"{provider}-{model}".replace("/", "-").replace(":", "-")

    def available(self) -> bool:
        if self.enabled_env and os.environ.get(self.enabled_env, "").strip().lower() not in {"1", "true", "yes"}:
            return False
        if not self.model or not self.base_url:
            return False
        if self.api_key_env:
            return bool(os.environ.get(self.api_key_env, "").strip())
        return True

    async def complete(self, req: CompletionRequest) -> CompletionResponse:
        if not self.available():
            raise ProviderError(f"{self.provider} provider is not configured")
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ProviderError("openai package not installed") from exc

        key = os.environ.get(self.api_key_env, "") if self.api_key_env else os.environ.get("OPENAI_COMPAT_API_KEY", "local")
        client = AsyncOpenAI(
            api_key=key or "local",
            base_url=self.base_url,
            timeout=60.0,
            max_retries=0,
        )
        messages = [{"role": m.role, "content": m.content} for m in req.messages]
        if req.system and not any(m["role"] == "system" for m in messages):
            messages.insert(0, {"role": "system", "content": req.system})
        kwargs = {
            "model": self.model,
            "messages": messages,
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
        }
        if req.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self.provider == "nvidia":
            thinking = os.environ.get("NVIDIA_ENABLE_THINKING", "").strip().lower() in {"1", "true", "yes"}
            kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": thinking}}
        try:
            resp = await client.chat.completions.create(**kwargs)
            choice = resp.choices[0]
            text = choice.message.content or ""
            usage = getattr(resp, "usage", None)
            return CompletionResponse(
                text=text,
                provider=self.provider,
                model=self.model,
                finish_reason=getattr(choice, "finish_reason", None),
                usage={
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
                    "completion_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
                },
            )
        except Exception as exc:  # noqa: BLE001
            raise provider_exception(self.id, exc) from None
        finally:
            await client.close()


def configured_compatible_providers() -> list[LLMProvider]:
    providers: list[LLMProvider] = []

    # NVIDIA API Catalog exposes an OpenAI-compatible chat-completions API.
    # Keep this adapter configuration-driven so NVIDIA participates in the same
    # timeout, cooldown, health, and fallback semantics as the other vendors.
    nvidia_model = os.environ.get("NVIDIA_MODEL", "openai/gpt-oss-20b").strip()
    if nvidia_model and os.environ.get("NVIDIA_API_KEY", "").strip():
        providers.append(OpenAICompatibleProvider(
            provider="nvidia",
            model=nvidia_model,
            base_url=os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
            api_key_env="NVIDIA_API_KEY",
        ))

    # Cloudflare Workers AI exposes an OpenAI-compatible endpoint scoped to
    # the account. Keep credentials server-side and opt in only when both the
    # API token and account id are configured. The default model is on
    # Cloudflare's JSON Mode supported list so the planner/diagnosis flows can
    # request structured output; a model without JSON Mode would break those
    # core requests.
    cloudflare_model = os.environ.get("CLOUDFLARE_MODEL", CLOUDFLARE_DEFAULT_MODEL).strip()
    cloudflare_account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if cloudflare_model and cloudflare_account_id and os.environ.get("CLOUDFLARE_API_TOKEN", "").strip():
        providers.append(OpenAICompatibleProvider(
            provider="cloudflare",
            model=cloudflare_model,
            base_url=os.environ.get(
                "CLOUDFLARE_BASE_URL",
                f"https://api.cloudflare.com/client/v4/accounts/{cloudflare_account_id}/ai/v1",
            ),
            api_key_env="CLOUDFLARE_API_TOKEN",
        ))

    # SambaNova Cloud provides an OpenAI-compatible chat-completions API.
    sambanova_model = os.environ.get("SAMBANOVA_MODEL", "Meta-Llama-3.3-70B-Instruct").strip()
    if sambanova_model and os.environ.get("SAMBANOVA_API_KEY", "").strip():
        providers.append(OpenAICompatibleProvider(
            provider="sambanova",
            model=sambanova_model,
            base_url=os.environ.get("SAMBANOVA_BASE_URL", "https://api.sambanova.ai/v1"),
            api_key_env="SAMBANOVA_API_KEY",
        ))

    openrouter_model = os.environ.get("OPENROUTER_MODEL", "").strip()
    if openrouter_model and os.environ.get("OPENROUTER_API_KEY", "").strip():
        providers.append(OpenAICompatibleProvider(
            provider="openrouter",
            model=openrouter_model,
            base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            api_key_env="OPENROUTER_API_KEY",
        ))

    mistral_model = os.environ.get("MISTRAL_MODEL", "mistral-small-latest").strip()
    if os.environ.get("MISTRAL_API_KEY", "").strip():
        providers.append(OpenAICompatibleProvider(
            provider="mistral",
            model=mistral_model,
            base_url=os.environ.get("MISTRAL_BASE_URL", "https://api.mistral.ai/v1"),
            api_key_env="MISTRAL_API_KEY",
        ))

    hf_model = os.environ.get("HUGGINGFACE_MODEL", "").strip()
    hf_key_env = "HUGGINGFACE_API_KEY" if os.environ.get("HUGGINGFACE_API_KEY", "").strip() else "HF_TOKEN"
    if hf_model and os.environ.get(hf_key_env, "").strip():
        providers.append(OpenAICompatibleProvider(
            provider="huggingface",
            model=hf_model,
            base_url=os.environ.get("HUGGINGFACE_BASE_URL", "https://router.huggingface.co/v1"),
            api_key_env=hf_key_env,
        ))

    ollama_model = os.environ.get("OLLAMA_MODEL", "").strip()
    if ollama_model:
        providers.append(OpenAICompatibleProvider(
            provider="ollama",
            model=ollama_model,
            base_url=os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434/v1"),
        ))

    # FreeLLMAPI is a separately deployed OpenAI-compatible aggregator.  It is
    # deliberately opt-in and uses the aggregator default automatic fallback chain so
    # existing direct providers remain independent fallbacks.
    freellmapi_model = os.environ.get("FREELLMAPI_MODEL", "auto").strip()
    freellmapi_url = os.environ.get("FREELLMAPI_BASE_URL", "").strip()
    if freellmapi_model and freellmapi_url and os.environ.get("FREELLMAPI_API_KEY", "").strip():
        providers.append(OpenAICompatibleProvider(
            provider="freellmapi",
            model=freellmapi_model,
            base_url=freellmapi_url,
            api_key_env="FREELLMAPI_API_KEY",
        ))

    generic_model = os.environ.get("OPENAI_COMPAT_MODEL", "").strip()
    generic_url = os.environ.get("OPENAI_COMPAT_BASE_URL", "").strip()
    if generic_model and generic_url:
        providers.append(OpenAICompatibleProvider(
            provider=os.environ.get("OPENAI_COMPAT_PROVIDER", "openai-compatible"),
            model=generic_model,
            base_url=generic_url,
            api_key_env="OPENAI_COMPAT_API_KEY" if os.environ.get("OPENAI_COMPAT_API_KEY") else None,
        ))

    return providers
