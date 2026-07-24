import base64
import io
from types import SimpleNamespace

import pytest
from PIL import Image

from providers.gemini_provider import _extract_image


def _png(width: int, height: int, seed: int) -> bytes:
    image = Image.new("RGB", (width, height))
    pixels = []
    for y in range(height):
        for x in range(width):
            pixels.append(
                (
                    (x * 17 + y * 3 + seed) % 256,
                    (x * 5 + y * 19 + seed) % 256,
                    (x * 11 + y * 7 + seed) % 256,
                )
            )
    image.putdata(pixels)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _part(payload: bytes, mime: str = "image/png"):
    return SimpleNamespace(
        thought=False,
        inline_data=SimpleNamespace(data=base64.b64encode(payload).decode("ascii"), mime_type=mime),
    )


def test_extract_image_uses_largest_inline_payload():
    tiny_placeholder = b"\x89PNG\r\n\x1a\n" + (b"x" * 173)
    real_image = _png(96, 96, 10)
    response = SimpleNamespace(parts=[_part(real_image), _part(tiny_placeholder)])

    extracted = _extract_image(response)

    assert extracted.data == real_image
    assert len(extracted.data) == len(real_image)


def test_extract_image_reads_candidate_content_parts():
    real_image = _png(96, 96, 20)
    response = SimpleNamespace(
        parts=[],
        candidates=[
            SimpleNamespace(content=SimpleNamespace(parts=[_part(real_image, "image/png")]))
        ],
    )

    extracted = _extract_image(response)

    assert extracted.data == real_image
    assert extracted.mime_type == "image/png"


def test_extract_image_rejects_tiny_placeholder():
    tiny_placeholder = b"\x89PNG\r\n\x1a\n" + (b"x" * 173)
    response = SimpleNamespace(parts=[_part(tiny_placeholder)])

    with pytest.raises(RuntimeError, match="no valid image bytes"):
        _extract_image(response)


def test_extract_image_rejects_response_without_inline_image_data():
    response = SimpleNamespace(parts=[SimpleNamespace(thought=False, text="no image")], text="no image")

    with pytest.raises(RuntimeError, match="no valid image bytes"):
        _extract_image(response)
