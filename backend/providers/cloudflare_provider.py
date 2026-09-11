"""Cloudflare Workers AI FLUX.1 Schnell image provider."""
from __future__ import annotations
import asyncio
import base64
import os
import httpx
from .base import ErrorKind, GeneratedImage, GenerationInput, ImageProvider, ProviderCapabilities, ProviderError, ProviderInvalidResponseError

MODEL = "@cf/black-forest-labs/flux-1-schnell"

class CloudflareFluxProvider(ImageProvider):
    name = "cloudflare"
    priority = 4
    capabilities = ProviderCapabilities(generation=True, editing=False, identity_references=False, masks=False, multiple_outputs=True, aspect_ratios=("1:1",), models=(MODEL,), maximum_reference_images=0, maximum_outputs=4)

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.getenv("CLOUDFLARE_API_TOKEN", "").strip() and os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip())

    async def _one(self, spec: GenerationInput, seed: int | None) -> GeneratedImage:
        token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip(); account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
        if not token or not account_id:
            raise ProviderError(self.name, "Cloudflare Workers AI credentials are not configured.", kind=ErrorKind.AUTH, safe_message="Cloudflare Workers AI is not configured.")
        if spec.reference_images:
            raise ProviderError(self.name, "Reference images are unsupported.", kind=ErrorKind.UNSUPPORTED, safe_message="Cloudflare FLUX.1 Schnell supports text-to-image only.")
        payload = {"prompt": spec.prompt.strip(), "steps": 4}
        if seed is not None: payload["seed"] = int(seed)
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{MODEL}"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0), trust_env=False) as client:
                response = await client.post(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderError(self.name, str(exc), kind=ErrorKind.TIMEOUT, retryable=True, safe_message="Cloudflare image generation timed out.") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, str(exc), kind=ErrorKind.UNAVAILABLE, retryable=True, safe_message="Cloudflare Workers AI is temporarily unavailable.") from exc
        if not 200 <= response.status_code < 300:
            kind = ErrorKind.AUTH if response.status_code in {401, 403} else ErrorKind.RATE_LIMIT if response.status_code == 429 else ErrorKind.UNAVAILABLE
            raise ProviderError(self.name, f"Cloudflare HTTP {response.status_code}", kind=kind, retryable=response.status_code in {429,500,502,503,504}, status_code=response.status_code, safe_message="Cloudflare Workers AI could not complete the image request.")
        try:
            envelope = response.json(); result = envelope.get("result", envelope) if isinstance(envelope, dict) else {}; encoded = result.get("image") if isinstance(result, dict) else None; data = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise ProviderInvalidResponseError(self.name, "Cloudflare returned an invalid image response.") from exc
        if not data: raise ProviderInvalidResponseError(self.name, "Cloudflare returned an empty image.")
        return GeneratedImage(data=data, mime_type="image/jpeg")

    async def generate(self, spec: GenerationInput) -> list[GeneratedImage]:
        if spec.mode not in {"text-to-image", "generate", ""}: raise ProviderError(self.name, "Unsupported mode.", kind=ErrorKind.UNSUPPORTED)
        if not spec.prompt.strip(): raise ProviderError(self.name, "Prompt is required.", kind=ErrorKind.INVALID_REQUEST)
        count = max(1, min(int(spec.count or 1), self.capabilities.maximum_outputs))
        return await asyncio.gather(*(self._one(spec, None if spec.seed is None else int(spec.seed) + i) for i in range(count)))
