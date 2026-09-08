"""Free Hugging Face Gradio provider for FLUX.1 [schnell]."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx
from gradio_client import Client

from .base import (
    ErrorKind,
    GeneratedImage,
    GenerationInput,
    ImageProvider,
    ProviderCapabilities,
    ProviderError,
    ProviderInvalidResponseError,
)


DEFAULT_FLUX_SPACE = "black-forest-labs/FLUX.1-schnell"
DEFAULT_FLUX_API_NAME = "/predict"


class FluxHFProvider(ImageProvider):
    """Text-to-image generation through the public FLUX.1 schnell HF Space."""

    name = "flux"
    priority = 5
    capabilities = ProviderCapabilities(
        generation=True,
        editing=False,
        identity_references=False,
        masks=False,
        multiple_outputs=True,
        aspect_ratios=("1:1", "16:9", "9:16", "4:5", "3:2"),
        models=("black-forest-labs/FLUX.1-schnell",),
        maximum_reference_images=0,
        maximum_outputs=4,
    )

    @classmethod
    def is_configured(cls) -> bool:
        # Public Space requires no paid API key. HF_TOKEN is optional and can
        # be supplied only to use an authenticated Hugging Face session/quota.
        return True

    @staticmethod
    def _dimensions(aspect_ratio: str, resolution: str) -> tuple[int, int]:
        try:
            base = int(str(resolution).lower().replace("px", "").strip())
        except (TypeError, ValueError):
            base = 1024
        base = max(512, min(base, 1536))

        ratios = {
            "1:1": (1, 1),
            "16:9": (16, 9),
            "9:16": (9, 16),
            "4:5": (4, 5),
            "3:2": (3, 2),
        }
        rw, rh = ratios.get(aspect_ratio, (1, 1))
        if rw >= rh:
            width = base
            height = round(base * rh / rw)
        else:
            height = base
            width = round(base * rw / rh)

        def snap(value: int) -> int:
            return max(256, min(2048, int(round(value / 32) * 32)))

        return snap(width), snap(height)

    @staticmethod
    def _clean_text_to_image_prompt(prompt: str) -> str:
        """Return only the user's prompt when no identity/reference image is used."""
        value = (prompt or "").strip()
        marker = "User prompt:"
        if marker in value:
            value = value.rsplit(marker, 1)[1].strip()
        return value

    async def _read_image(self, value, timeout: float) -> bytes:
        # The Space returns (image_path, seed); use the first output.
        if isinstance(value, (tuple, list)) and value:
            value = value[0]
        if isinstance(value, dict):
            value = value.get("path") or value.get("url") or value.get("image")

        if not isinstance(value, str) or not value:
            raise ProviderInvalidResponseError(
                self.name,
                f"FLUX Space returned an invalid image result: {value!r}",
            )

        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"}:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, trust_env=False) as client:
                response = await client.get(value)
                response.raise_for_status()
                return response.content

        path = Path(value)
        if not path.exists():
            raise ProviderInvalidResponseError(self.name, f"FLUX output file does not exist: {value}")
        return await asyncio.to_thread(path.read_bytes)

    async def generate(self, spec: GenerationInput) -> list[GeneratedImage]:
        if spec.mode not in {"text-to-image", "generate", ""}:
            raise ProviderError(
                self.name,
                f"FLUX.1 schnell does not support mode={spec.mode!r}",
                kind=ErrorKind.UNSUPPORTED,
                retryable=False,
                safe_message="FLUX.1 schnell supports text-to-image generation only.",
            )

        reference_images = list(getattr(spec, "reference_images", None) or [])
        if reference_images:
            raise ProviderError(
                self.name,
                "FLUX.1 schnell public Space does not accept reference images.",
                kind=ErrorKind.UNSUPPORTED,
                retryable=False,
                safe_message="This FLUX provider does not support reference-image generation.",
            )

        prediction_prompt = self._clean_text_to_image_prompt(spec.prompt)
        if not prediction_prompt:
            raise ProviderError(
                self.name,
                "Prompt is required for FLUX text-to-image generation.",
                kind=ErrorKind.INVALID_REQUEST,
                retryable=False,
                safe_message="Please enter a prompt before generating an image.",
            )

        space = os.getenv("HF_GRADIO_FLUX_SPACE", DEFAULT_FLUX_SPACE).strip()
        api_name = os.getenv("HF_GRADIO_FLUX_API_NAME", DEFAULT_FLUX_API_NAME).strip() or DEFAULT_FLUX_API_NAME
        token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACEHUB_API_TOKEN")
        timeout = float(os.getenv("HF_IMAGE_TIMEOUT_SECONDS", "300"))
        steps = max(1, min(int(os.getenv("HF_FLUX_STEPS", "4")), 8))
        width, height = self._dimensions(spec.aspect_ratio, spec.resolution)
        count = max(1, min(int(spec.count or 1), self.capabilities.maximum_outputs))

        client_kwargs = {"download_files": True, "verbose": False}
        if token:
            client_kwargs["hf_token"] = token

        client = Client(space, **client_kwargs)
        images: list[GeneratedImage] = []

        for _index in range(count):
            def run_prediction():
                return client.predict(
                    prompt=prediction_prompt,
                    seed=0,
                    randomize_seed=True,
                    width=width,
                    height=height,
                    num_inference_steps=steps,
                    api_name=api_name,
                )

            try:
                result = await asyncio.wait_for(asyncio.to_thread(run_prediction), timeout=timeout)
                image_bytes = await self._read_image(result, timeout)
            except ProviderError:
                raise
            except asyncio.TimeoutError as exc:
                raise ProviderError(
                    self.name,
                    "FLUX Hugging Face Space timed out.",
                    kind=ErrorKind.TIMEOUT,
                    retryable=True,
                    safe_message="The free FLUX image service timed out. Please try again.",
                ) from exc
            except Exception as exc:
                message = str(exc)
                retryable = any(marker in message.lower() for marker in ("429", "503", "queue", "quota", "zero gpu", "timeout", "timed out"))
                raise ProviderError(
                    self.name,
                    message,
                    kind=ErrorKind.UNAVAILABLE,
                    retryable=retryable,
                    safe_message="The free FLUX image service is temporarily unavailable.",
                ) from exc

            if not image_bytes:
                raise ProviderInvalidResponseError(self.name, "FLUX Space returned an empty image.")
            images.append(GeneratedImage(data=image_bytes, mime_type="image/png"))

        return images
