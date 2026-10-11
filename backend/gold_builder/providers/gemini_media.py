"""Direct Gemini image provider using the official Gemini REST API.

Supports both text-to-image and image-conditioned editing with GEMINI_API_KEY.
No SDK-specific dependency is required.
"""
from __future__ import annotations

import base64
import os
from typing import List

import httpx

from .base import ImageProvider, ImageRequest, ImageResponse, ProviderError, provider_exception


def _mime_for_image(data: bytes, name: str = "") -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    lowered = name.lower()
    if lowered.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lowered.endswith(".webp"):
        return "image/webp"
    return None


class GeminiImageProvider(ImageProvider):
    id = "gemini-image"
    provider = "gemini"
    model = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")
    capabilities = frozenset({"text_to_image", "image_to_image"})

    def available(self) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY", "").strip())

    async def _call(self, req: ImageRequest) -> tuple[bytes, str]:
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise ProviderError("GEMINI_API_KEY not configured")

        if req.input_images:
            interaction_input: str | list[dict] = [
                {"type": "text", "text": req.prompt},
            ]
            for index, data in enumerate(req.input_images):
                name = req.input_image_names[index] if index < len(req.input_image_names) else ""
                mime = _mime_for_image(data, name)
                if not mime:
                    raise ProviderError("unsupported input image MIME type")
                interaction_input.append({
                    "type": "image",
                    "mime_type": mime,
                    "data": base64.b64encode(data).decode("ascii"),
                })
        else:
            interaction_input = req.prompt

        payload = {
            "model": self.model,
            "input": interaction_input,
        }
        # The simplest Interactions image request needs only model + input.
        # Add response_format only when a provider-specific rendering option is
        # explicitly requested, avoiding unsupported format combinations.
        if req.aspect_ratio:
            payload["response_format"] = {
                "type": "image",
                "aspect_ratio": req.aspect_ratio,
            }
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(
                    "https://generativelanguage.googleapis.com/v1beta/interactions",
                    headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
        except Exception as exc:  # noqa: BLE001
            raise provider_exception(self.id, exc) from None

        def decode_block(block: dict) -> tuple[bytes, str] | None:
            encoded = block.get("data")
            if not encoded:
                return None
            try:
                data = base64.b64decode(encoded)
            except Exception as exc:  # noqa: BLE001
                raise ProviderError("Gemini returned invalid base64 image data") from exc
            declared = block.get("mime_type") or block.get("mimeType")
            mime = declared if declared in {"image/png", "image/jpeg", "image/webp"} else _mime_for_image(data)
            if not mime:
                raise ProviderError("Gemini returned an unsupported image MIME type")
            return data, mime

        # Current Interactions API exposes output_image directly. Keep a
        # defensive steps parser for responses that return model-output blocks.
        direct = body.get("output_image")
        if isinstance(direct, dict):
            decoded = decode_block(direct)
            if decoded:
                return decoded
        interaction = body.get("interaction")
        if isinstance(interaction, dict) and isinstance(interaction.get("output_image"), dict):
            decoded = decode_block(interaction["output_image"])
            if decoded:
                return decoded
        step_sets = [body.get("steps") or []]
        if isinstance(interaction, dict):
            step_sets.append(interaction.get("steps") or [])
        for steps in step_sets:
            for step in steps:
                if not isinstance(step, dict):
                    continue
                for block in step.get("content") or []:
                    if not isinstance(block, dict) or block.get("type") != "image":
                        continue
                    decoded = decode_block(block)
                    if decoded:
                        return decoded
        raise ProviderError("Gemini image response contained no image data")

    async def _generate_many(self, req: ImageRequest) -> ImageResponse:
        images: List[bytes] = []
        mime_types: List[str] = []
        for _ in range(max(1, req.n)):
            data, mime = await self._call(req)
            images.append(data)
            mime_types.append(mime)
        return ImageResponse(
            images=images,
            provider=self.provider,
            model=self.model,
            mime_types=mime_types,
        )

    async def generate(self, req: ImageRequest) -> ImageResponse:
        return await self._generate_many(req)

    async def edit(self, req: ImageRequest) -> ImageResponse:
        if not req.input_images:
            raise ProviderError("Gemini image edit requires at least one input image")
        return await self._generate_many(req)



class GeminiFlashLiteImageProvider(GeminiImageProvider):
    """Nano Banana 2 Lite with an independent provider identity/cooldown."""

    id = "gemini-image-flash-lite"
    model = os.environ.get("GB_GEMINI_IMAGE_LITE_MODEL", "gemini-3.1-flash-lite-image")


class Gemini25FlashImageProvider(ImageProvider):
    """Fallback Gemini 2.5 Flash Image provider using generateContent.

    Kept separate from the Interactions-based Gemini 3.1 provider so a
    model-specific quota/rate limit can fall through cleanly.
    """

    id = "gemini-image-2.5-flash"
    provider = "gemini"
    model = "gemini-2.5-flash-image"
    capabilities = frozenset({"text_to_image", "image_to_image"})

    def available(self) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY", "").strip())

    async def _call(self, req: ImageRequest) -> tuple[bytes, str]:
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise ProviderError("GEMINI_API_KEY not configured")

        parts: list[dict] = [{"text": req.prompt}]
        for index, data in enumerate(req.input_images):
            name = req.input_image_names[index] if index < len(req.input_image_names) else ""
            mime = _mime_for_image(data, name)
            if not mime:
                raise ProviderError("unsupported input image MIME type")
            parts.append({
                "inlineData": {
                    "mimeType": mime,
                    "data": base64.b64encode(data).decode("ascii"),
                }
            })

        generation_config: dict = {"responseModalities": ["IMAGE"]}
        if req.aspect_ratio:
            generation_config["responseFormat"] = {
                "image": {"aspectRatio": req.aspect_ratio}
            }

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": generation_config,
        }
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(
                    url,
                    headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
        except Exception as exc:  # noqa: BLE001
            raise provider_exception(self.id, exc) from None

        candidates = body.get("candidates") or []
        if not candidates:
            raise ProviderError("Gemini 2.5 image response contained no candidates")
        response_parts = ((candidates[0].get("content") or {}).get("parts") or [])
        for part in response_parts:
            inline = part.get("inlineData") or part.get("inline_data")
            if not isinstance(inline, dict):
                continue
            encoded = inline.get("data")
            if not encoded:
                continue
            try:
                data = base64.b64decode(encoded)
            except Exception as exc:  # noqa: BLE001
                raise ProviderError("Gemini 2.5 returned invalid base64 image data") from exc
            declared = inline.get("mimeType") or inline.get("mime_type")
            mime = declared if declared in {"image/png", "image/jpeg", "image/webp"} else _mime_for_image(data)
            if not mime:
                raise ProviderError("Gemini 2.5 returned an unsupported image MIME type")
            return data, mime
        raise ProviderError("Gemini 2.5 image response contained no image data")

    async def _generate_many(self, req: ImageRequest) -> ImageResponse:
        images: List[bytes] = []
        mime_types: List[str] = []
        for _ in range(max(1, req.n)):
            data, mime = await self._call(req)
            images.append(data)
            mime_types.append(mime)
        return ImageResponse(
            images=images,
            provider=self.provider,
            model=self.model,
            mime_types=mime_types,
        )

    async def generate(self, req: ImageRequest) -> ImageResponse:
        return await self._generate_many(req)

    async def edit(self, req: ImageRequest) -> ImageResponse:
        if not req.input_images:
            raise ProviderError("Gemini 2.5 image edit requires at least one input image")
        return await self._generate_many(req)
