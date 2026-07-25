"""Local Video Studio provider that creates an animated preview without credentials."""
from __future__ import annotations

import io

from PIL import Image, ImageEnhance, ImageOps

from .base import GeneratedVideo, VideoGenerationInput, VideoProvider, VideoProviderCapabilities, VideoProviderError


class MockVideoProvider(VideoProvider):
    """Creates a small Ken-Burns-style animated GIF for local product testing.

    The provider intentionally uses only Pillow, so it runs in a fresh local
    environment. Hosted engines can return MP4/WebM from the exact same contract.
    """

    name = "mock"
    capabilities = VideoProviderCapabilities(
        text_to_video=True, image_to_video=True, multiple_images=True,
        variation=True, interpolation=True, output_formats=("image/gif",), max_image_inputs=8,
    )

    @classmethod
    def is_configured(cls) -> bool:
        return True

    async def generate(self, spec: VideoGenerationInput) -> GeneratedVideo:
        try:
            if not spec.source_images:
                # Text-to-video remains locally testable: generate a neutral canvas.
                source = Image.new("RGB", (640, 360), "#191714")
            else:
                source = Image.open(io.BytesIO(spec.source_images[0])).convert("RGB")
        except Exception as exc:
            raise VideoProviderError(self.name, "Invalid source image", "The uploaded image could not be read.") from exc

        target = (360, 640) if spec.aspect_ratio == "9:16" else (640, 360)
        fitted = ImageOps.fit(source, target, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        frames = []
        frame_count = min(18, max(8, spec.duration_seconds * 3))
        for index in range(frame_count):
            progress = index / max(1, frame_count - 1)
            zoom = 1.0 + (0.085 * progress)
            width, height = fitted.size
            crop_w, crop_h = int(width / zoom), int(height / zoom)
            left = int((width - crop_w) * progress)
            top = int((height - crop_h) * (1 - progress))
            frame = fitted.crop((left, top, left + crop_w, top + crop_h)).resize(target, Image.Resampling.LANCZOS)
            # A subtle light shift keeps the local preview visibly animated even
            # when the source image is a single flat colour.
            frame = ImageEnhance.Brightness(frame).enhance(0.96 + (0.08 * progress))
            frames.append(frame)

        output = io.BytesIO()
        frames[0].save(
            output,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=max(80, int(spec.duration_seconds * 1000 / frame_count)),
            loop=0,
            optimize=True,
        )
        return GeneratedVideo(output.getvalue(), "image/gif", preview_kind="animated-image")
