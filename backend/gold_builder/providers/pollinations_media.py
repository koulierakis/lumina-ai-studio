"""Pollinations media provider for Gold Builder."""
from __future__ import annotations

import json
import os
from urllib.parse import quote
import httpx

from .base import (
    ImageProvider,
    ImageRequest,
    ImageResponse,
    VideoProvider,
    VideoRequest,
    VideoResponse,
    ProviderError,
    TransientProviderError,
    provider_exception,
)

_IMAGE_BASE_URL = "https://image.pollinations.ai/prompt"
_VIDEO_BASE_URL = "https://gen.pollinations.ai"


def _retry_after(resp) -> float | None:
    """Seconds from a Retry-After header, when it is a plain integer."""
    value = (getattr(resp, "headers", {}) or {}).get("retry-after")
    try:
        value = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return value if value is not None and value >= 0 else None


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def _dimensions(req: ImageRequest) -> tuple[int, int]:
    size = (req.size or "1024x1024").lower().replace(" ", "")
    fallback_w, fallback_h = 1024, 1024
    if "x" in size:
        w, _, h = size.partition("x")
        try: fallback_w, fallback_h = int(w), int(h)
        except ValueError: pass
    return int(req.width or fallback_w), int(req.height or fallback_h)


def _image_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"
    if data.startswith(b"\xff\xd8\xff"): return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP": return "image/webp"
    raise ProviderError("pollinations returned a non-image response")


def _is_image(data: bytes) -> bool:
    return (
        data.startswith(b"\x89PNG\r\n\x1a\n")
        or data.startswith(b"\xff\xd8\xff")
        or (data.startswith(b"RIFF") and data[8:12] == b"WEBP")
    )


class PollinationsImage(ImageProvider):
    id = "pollinations-image"
    provider = "pollinations"
    model = os.environ.get("POLLINATIONS_IMAGE_MODEL", "flux")
    capabilities = frozenset({"text_to_image"})

    def available(self) -> bool:
        return os.environ.get("POLLINATIONS_DISABLED", "").strip().lower() not in {"1", "true", "yes"}

    async def generate(self, req: ImageRequest) -> ImageResponse:
        width, height = _dimensions(req)
        params = {
            "width": width,
            "height": height,
            "nologo": "true",
            "private": "true",
            "model": self.model,
        }
        if req.seed is not None:
            params["seed"] = int(req.seed)
        url = f"{_IMAGE_BASE_URL}{quote(req.prompt, safe='')}"
        images: list[bytes] = []
        mime_types: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=90.0, follow_redirects=True) as client:
                for index in range(max(1, int(req.n))):
                    request_params = dict(params)
                    if req.n > 1 and req.seed is None:
                        request_params["seed"] = index
                    resp = await client.get(url, params=request_params)
                    status = resp.status_code
                    if status in (401, 402, 403, 410):
                        raise ProviderError(f"pollinations auth/quota failure (HTTP {status})", status_code=status)
                    if status == 429:
                        raise TransientProviderError(
                            "pollinations rate limited (HTTP 429)",
                            status_code=429,
                            retry_after=_retry_after(resp),
                        )
                    if status >= 500:
                        raise TransientProviderError(f"pollinations server error (HTTP {status})", status_code=status)
                    if status != 200:
                        raise ProviderError(f"pollinations unexpected response (HTTP {status})", status_code=status)
                    data = resp.content
                    if not data or not _is_image(data):
                        raise ProviderError("pollinations returned a non-image response")
                    images.append(data)
                    mime_types.append(_image_mime(data))
        except ProviderError:
            raise
        except Exception as exc:
            raise provider_exception(self.id, exc) from None
        return ImageResponse(images=images, provider=self.provider, model=self.model, mime_types=mime_types)


class PollinationsVideoProvider(VideoProvider):
    """Keyless-by-design video provider, but the Pollinations video service
    (``gen.pollinations.ai/video/...``) requires an API key. It is therefore
    only *available* when a key is configured.

    Two bugs are fixed here: the old code pointed at the website root (which
    returns HTML) and built ``VideoResponse(video_url=...)`` — a field that does
    not exist — so it raised on every call while the capability report still
    advertised video as available.
    """

    id = "pollinations-video"
    provider = "pollinations"
    model = os.environ.get("POLLINATIONS_VIDEO_MODEL", "wan")

    def __init__(self) -> None:
        self.capabilities = frozenset(
            {"text_to_video", "image_to_video"} if self._api_key() else {"text_to_video"}
        )

    @staticmethod
    def _api_key() -> str:
        return (os.environ.get("POLLINATIONS_API_KEY") or "").strip()

    def available(self) -> bool:
        return bool(self._api_key()) and not _env_flag("POLLINATIONS_DISABLED")

    async def generate(self, req: VideoRequest) -> VideoResponse:
        api_key = self._api_key()
        if not api_key:
            raise ProviderError(
                "pollinations video requires POLLINATIONS_API_KEY", status_code=401
            )
        prompt = req.prompt
        if req.operation == "animate":
            if not req.input_image:
                raise ValueError("animate requires an input image")
            prompt = f"{prompt} animate-from:{_data_uri(req.input_image)}"
        params = {
            "model": self.model,
            "duration": int(req.seconds or 4),
            "aspectRatio": req.aspect_ratio or "16:9",
        }
        url = f"{_VIDEO_BASE_URL}/video/{quote(prompt, safe='')}"
        try:
            async with httpx.AsyncClient(timeout=180.0, follow_redirects=True) as client:
                resp = await client.get(
                    url, params=params, headers={"Authorization": f"Bearer {api_key}"}
                )
                status = resp.status_code
                if status in (401, 402, 403, 410):
                    raise ProviderError(
                        f"pollinations video auth/quota failure (HTTP {status})",
                        status_code=status,
                    )
                if status == 429:
                    raise TransientProviderError(
                        "pollinations video rate limited (HTTP 429)",
                        status_code=429,
                        retry_after=_retry_after(resp),
                    )
                if status >= 500:
                    raise TransientProviderError(
                        f"pollinations video server error (HTTP {status})", status_code=status
                    )
                if status != 200:
                    raise ProviderError(
                        f"pollinations video unexpected response (HTTP {status})",
                        status_code=status,
                    )
                data, mime = await _extract_video(client, resp)
        except ProviderError:
            raise
        except Exception as exc:
            raise provider_exception(self.id, exc) from None
        return VideoResponse(
            video=data,
            mime=mime,
            provider=self.provider,
            model=self.model,
            duration=float(req.seconds or 4),
        )


def _data_uri(image: bytes) -> str:
    import base64

    mime = "image/png" if image.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(image).decode()}"


def _looks_like_video(data: bytes) -> bool:
    if not data:
        return False
    if len(data) > 12 and data[4:8] == b"ftyp":
        return True
    if data.startswith(b"\x1aE\xdf\xa3"):
        return True
    return len(data) >= 8 and data[4:8] in {b"moov", b"mdat", b"wide", b"free", b"skip"}


def _video_mime(data: bytes) -> str:
    if data.startswith(b"\x1aE\xdf\xa3"):
        return "video/webm"
    if len(data) >= 8 and data[4:8] in {b"moov", b"mdat", b"wide", b"free", b"skip"}:
        return "video/quicktime"
    return "video/mp4"


async def _extract_video(client, resp) -> tuple[bytes, str]:
    """Accept a binary video body, or a JSON envelope carrying a media URL.

    A remote URL is downloaded with the same client; an inline ``data:`` URI is
    decoded directly. Anything else fails loudly rather than reporting a fake
    success.
    """
    content_type = (getattr(resp, "headers", {}) or {}).get("content-type", "")
    data = resp.content
    if "application/json" in content_type:
        try:
            payload = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ProviderError("pollinations video returned malformed JSON") from None
        candidate = None
        if isinstance(payload, dict):
            candidate = payload.get("video") or payload.get("url") or payload.get("output")
            if isinstance(candidate, list):
                candidate = candidate[0] if candidate else None
        if not isinstance(candidate, str) or not candidate:
            raise ProviderError("pollinations video response carried no media URL")
        if candidate.startswith("data:"):
            import base64

            _, _, encoded = candidate.partition(",")
            try:
                data = base64.b64decode(encoded)
            except (ValueError, TypeError):
                raise ProviderError("pollinations video returned invalid base64") from None
        else:
            downloaded = await client.get(candidate, follow_redirects=True)
            if downloaded.status_code != 200 or not _looks_like_video(downloaded.content):
                raise ProviderError("pollinations video media URL did not yield a video")
            data = downloaded.content
    if not _looks_like_video(data):
        raise ProviderError("pollinations video returned a non-video response")
    return data, _video_mime(data)
