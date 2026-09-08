"""Hugging Face Inference adapter for LUMINA Video Studio."""
from __future__ import annotations

import logging
import os

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
        return bool(os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN"))

    def _client(self) -> InferenceClient:
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
        if not token:
            raise VideoProviderError(self.name, "HF_TOKEN is missing", "Hugging Face video generation is not configured.")
        timeout = float(os.environ.get("HF_VIDEO_TIMEOUT_SECONDS", "600"))
        inference_provider = os.environ.get("HF_VIDEO_INFERENCE_PROVIDER", "fal-ai").strip() or "fal-ai"
        return InferenceClient(api_key=token, timeout=timeout, provider=inference_provider)

    async def generate(self, spec: VideoGenerationInput) -> GeneratedVideo:
        if not self.is_configured():
            raise VideoProviderError(self.name, "Hugging Face credentials are missing", "Hugging Face video generation is not configured.")

        model = "unknown"
        inference_provider = os.environ.get("HF_VIDEO_INFERENCE_PROVIDER", "fal-ai").strip() or "fal-ai"
        try:
            client = self._client()
            if spec.mode == "image-to-video":
                if not spec.source_images:
                    raise VideoProviderError(self.name, "Source image missing", "Please upload a source image.")
                # Wan2.2 TI2V-5B supports both text-to-video and image-to-video and is
                # available through Hugging Face Inference Providers. The larger A14B
                # I2V checkpoint is a Hub model but is not reliably serverless-routed.
                model = os.environ.get("HF_VIDEO_I2V_MODEL", "Wan-AI/Wan2.2-TI2V-5B")
                logger.info(
                    "Starting Hugging Face image-to-video provider=%s model=%s duration=%ss resolution=%s aspect_ratio=%s source_bytes=%s",
                    inference_provider,
                    model,
                    spec.duration_seconds,
                    spec.resolution,
                    spec.aspect_ratio,
                    len(spec.source_images[0]),
                )
                result = client.image_to_video(
                    spec.source_images[0],
                    prompt=spec.prompt,
                    negative_prompt=spec.negative_prompt or None,
                    model=model,
                    seed=spec.seed,
                )
            elif spec.mode == "text-to-video":
                model = os.environ.get("HF_VIDEO_T2V_MODEL", "Wan-AI/Wan2.2-TI2V-5B")
                logger.info(
                    "Starting Hugging Face text-to-video provider=%s model=%s duration=%ss resolution=%s aspect_ratio=%s",
                    inference_provider,
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
                raise VideoProviderError(self.name, f"Unsupported mode: {spec.mode}", "Hugging Face currently supports Text to Video and Image to Video.")

            if isinstance(result, bytes):
                video_bytes = result
            elif hasattr(result, "read"):
                video_bytes = result.read()
            else:
                video_bytes = bytes(result)
            if not video_bytes:
                raise VideoProviderError(self.name, "Hugging Face returned an empty video", "The video engine returned an empty result.")

            logger.info(
                "Hugging Face video completed provider=%s model=%s output_bytes=%s",
                inference_provider,
                model,
                len(video_bytes),
            )
            return GeneratedVideo(
                data=video_bytes,
                mime_type="video/mp4",
                preview_kind="video",
                duration_seconds=spec.duration_seconds,
                resolution=spec.resolution,
                metadata={"provider": self.name, "inference_provider": inference_provider, "model": model, "mode": spec.mode},
            )
        except VideoProviderError:
            raise
        except Exception as exc:
            message = str(exc)
            status_code = getattr(exc, "status_code", None)
            response = getattr(exc, "response", None)
            if status_code is None and response is not None:
                status_code = getattr(response, "status_code", None)
            response_text = ""
            if response is not None:
                try:
                    response_text = (getattr(response, "text", "") or "")[:2000]
                except Exception:
                    response_text = "<unavailable>"
            logger.exception(
                "Hugging Face video generation failed provider=%s model=%s mode=%s exception=%s status=%s response=%s message=%s",
                inference_provider,
                model,
                spec.mode,
                type(exc).__name__,
                status_code,
                response_text,
                message,
            )
            retryable = any(marker in message.lower() for marker in ("timeout", "timed out", "429", "503", "temporarily unavailable", "rate limit", "loading"))
            safe_message = "Hugging Face video generation failed. Please try again."
            if status_code in {401, 403}:
                safe_message = "Hugging Face rejected the video request. Check token permissions or inference-provider billing."
            elif status_code == 404:
                safe_message = "The selected Hugging Face video model is not available through the configured inference provider."
            elif status_code == 429:
                safe_message = "Hugging Face video generation is rate limited or has reached its provider quota. Please retry later."
            raise VideoProviderError(self.name, message, safe_message, retryable=retryable) from exc
