"""OpenAI Images provider using the public Images API."""
from __future__ import annotations

import asyncio
import base64
import io
import os
from typing import List

import requests

from .base import ErrorKind, GeneratedImage, GenerationInput, ImageProvider, ProviderCapabilities, ProviderError


class OpenAIImageProvider(ImageProvider):
    name = "openai"
    priority = 20
    capabilities = ProviderCapabilities(
        generation=True,
        editing=True,
        # The current adapter does not submit reference images.
        identity_references=False,
        masks=True,
        aspect_ratios=("1:1", "16:9", "9:16"),
        maximum_reference_images=0,
        maximum_outputs=4,
        models=("gpt-image-1",),
    )

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.getenv("OPENAI_API_KEY"))

    @staticmethod
    def _size(ratio: str) -> str:
        return {"16:9": "1536x1024", "9:16": "1024x1536"}.get(ratio, "1024x1024")

    def _sync_generate(self, spec: GenerationInput) -> List[GeneratedImage]:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise ProviderError(self.name, "OPENAI_API_KEY is missing", kind=ErrorKind.AUTH)
        prompt = " ".join(x for x in [spec.prompt, spec.scene, spec.outfit,
            f"Avoid: {spec.negative_prompt}" if spec.negative_prompt else ""] if x).strip()
        try:
            response = requests.post(
                "https://api.openai.com/v1/images/generations",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": spec.model or os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
                    "prompt": prompt,
                    "n": max(1, min(4, spec.count)),
                    "size": self._size(spec.aspect_ratio),
                },
                timeout=float(os.getenv("PROVIDER_TIMEOUT_SECONDS", "120")),
            )
        except requests.Timeout as exc:
            raise ProviderError(self.name, "OpenAI timed out", kind=ErrorKind.TIMEOUT, retryable=True) from exc
        except requests.RequestException as exc:
            raise ProviderError(self.name, str(exc), kind=ErrorKind.UNAVAILABLE, retryable=True) from exc

        if response.status_code >= 400:
            text = response.text.lower()
            if response.status_code == 401:
                kind, retryable = ErrorKind.AUTH, False
            elif response.status_code == 429 and "quota" in text:
                kind, retryable = ErrorKind.QUOTA, False
            elif response.status_code == 429:
                kind, retryable = ErrorKind.RATE_LIMIT, True
            elif response.status_code >= 500:
                kind, retryable = ErrorKind.UNAVAILABLE, True
            else:
                kind, retryable = ErrorKind.INVALID_REQUEST, False
            raise ProviderError(self.name, response.text[:500], kind=kind, retryable=retryable,
                                status_code=response.status_code)

        output: List[GeneratedImage] = []
        for item in response.json().get("data", []):
            if item.get("b64_json"):
                output.append(GeneratedImage(base64.b64decode(item["b64_json"]), "image/png"))
            elif item.get("url"):
                fetched = requests.get(item["url"], timeout=60)
                fetched.raise_for_status()
                output.append(GeneratedImage(fetched.content, fetched.headers.get("content-type", "image/png")))
        if not output:
            raise ProviderError(self.name, "OpenAI returned no image", kind=ErrorKind.UNAVAILABLE, retryable=True)
        return output

    async def generate(self, spec: GenerationInput) -> List[GeneratedImage]:
        return await asyncio.to_thread(self._sync_generate, spec)

    def _sync_edit(
        self,
        source_bytes: bytes,
        source_mime: str,
        instruction: str,
        mask_bytes: bytes | None,
        mask_mime: str | None,
    ) -> GeneratedImage:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise ProviderError(self.name, "OPENAI_API_KEY is missing", kind=ErrorKind.AUTH)
        files = {"image": ("source.png", io.BytesIO(source_bytes), source_mime or "image/png")}
        if mask_bytes:
            files["mask"] = ("mask.png", io.BytesIO(mask_bytes), mask_mime or "image/png")
        try:
            response = requests.post(
                "https://api.openai.com/v1/images/edits",
                headers={"Authorization": f"Bearer {key}"},
                data={"model": os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"), "prompt": instruction, "n": 1},
                files=files,
                timeout=float(os.getenv("PROVIDER_TIMEOUT_SECONDS", "120")),
            )
        except requests.Timeout as exc:
            raise ProviderError(self.name, "OpenAI timed out", kind=ErrorKind.TIMEOUT, retryable=True) from exc
        except requests.RequestException as exc:
            raise ProviderError(self.name, str(exc), kind=ErrorKind.UNAVAILABLE, retryable=True) from exc
        if response.status_code >= 400:
            text = response.text.lower()
            if response.status_code in {401, 403}:
                kind, retryable = ErrorKind.AUTH, False
            elif response.status_code == 429 and "quota" in text:
                kind, retryable = ErrorKind.QUOTA, True
            elif response.status_code == 429:
                kind, retryable = ErrorKind.RATE_LIMIT, True
            elif response.status_code >= 500:
                kind, retryable = ErrorKind.UNAVAILABLE, True
            else:
                kind, retryable = ErrorKind.INVALID_REQUEST, False
            raise ProviderError(self.name, response.text[:500], kind=kind, retryable=retryable, status_code=response.status_code)
        data = response.json().get("data", [])
        if not data or not data[0].get("b64_json"):
            raise ProviderError(self.name, "OpenAI returned no image", kind=ErrorKind.UNAVAILABLE, retryable=True)
        return GeneratedImage(base64.b64decode(data[0]["b64_json"]), "image/png")

    async def edit(
        self,
        source_bytes: bytes,
        source_mime: str,
        instruction: str,
        mask_bytes: bytes | None = None,
        mask_mime: str | None = "image/png",
        identity_refs: list[bytes] | None = None,
    ) -> GeneratedImage:
        return await asyncio.to_thread(self._sync_edit, source_bytes, source_mime, instruction, mask_bytes, mask_mime)
