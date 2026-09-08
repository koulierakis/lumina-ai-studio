"""Hugging Face / fal adapter for LUMINA Video Studio.

Text-to-video can use Hugging Face Inference Providers. Image-to-video is
routed directly to fal.ai because Hugging Face Inference Providers currently
expose Wan2.2-TI2V-5B as text-to-video only.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os

import httpx
from huggingface_hub import InferenceClient

from .base import GeneratedVideo, VideoGenerationInput, VideoProvider, VideoProviderCapabilities, VideoProviderError

logger = logging.getLogger("lumina.video.huggingface")


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
        return bool(
            os.environ.get("HF_TOKEN")
            or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
            or os.environ.get("FAL_KEY")
        )

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

    async def _generate_image_to_video_via_fal(self, spec: VideoGenerationInput) -> GeneratedVideo:
        fal_key = os.environ.get("FAL_KEY", "").strip()
        if not fal_key:
            raise VideoProviderError(
                self.name,
                "FAL_KEY is missing for image-to-video",
                "Image-to-video requires a fal.ai API key on the server.",
            )
        if not spec.source_images:
            raise VideoProviderError(self.name, "Source image missing", "Please upload a source image.")

        try:
            import fal_client
        except ImportError as exc:
            raise VideoProviderError(
                self.name,
                "fal-client dependency is missing",
                "The image-to-video engine is not installed correctly.",
            ) from exc

        mime = spec.source_mimes[0] if spec.source_mimes else "image/jpeg"
        encoded = base64.b64encode(spec.source_images[0]).decode("ascii")
        image_url = f"data:{mime};base64,{encoded}"
        endpoint = os.environ.get("FAL_VIDEO_I2V_ENDPOINT", "fal-ai/wan/v2.2-5b/image-to-video")

        fps = spec.fps if spec.fps in {12, 16, 24, 30, 60} else 24
        num_frames = max(17, min(161, int(spec.duration_seconds * fps) + 1))
        arguments = {
            "image_url": image_url,
            "prompt": spec.prompt,
            "negative_prompt": spec.negative_prompt or "",
            "num_frames": num_frames,
            "frames_per_second": fps,
            "image_size": "landscape_16_9" if spec.aspect_ratio == "16:9" else "portrait_16_9",
        }
        if spec.seed is not None:
            arguments["seed"] = spec.seed

        logger.info(
            "Starting direct fal image-to-video endpoint=%s duration=%ss fps=%s frames=%s aspect_ratio=%s source_bytes=%s",
            endpoint,
            spec.duration_seconds,
            fps,
            num_frames,
            spec.aspect_ratio,
            len(spec.source_images[0]),
        )

        previous_fal_key = os.environ.get("FAL_KEY")
        os.environ["FAL_KEY"] = fal_key
        try:
            result = await asyncio.to_thread(
                fal_client.subscribe,
                endpoint,
                arguments=arguments,
                with_logs=True,
            )
        finally:
            if previous_fal_key is None:
                os.environ.pop("FAL_KEY", None)
            else:
                os.environ["FAL_KEY"] = previous_fal_key

        video_url = ((result or {}).get("video") or {}).get("url")
        if not video_url:
            raise VideoProviderError(
                self.name,
                f"fal.ai returned no video URL: {result!r}",
                "The video provider returned an invalid result.",
            )

        timeout = float(os.environ.get("HF_VIDEO_TIMEOUT_SECONDS", "600"))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, trust_env=False) as client:
            response = await client.get(video_url)
            response.raise_for_status()
            video_bytes = response.content
        if not video_bytes:
            raise VideoProviderError(
                self.name,
                "fal.ai returned an empty video",
                "The video engine returned an empty result.",
            )

        logger.info("Direct fal image-to-video completed endpoint=%s output_bytes=%s", endpoint, len(video_bytes))
        return GeneratedVideo(
            data=video_bytes,
            mime_type="video/mp4",
            preview_kind="video",
            duration_seconds=spec.duration_seconds,
            resolution=spec.resolution,
            metadata={"provider": "fal-ai-direct", "endpoint": endpoint, "mode": spec.mode},
        )

    async def generate(self, spec: VideoGenerationInput) -> GeneratedVideo:
        if not self.is_configured():
            raise VideoProviderError(self.name, "Video credentials are missing", "Video generation is not configured.")

        model = "unknown"
        provider_name = "unknown"
        try:
            if spec.mode == "image-to-video":
                return await self._generate_image_to_video_via_fal(spec)

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
                raise VideoProviderError(self.name, "Hugging Face returned an empty video", "The video engine returned an empty result.")

            logger.info("Hugging Face video completed provider=%s model=%s output_bytes=%s", provider_name, model, len(video_bytes))
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
            retryable = any(marker in message.lower() for marker in ("timeout", "timed out", "429", "503", "temporarily unavailable", "rate limit", "loading"))
            raise VideoProviderError(self.name, message, "Video generation failed. Please try again.", retryable=retryable) from exc
