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
        return InferenceClient(api_key=token, timeout=timeout)

    async def generate(self, spec: VideoGenerationInput) -> GeneratedVideo:
        if not self.is_configured():
            raise VideoProviderError(self.name, "Hugging Face credentials are missing", "Hugging Face video generation is not configured.")

        model = "unknown"
        try:
            client = self._client()
            if spec.mode == "image-to-video":
                if not spec.source_images:
                    raise VideoProviderError(self.name, "Source image missing", "Please upload a source image.")
                model = os.environ.get("HF_VIDEO_I2V_MODEL", "Wan-AI/Wan2.2-I2V-A14B")
                logger.info(
                    "Starting Hugging Face image-to-video model=%s duration=%ss resolution=%s aspect_ratio=%s source_bytes=%s",
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
                # Wan 2.1 is the actual 1.3B T2V release; Wan 2.2 has no T2V-1.3B model ID.
                model = os.environ.get("HF_VIDEO_T2V_MODEL", "Wan-AI/Wan2.1-T2V-1.3B")
                logger.info(
                    "Starting Hugging Face text-to-video model=%s duration=%ss resolution=%s aspect_ratio=%s",
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

            logger.info("Hugging Face video completed model=%s output_bytes=%s", model, len(video_bytes))
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
            logger.exception("Hugging Face video generation failed model=%s mode=%s: %s", model, spec.mode, message)
            retryable = any(marker in message.lower() for marker in ("timeout", "timed out", "429", "503", "temporarily unavailable", "rate limit", "loading"))
            raise VideoProviderError(self.name, message, "Hugging Face video generation failed. Please try again.", retryable=retryable) from exc
