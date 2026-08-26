"""Stable Diffusion/Comfy-compatible generic REST connector."""
from __future__ import annotations

import asyncio
import base64
import os

import requests

from .base import (
    ErrorKind,
    GeneratedImage,
    GenerationInput,
    ImageProvider,
    ProviderCapabilities,
    ProviderError,
)


class StableDiffusionProvider(ImageProvider):
    name = "stable-diffusion"
    priority = 50
    capabilities = ProviderCapabilities(
        generation=True, editing=False, identity_references=False,
        aspect_ratios=("1:1", "16:9", "9:16", "4:5", "3:2"),
        maximum_outputs=4,
        models=("configured-endpoint",),
    )

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.getenv("STABLE_DIFFUSION_URL"))

    @staticmethod
    def _dimensions(ratio: str) -> tuple[int, int]:
        return {
            "16:9": (1024, 576), "9:16": (576, 1024), "4:5": (768, 960),
            "3:2": (960, 640), "1:1": (768, 768),
        }.get(ratio, (768, 768))

    def _sync_generate(self, spec: GenerationInput) -> list[GeneratedImage]:
        url = os.getenv("STABLE_DIFFUSION_URL")
        if not url:
            raise ProviderError(self.name, "STABLE_DIFFUSION_URL is missing", kind=ErrorKind.AUTH)
        width, height = self._dimensions(spec.aspect_ratio)
        endpoint = url.rstrip("/")
        if not endpoint.endswith("/sdapi/v1/txt2img"):
            endpoint += "/sdapi/v1/txt2img"
        headers = {"Content-Type": "application/json"}
        if os.getenv("STABLE_DIFFUSION_API_KEY"):
            headers["Authorization"] = f"Bearer {os.environ['STABLE_DIFFUSION_API_KEY']}"
        try:
            response = requests.post(endpoint, headers=headers, json={
                "prompt": " ".join(filter(None, [spec.prompt, spec.scene, spec.outfit])),
                "negative_prompt": spec.negative_prompt,
                "batch_size": max(1, min(4, spec.count)),
                "width": width, "height": height,
                "steps": int(os.getenv("STABLE_DIFFUSION_STEPS", "24")),
            }, timeout=float(os.getenv("PROVIDER_TIMEOUT_SECONDS", "120")))
        except requests.Timeout as exc:
            raise ProviderError(self.name, "Stable Diffusion timed out", kind=ErrorKind.TIMEOUT, retryable=True) from exc
        except requests.RequestException as exc:
            raise ProviderError(self.name, str(exc), kind=ErrorKind.UNAVAILABLE, retryable=True) from exc
        if response.status_code >= 400:
            raise ProviderError(self.name, response.text[:500],
                                kind=ErrorKind.UNAVAILABLE if response.status_code >= 500 else ErrorKind.INVALID_REQUEST,
                                retryable=response.status_code >= 500, status_code=response.status_code)
        images = [GeneratedImage(base64.b64decode(raw.split(",")[-1]), "image/png")
                  for raw in response.json().get("images", [])]
        if not images:
            raise ProviderError(self.name, "Endpoint returned no images")
        return images

    async def generate(self, spec: GenerationInput) -> list[GeneratedImage]:
        if spec.reference_images:
            raise ProviderError(self.name, "This connector is configured for text-to-image only",
                                kind=ErrorKind.UNSUPPORTED)
        return await asyncio.to_thread(self._sync_generate, spec)


class LocalImageProvider(StableDiffusionProvider):
    name = "local"
