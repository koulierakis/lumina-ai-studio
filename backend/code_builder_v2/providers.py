"""Multi-provider model routing for Lumina Code Builder.

Supports: OpenRouter (primary, 400+ models), Groq, HuggingFace, Local Ollama (fallback).
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


class ProviderError(RuntimeError):
    """Raised when a provider fails to generate."""


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
        if text.lower().startswith("json"):
            text = text[4:].lstrip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ProviderError("Model did not return a JSON object.")
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ProviderError("Model returned invalid JSON.") from exc

    if not isinstance(data, dict):
        raise ProviderError("Model JSON result must be an object.")
    return data


class ModelProvider(ABC):
    """Abstract base for model providers."""

    @abstractmethod
    def generate_json(self, prompt: str, model: Optional[str] = None) -> dict[str, Any]:
        """Generate structured JSON from prompt."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier."""


@dataclass(slots=True)
class OpenRouterProvider(ModelProvider):
    """OpenRouter - 400+ models via unified API."""

    api_key: str = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY", "").strip())
    default_model: str = "openai/gpt-4o-mini"
    timeout_seconds: int = 120
    http_referer: str = "https://lumina-code-builder.local"
    x_title: str = "Lumina Code Builder"

    def __post_init__(self):
        if not self.api_key:
            raise ProviderError("OPENROUTER_API_KEY not configured")

    @property
    def name(self) -> str:
        return "openrouter"

    def generate_json(self, prompt: str, model: Optional[str] = None) -> dict[str, Any]:
        try:
            from openrouter import OpenRouter
        except ImportError as exc:
            raise ProviderError("openrouter package not installed") from exc

        client = OpenRouter(api_key=self.api_key)
        response = client.chat.completions.create(
            model=model or self.default_model,
            messages=[
                {"role": "system", "content": "You are the Lumina Code Builder engine. Return only valid JSON with no markdown fences."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
            extra_headers={
                "HTTP-Referer": self.http_referer,
                "X-Title": self.x_title,
            },
        )
        raw = response.choices[0].message.content
        if not isinstance(raw, str) or not raw.strip():
            raise ProviderError("OpenRouter returned empty response")
        return _extract_json_object(raw)


@dataclass(slots=True)
class GroqProvider(ModelProvider):
    """Groq - fast inference for open models."""

    api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", "").strip())
    default_model: str = "openai/gpt-oss-120b"
    timeout_seconds: int = 120

    def __post_init__(self):
        if not self.api_key:
            raise ProviderError("GROQ_API_KEY not configured")

    @property
    def name(self) -> str:
        return "groq"

    def generate_json(self, prompt: str, model: Optional[str] = None) -> dict[str, Any]:
        try:
            from groq import Groq
        except ImportError as exc:
            raise ProviderError("groq package not installed") from exc

        client = Groq(api_key=self.api_key, timeout=self.timeout_seconds)
        response = client.chat.completions.create(
            model=model or self.default_model,
            messages=[
                {"role": "system", "content": "You are the Lumina Code Builder engine. Return only valid JSON with no markdown fences."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        if not isinstance(raw, str) or not raw.strip():
            raise ProviderError("Groq returned empty response")
        return _extract_json_object(raw)


@dataclass(slots=True)
class HuggingFaceProvider(ModelProvider):
    """Hugging Face Inference API."""

    token: str = field(default_factory=lambda: (
        os.getenv("HF_TOKEN", "").strip() or os.getenv("HUGGINGFACEHUB_API_TOKEN", "").strip()
    ))
    default_model: str = "Qwen/Qwen2.5-Coder-32B-Instruct"
    timeout_seconds: int = 180

    def __post_init__(self):
        if not self.token:
            raise ProviderError("HF_TOKEN not configured")

    @property
    def name(self) -> str:
        return "huggingface"

    def generate_json(self, prompt: str, model: Optional[str] = None) -> dict[str, Any]:
        try:
            from huggingface_hub import InferenceClient
        except ImportError as exc:
            raise ProviderError("huggingface_hub package not installed") from exc

        client = InferenceClient(model=model or self.default_model, token=self.token, timeout=self.timeout_seconds)
        try:
            response = client.chat_completion(
                messages=[
                    {"role": "system", "content": "You are the Lumina Code Builder engine. Return only valid JSON with no markdown fences."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=8192,
                temperature=0.1,
            )
            raw = response.choices[0].message.content
        except Exception:
            raw = client.text_generation(prompt, max_new_tokens=8192, temperature=0.1, return_full_text=False)

        if not isinstance(raw, str) or not raw.strip():
            raise ProviderError("Hugging Face returned empty response")
        return _extract_json_object(raw)


@dataclass(slots=True)
class OllamaProvider(ModelProvider):
    """Local Ollama server fallback."""

    base_url: str = "http://127.0.0.1:11434"
    default_model: str = "qwen2.5-coder:1.5b"
    timeout_seconds: int = 600

    @property
    def name(self) -> str:
        return "ollama"

    def generate_json(self, prompt: str, model: Optional[str] = None) -> dict[str, Any]:
        model_name = model or self.default_model
        url = f"{self.base_url}/api/generate"

        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,
                "num_ctx": 8192,
                "num_predict": 8192,
            }
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise ProviderError(f"Local Ollama request failed: {exc}") from exc
        except Exception as exc:
            raise ProviderError(f"Local Ollama request failed: {exc}") from exc

        if not isinstance(raw, str) or not raw.strip():
            raise ProviderError("Local Ollama returned empty response")

        try:
            parsed = json.loads(raw)
            if "response" in parsed:
                raw = parsed["response"]
        except json.JSONDecodeError:
            pass

        return _extract_json_object(raw)


@dataclass(slots=True)
class ModelRouter:
    """Routes requests to providers with automatic fallback.

    Priority: OpenRouter -> Groq -> HuggingFace -> Ollama
    """

    providers: list[ModelProvider] = field(default_factory=list)

    def __post_init__(self):
        if not self.providers:
            self.providers = self._default_providers()

    @staticmethod
    def _default_providers() -> list[ModelProvider]:
        providers = []

        # OpenRouter (primary - 400+ models)
        if os.getenv("OPENROUTER_API_KEY", "").strip():
            try:
                providers.append(OpenRouterProvider())
            except ProviderError:
                pass

        # Groq (fast alternative)
        if os.getenv("GROQ_API_KEY", "").strip():
            try:
                providers.append(GroqProvider())
            except ProviderError:
                pass

        # HuggingFace
        if os.getenv("HF_TOKEN", "").strip() or os.getenv("HUGGINGFACEHUB_API_TOKEN", "").strip():
            try:
                providers.append(HuggingFaceProvider())
            except ProviderError:
                pass

        # Local Ollama (always available as fallback)
        try:
            providers.append(OllamaProvider())
        except ProviderError:
            pass

        if not providers:
            raise ProviderError("No model providers configured. Set OPENROUTER_API_KEY, GROQ_API_KEY, HF_TOKEN, or run local Ollama.")

        return providers

    def generate_json(self, prompt: str, model: Optional[str] = None, preferred_provider: Optional[str] = None) -> dict[str, Any]:
        """Generate with automatic fallback through provider chain."""

        last_error: Optional[Exception] = None

        # If preferred provider specified, try it first
        if preferred_provider:
            for provider in self.providers:
                if provider.name == preferred_provider:
                    try:
                        return provider.generate_json(prompt, model)
                    except ProviderError as e:
                        last_error = e
                        break

        # Try all providers in order
        for provider in self.providers:
            if preferred_provider and provider.name == preferred_provider:
                continue  # Already tried
            try:
                return provider.generate_json(prompt, model)
            except ProviderError as e:
                last_error = e
                continue

        raise ProviderError(f"All providers failed. Last error: {last_error}")

    def get_provider_names(self) -> list[str]:
        return [p.name for p in self.providers]