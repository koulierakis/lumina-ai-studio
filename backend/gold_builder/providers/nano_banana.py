"""Gemini Nano Banana image provider through Emergent Universal Key.

Falls back gracefully if the library is unavailable. Wrapped behind
ImageProvider so a different image backend (SDXL, DALL-E, etc.) can be
swapped without touching engine code.
"""
from __future__ import annotations

import os
from typing import List

from .base import ImageProvider, ImageRequest, ImageResponse, ProviderError, provider_exception


class NanoBananaImage(ImageProvider):
    id = "emergent-gemini-nano-banana"
    provider = "gemini"
    model = "gemini-2.5-flash-image-preview"
    capabilities = frozenset({"text_to_image"})

    def available(self) -> bool:
        if not os.environ.get("EMERGENT_LLM_KEY"):
            return False
        try:
            import emergentintegrations  # noqa: F401
            return True
        except ImportError:
            return False

    async def generate(self, req: ImageRequest) -> ImageResponse:
        key = os.environ.get("EMERGENT_LLM_KEY")
        if not key:
            raise ProviderError("EMERGENT_LLM_KEY not configured")
        try:
            # emergentintegrations exposes an image gen helper for nano banana
            from emergentintegrations.llm.gemini.image_generation import (  # type: ignore
                GeminiImageGeneration,
            )
        except ImportError as e:
            raise ProviderError("gemini image generation not available") from None

        try:
            gen = GeminiImageGeneration(api_key=key)
            images = await gen.generate_images(
                prompt=req.prompt,
                model="gemini-2.5-flash-image-preview",
                number_of_images=req.n,
            )
            # images should be List[bytes]
            if not isinstance(images, list):
                images = [images]
            out: List[bytes] = []
            for im in images:
                if isinstance(im, (bytes, bytearray)):
                    out.append(bytes(im))
                elif hasattr(im, "read"):
                    out.append(im.read())
                else:
                    out.append(bytes(im))
            return ImageResponse(images=out, provider="gemini", model="nano-banana")
        except Exception as e:  # noqa: BLE001
            raise provider_exception(self.id, e) from None
