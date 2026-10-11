"""OpenAI image generation/edit provider.

Uses the existing OPENAI_API_KEY configuration. All secret-bearing calls stay
server-side. The provider returns raw bytes only; persistence is handled by the
engine media layer.
"""
from __future__ import annotations

import base64
import io
import os
from typing import List

import httpx
from openai import AsyncOpenAI

from .base import ImageProvider, ImageRequest, ImageResponse, ProviderError, provider_exception


class OpenAIImageProvider(ImageProvider):
    id = "openai-image"
    provider = "openai"
    model = os.environ.get("GB_OPENAI_IMAGE_MODEL", os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-2.5-flare"))
    capabilities = frozenset({"text_to_image", "image_to_image"})

    def available(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY", "").strip())

    def _client(self) -> AsyncOpenAI:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise ProviderError("OPENAI_API_KEY not configured")
        return AsyncOpenAI(api_key=key)

    async def _bytes_from_response(self, response) -> ImageResponse:
        out: List[bytes] = []
        mimes: List[str] = []
        for item in getattr(response, "data", []) or []:
            encoded = getattr(item, "b64_json", None)
            url = getattr(item, "url", None)
            if encoded:
                out.append(base64.b64decode(encoded))
                mimes.append("image/png")
            elif url:
                async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                    fetched = await client.get(url)
                    fetched.raise_for_status()
                    out.append(fetched.content)
                    mimes.append((fetched.headers.get("content-type") or "image/png").split(";")[0])
        if not out:
            raise ProviderError("OpenAI image response contained no image data")
        return ImageResponse(images=out, provider=self.provider, model=self.model, mime_types=mimes)

    async def generate(self, req: ImageRequest) -> ImageResponse:
        try:
            kwargs = {
                "model": self.model,
                "prompt": req.prompt,
                "n": req.n,
                "size": req.size,
            }
            if req.quality:
                kwargs["quality"] = req.quality
            if req.output_format:
                kwargs["output_format"] = req.output_format
            response = await self._client().images.generate(**kwargs)
            return await self._bytes_from_response(response)
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise provider_exception(self.id, exc) from None

    async def edit(self, req: ImageRequest) -> ImageResponse:
        if not req.input_images:
            raise ProviderError("image edit requires at least one input image")
        streams = []
        for index, data in enumerate(req.input_images):
            stream = io.BytesIO(data)
            name = req.input_image_names[index] if index < len(req.input_image_names) else f"input-{index}.png"
            stream.name = name  # SDK uses this for multipart filename/type inference.
            streams.append(stream)
        try:
            model = os.environ.get("GB_OPENAI_IMAGE_QUALITY_MODEL", "gpt-image-2.5-sunburst")
            kwargs = {
                "model": model,
                "prompt": req.prompt,
                "image": streams if len(streams) > 1 else streams[0],
                "n": req.n,
                "size": req.size,
            }
            if req.quality:
                kwargs["quality"] = req.quality
            if req.output_format:
                kwargs["output_format"] = req.output_format
            response = await self._client().images.edit(**kwargs)
            result = await self._bytes_from_response(response)
            result.model = model
            return result
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise provider_exception(self.id, exc) from None
        finally:
            for stream in streams:
                stream.close()
