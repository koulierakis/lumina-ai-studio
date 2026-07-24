"""Test-only image provider for network-independent backend regressions."""
from __future__ import annotations

import os
import struct
import zlib

from .base import GeneratedImage, GenerationInput, ImageProvider, ProviderCapabilities


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def _solid_png(width: int = 64, height: int = 64) -> bytes:
    raw_rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            row.extend(((x * 3) % 256, (y * 5) % 256, 180))
        raw_rows.append(bytes(row))
    payload = b"".join(raw_rows)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(payload, level=6))
        + _png_chunk(b"IEND", b"")
    )


class MockImageProvider(ImageProvider):
    name = "mock"
    priority = -100
    capabilities = ProviderCapabilities(
        generation=True,
        editing=False,
        identity_references=True,
        multiple_outputs=True,
        aspect_ratios=("1:1", "4:3", "3:4", "16:9", "9:16"),
        maximum_reference_images=5,
        maximum_outputs=4,
        models=("lumina-test-image",),
    )

    @classmethod
    def is_configured(cls) -> bool:
        return os.getenv("LUMINA_TEST_PROVIDER", "").lower() in {"1", "true", "yes"}

    async def generate(self, spec: GenerationInput) -> list[GeneratedImage]:
        count = max(1, min(4, spec.count or 1))
        return [GeneratedImage(data=_solid_png(), mime_type="image/png") for _ in range(count)]
