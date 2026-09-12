"""Optional Pollinations video adapter for LUMINA Video Studio.

Pollinations currently requires an API key for generation requests. This adapter
is therefore an *optional* fallback only; the primary no-key/no-credit path is
the public Hugging Face Gradio Space in ``huggingface_provider.py``.
"""
from __future__ import annotations

import logging
import os
from urllib.parse import quote

import httpx

from .base import GeneratedVideo, VideoGenerationInput, VideoProvider, VideoProviderCapabilities, VideoProviderError

logger = logging.getLogger("lumina.video.pollinations")


class PollinationsVideoProvider(VideoProvider):
    name = "pollinations"
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
        return bool(os.environ.get("POLLINATIONS_API_KEY", "").strip())

    @staticmethod
    def _dimensions(aspect_ratio: str) -> tuple[int, int]:
        return (720, 1280) if aspect_ratio == "9:16" else (1280, 720)

    async def _upload_source_image(self, client: httpx.AsyncClient, spec: VideoGenerationInput) -> str:
        if not spec.source_images:
            raise VideoProviderError(self.name, "Source image missing", "Please upload a source image.")
        mime = spec.source_mimes[0] if spec.source_mimes else "image/jpeg"
        extension = ".png" if "png" in mime else ".webp" if "webp" in mime else ".jpg"
        response = await client.post(
            "/upload",
            files={"file": (f"lumina-source{extension}", spec.source_images[0], mime)},
        )
        response.raise_for_status()
        payload = response.json()
        url = str(payload.get("url") or "").strip()
        if not url.startswith(("https://", "http://")):
            raise VideoProviderError(self.name, f"Invalid upload response: {payload!r}", "The fallback video engine could not accept the source image.")
        return url

    async def generate(self, spec: VideoGenerationInput) -> GeneratedVideo:
        api_key = os.environ.get("POLLINATIONS_API_KEY", "").strip()
        if not api_key:
            raise VideoProviderError(
                self.name,
                "POLLINATIONS_API_KEY is missing",
                "The optional Pollinations fallback is not configured.",
            )

        base_url = os.environ.get("POLLINATIONS_BASE_URL", "https://gen.pollinations.ai").strip().rstrip("/")
        model = os.environ.get("POLLINATIONS_VIDEO_MODEL", "wan-fast").strip() or "wan-fast"
        timeout = float(os.environ.get("POLLINATIONS_VIDEO_TIMEOUT_SECONDS", "300"))
        width, height = self._dimensions(spec.aspect_ratio)
        headers = {"Authorization": f"Bearer {api_key}"}

        try:
            async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=timeout, follow_redirects=True, trust_env=False) as client:
                image_url = None
                if spec.mode == "image-to-video":
                    image_url = await self._upload_source_image(client, spec)
                elif spec.mode != "text-to-video":
                    raise VideoProviderError(
                        self.name,
                        f"Unsupported mode: {spec.mode}",
                        "This fallback supports Text to Video and Image to Video.",
                    )

                params: dict[str, str | int] = {
                    "model": model,
                    "duration": max(1, min(int(spec.duration_seconds), 120)),
                    "aspectRatio": spec.aspect_ratio,
                    "width": width,
                    "height": height,
                    "audio": "false",
                }
                if spec.seed is not None:
                    params["seed"] = int(spec.seed)
                if image_url:
                    params["image"] = image_url

                response = await client.get(f"/video/{quote(spec.prompt, safe='')}", params=params)
                response.raise_for_status()
                video_bytes = response.content
                content_type = (response.headers.get("content-type") or "video/mp4").split(";", 1)[0].strip().lower()
                if not video_bytes:
                    raise VideoProviderError(self.name, "Pollinations returned an empty video", "The fallback video engine returned an empty result.")
                if content_type != "video/mp4" and not video_bytes.startswith((b"\x00\x00\x00", b"ftyp")):
                    raise VideoProviderError(self.name, f"Unexpected content type: {content_type}", "The fallback video engine returned an invalid video.")

                logger.info("Pollinations video completed model=%s mode=%s output_bytes=%s", model, spec.mode, len(video_bytes))
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
            status = getattr(getattr(exc, "response", None), "status_code", None)
            retryable = isinstance(exc, httpx.TimeoutException) or status in {429, 502, 503, 504}
            logger.exception("Pollinations video generation failed status=%s exception=%s", status, exc.__class__.__name__)
            safe = "The optional fallback video engine is temporarily unavailable." if retryable else "The optional fallback video engine failed."
            raise VideoProviderError(self.name, str(exc), safe, retryable=retryable) from exc
