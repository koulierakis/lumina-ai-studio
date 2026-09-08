"""Hugging Face adapter for LUMINA Video Studio.

Text-to-video uses Hugging Face Inference Providers. Image-to-video uses a
public Hugging Face Gradio Space so it does not require fal.ai credits.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx
from gradio_client import Client, handle_file
from huggingface_hub import InferenceClient

from .base import GeneratedVideo, VideoGenerationInput, VideoProvider, VideoProviderCapabilities, VideoProviderError

logger = logging.getLogger("lumina.video.huggingface")

DEFAULT_I2V_SPACE = "zerogpu-aoti/wan2-2-fp8da-aoti-faster"
DEFAULT_I2V_API_NAME = "/generate_video"


class HuggingFaceVideoProvider(VideoProvider):
    name = "huggingface"
    capabilities = VideoProviderCapabilities(
        text_to_video=True,
        image_to_video=True,
        multiple_images=False,
        extension=False,
        variation=False,
        interpolation=False,
        editing=False,
        output_formats=("video/mp4",),
        resolutions=("720p",),
        durations=(3, 5, 8),
        aspect_ratios=("16:9", "9:16"),
        cancellation=False,
        max_image_inputs=1,
        max_prompt_length=1000,
    )

    @classmethod
    def is_configured(cls) -> bool:
        # Public Gradio I2V works without a token. HF_TOKEN remains optional and
        # is only required for text-to-video or authenticated Space quota.
        return True

    def _hf_client(self) -> InferenceClient:
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
        if not token:
            raise VideoProviderError(
                self.name,
                "HF_TOKEN is missing",
                "Hugging Face text-to-video is not configured.",
            )
        timeout = float(os.environ.get("HF_VIDEO_TIMEOUT_SECONDS", "600"))
        provider = os.environ.get("HF_VIDEO_PROVIDER", "fal-ai")
        return InferenceClient(provider=provider, api_key=token, timeout=timeout)

    @staticmethod
    def _suffix_for_mime(mime: str) -> str:
        mime = (mime or "").lower()
        if "png" in mime:
            return ".png"
        if "webp" in mime:
            return ".webp"
        return ".jpg"

    async def _read_gradio_video(self, value, timeout: float) -> bytes:
        if isinstance(value, (tuple, list)) and value:
            value = value[0]
        if isinstance(value, dict):
            value = value.get("path") or value.get("url") or value.get("video")

        if not isinstance(value, str) or not value:
            raise VideoProviderError(
                self.name,
                f"Gradio Space returned an invalid video result: {value!r}",
                "The free Hugging Face Space returned an invalid result.",
            )

        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"}:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, trust_env=False) as client:
                response = await client.get(value)
                response.raise_for_status()
                return response.content

        path = Path(value)
        if not path.exists():
            raise VideoProviderError(
                self.name,
                f"Gradio result file does not exist: {value}",
                "The free Hugging Face Space returned a missing video file.",
            )
        return await asyncio.to_thread(path.read_bytes)

    async def _generate_image_to_video_via_gradio(self, spec: VideoGenerationInput) -> GeneratedVideo:
        if not spec.source_images:
            raise VideoProviderError(self.name, "Source image missing", "Please upload a source image.")

        space = os.environ.get("HF_GRADIO_I2V_SPACE", DEFAULT_I2V_SPACE).strip()
        api_name = os.environ.get("HF_GRADIO_I2V_API_NAME", DEFAULT_I2V_API_NAME).strip()
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
        timeout = float(os.environ.get("HF_VIDEO_TIMEOUT_SECONDS", "900"))

        # The current ZeroGPU Space accepts up to 5 seconds. Clamp older UI
        # presets rather than failing a request that asked for 8 seconds.
        duration = max(0.5, min(float(spec.duration_seconds), 5.0))
        seed = int(spec.seed if spec.seed is not None else 42)
        negative_prompt = spec.negative_prompt or ""
        steps = int(os.environ.get("HF_GRADIO_I2V_STEPS", "6"))
        guidance = float(os.environ.get("HF_GRADIO_I2V_GUIDANCE", "1"))

        suffix = self._suffix_for_mime(spec.source_mimes[0] if spec.source_mimes else "image/jpeg")
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as image_file:
                image_file.write(spec.source_images[0])
                temp_path = image_file.name

            logger.info(
                "Starting Hugging Face Gradio image-to-video space=%s api_name=%s duration=%ss steps=%s source_bytes=%s",
                space,
                api_name,
                duration,
                steps,
                len(spec.source_images[0]),
            )

            def run_prediction():
                client_kwargs = {"download_files": True, "verbose": False}
                if token:
                    client_kwargs["hf_token"] = token
                client = Client(space, **client_kwargs)
                return client.predict(
                    handle_file(temp_path),
                    spec.prompt,
                    steps,
                    negative_prompt,
                    duration,
                    guidance,
                    guidance,
                    seed,
                    False,
                    api_name=api_name,
                )

            result = await asyncio.wait_for(asyncio.to_thread(run_prediction), timeout=timeout)
            video_bytes = await self._read_gradio_video(result, timeout)
            if not video_bytes:
                raise VideoProviderError(
                    self.name,
                    "Gradio Space returned an empty video",
                    "The free Hugging Face Space returned an empty result.",
                )

            logger.info(
                "Hugging Face Gradio image-to-video completed space=%s output_bytes=%s",
                space,
                len(video_bytes),
            )
            return GeneratedVideo(
                data=video_bytes,
                mime_type="video/mp4",
                preview_kind="video",
                duration_seconds=duration,
                resolution=spec.resolution,
                metadata={
                    "provider": "huggingface-gradio-space",
                    "space": space,
                    "api_name": api_name,
                    "mode": spec.mode,
                },
            )
        finally:
            if temp_path:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except Exception:
                    logger.warning("Could not remove temporary I2V source image: %s", temp_path)

    async def generate(self, spec: VideoGenerationInput) -> GeneratedVideo:
        model = "unknown"
        provider_name = "unknown"
        try:
            if spec.mode == "image-to-video":
                return await self._generate_image_to_video_via_gradio(spec)

            if spec.mode == "text-to-video":
                client = self._hf_client()
                model = os.environ.get("HF_VIDEO_T2V_MODEL", "Wan-AI/Wan2.1-T2V-1.3B")
                provider_name = os.environ.get("HF_VIDEO_PROVIDER", "fal-ai")
                logger.info(
                    "Starting Hugging Face text-to-video provider=%s model=%s duration=%ss resolution=%s aspect_ratio=%s",
                    provider_name,
                    model,
                    spec.duration_seconds,
                    spec.resolution,
                    spec.aspect_ratio,
                )
                result = client.text_to_video(
                    spec.prompt,
                    model=model,
                    negative_prompt=[spec.negative_prompt] if spec.negative_prompt else None,
                    seed=spec.seed,
                )
            else:
                raise VideoProviderError(
                    self.name,
                    f"Unsupported mode: {spec.mode}",
                    "This provider supports Text to Video and Image to Video.",
                )

            if isinstance(result, bytes):
                video_bytes = result
            elif hasattr(result, "read"):
                video_bytes = result.read()
            else:
                video_bytes = bytes(result)
            if not video_bytes:
                raise VideoProviderError(
                    self.name,
                    "Hugging Face returned an empty video",
                    "The video engine returned an empty result.",
                )

            logger.info(
                "Hugging Face video completed provider=%s model=%s output_bytes=%s",
                provider_name,
                model,
                len(video_bytes),
            )
            return GeneratedVideo(
                data=video_bytes,
                mime_type="video/mp4",
                preview_kind="video",
                duration_seconds=spec.duration_seconds,
                resolution=spec.resolution,
                metadata={"provider": self.name, "model": model, "mode": spec.mode},
            )
        except VideoProviderError:
            raise
        except Exception as exc:
            message = str(exc)
            status = getattr(getattr(exc, "response", None), "status_code", None)
            response_text = getattr(getattr(exc, "response", None), "text", "") or ""
            logger.exception(
                "Hugging Face video generation failed provider=%s model=%s mode=%s exception=%s status=%s response=%s message=%s",
                provider_name,
                model,
                spec.mode,
                exc.__class__.__name__,
                status,
                response_text[:1000],
                message,
            )
            retryable = any(
                marker in message.lower()
                for marker in (
                    "timeout",
                    "timed out",
                    "429",
                    "503",
                    "temporarily unavailable",
                    "rate limit",
                    "loading",
                    "queue",
                    "quota",
                    "zero gpu",
                )
            )
            raise VideoProviderError(
                self.name,
                message,
                "Video generation failed. Please try again.",
                retryable=retryable,
            ) from exc
