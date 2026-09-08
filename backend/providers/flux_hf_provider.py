"""Replicate-backed FLUX.1 [schnell] image provider."""
from __future__ import annotations

import asyncio
import os

import replicate

from .base import (
    ErrorKind,
    GeneratedImage,
    GenerationInput,
    ImageProvider,
    ProviderCapabilities,
    ProviderError,
    ProviderInvalidResponseError,
)


REPLICATE_FLUX_MODEL = "black-forest-labs/flux-schnell"


class FluxHFProvider(ImageProvider):
    """FLUX.1 schnell text-to-image generation through Replicate's official API."""

    name = "flux"
    priority = 5
    capabilities = ProviderCapabilities(
        generation=True,
        editing=False,
        identity_references=False,
        masks=False,
        multiple_outputs=True,
        aspect_ratios=("1:1", "16:9", "9:16", "4:5", "3:2"),
        models=(REPLICATE_FLUX_MODEL,),
        maximum_reference_images=0,
        maximum_outputs=4,
    )

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.getenv("REPLICATE_API_TOKEN", "").strip())

    @staticmethod
    def _clean_text_to_image_prompt(prompt: str) -> str:
        value = (prompt or "").strip()
        marker = "User prompt:"
        if marker in value:
            value = value.rsplit(marker, 1)[1].strip()
        return value

    @staticmethod
    def _read_output_bytes(value) -> bytes:
        if hasattr(value, "read"):
            data = value.read()
            if isinstance(data, bytes):
                return data
        raise ProviderInvalidResponseError("flux", "Replicate returned an invalid image output.")

    async def generate(self, spec: GenerationInput) -> list[GeneratedImage]:
        if spec.mode not in {"text-to-image", "generate", ""}:
            raise ProviderError(
                self.name,
                f"FLUX.1 schnell does not support mode={spec.mode!r}",
                kind=ErrorKind.UNSUPPORTED,
                retryable=False,
                safe_message="FLUX.1 schnell supports text-to-image generation only.",
            )

        if list(getattr(spec, "reference_images", None) or []):
            raise ProviderError(
                self.name,
                "Replicate FLUX Schnell text-to-image does not accept reference images.",
                kind=ErrorKind.UNSUPPORTED,
                retryable=False,
                safe_message="This FLUX provider does not support reference-image generation.",
            )

        token = os.getenv("REPLICATE_API_TOKEN", "").strip()
        if not token:
            raise ProviderError(
                self.name,
                "REPLICATE_API_TOKEN is not configured.",
                kind=ErrorKind.AUTHENTICATION,
                retryable=False,
                status_code=401,
                safe_message="Replicate API credentials are not configured.",
            )

        prompt = self._clean_text_to_image_prompt(spec.prompt)
        if not prompt:
            raise ProviderError(
                self.name,
                "Prompt is required for FLUX text-to-image generation.",
                kind=ErrorKind.INVALID_REQUEST,
                retryable=False,
                safe_message="Please enter a prompt before generating an image.",
            )

        count = max(1, min(int(spec.count or 1), self.capabilities.maximum_outputs))
        input_payload = {
            "prompt": prompt,
            "aspect_ratio": spec.aspect_ratio or "1:1",
            "num_outputs": count,
            "num_inference_steps": 4,
            "output_format": "png",
        }
        if spec.seed is not None:
            input_payload["seed"] = int(spec.seed)

        try:
            # Replicate reads REPLICATE_API_TOKEN from the environment.
            output = await asyncio.to_thread(
                replicate.run,
                REPLICATE_FLUX_MODEL,
                input=input_payload,
            )
            values = list(output or [])
            if not values:
                raise ProviderInvalidResponseError(self.name, "Replicate returned no FLUX images.")
            images = [
                GeneratedImage(data=await asyncio.to_thread(self._read_output_bytes, value), mime_type="image/png")
                for value in values
            ]
            return images
        except ProviderError:
            raise
        except Exception as exc:
            message = str(exc)
            lowered = message.lower()
            if any(marker in lowered for marker in ("401", "unauthorized", "authentication", "api token")):
                kind = ErrorKind.AUTHENTICATION
                retryable = False
                safe = "Replicate rejected the API credentials."
            elif any(marker in lowered for marker in ("402", "payment", "billing", "credit", "quota")):
                kind = ErrorKind.QUOTA
                retryable = False
                safe = "Replicate billing or quota is unavailable for this request."
            elif any(marker in lowered for marker in ("429", "rate limit", "too many requests")):
                kind = ErrorKind.RATE_LIMIT
                retryable = True
                safe = "Replicate is rate-limiting image generation. Please try again shortly."
            elif any(marker in lowered for marker in ("timeout", "timed out")):
                kind = ErrorKind.TIMEOUT
                retryable = True
                safe = "Replicate image generation timed out. Please try again."
            else:
                kind = ErrorKind.UNAVAILABLE
                retryable = True
                safe = "Replicate FLUX image generation is temporarily unavailable."
            raise ProviderError(
                self.name,
                message,
                kind=kind,
                retryable=retryable,
                safe_message=safe,
            ) from exc
