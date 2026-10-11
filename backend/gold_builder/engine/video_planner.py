"""Deterministic autonomous video-requirement detection."""
from __future__ import annotations

import re
from typing import List, Optional

from ..models import ImageSpec, VideoSpec

_GENERATED_VIDEO = re.compile(
    r"\b(generate|create|make|produce|add|include|want|need|render)\b"
    r"[^.?!\n]{0,60}\b(video|videos|video clip|hero video|promo video|trailer|motion graphic)s?\b",
    re.IGNORECASE,
)
_WITH_VIDEO = re.compile(
    r"\b(with|featuring|including)\b[^.?!\n]{0,30}"
    r"\b(hero video|background video|promo video|video clip|motion graphic)s?\b",
    re.IGNORECASE,
)
_IMAGE_TO_VIDEO = re.compile(
    r"\banimate(?:s|d)?\s+(?:the\s+|this\s+|a\s+|an\s+|my\s+)?"
    r"(image|images|photo|photos|picture|pictures|logo|hero|banner|frame|still)\b",
    re.IGNORECASE,
)
_NEGATED_VIDEO = re.compile(
    r"\b(without|no|exclude|omit|remove|replace)\b[^.?!\n]{0,35}\b(video|videos|video clip|hero video)s?\b"
    r"|\b(do\s+not|don't|dont)\b[^.?!\n]{0,35}\b(include|add|create|generate|use)\b"
    r"[^.?!\n]{0,25}\bvideos?\b",
    re.IGNORECASE,
)
_MEDIA_HANDLING_ONLY = re.compile(
    r"\b(upload|uploads|uploader|playback|player|display|accept|support)\b"
    r"[^.?!\n]{0,40}\b(mp4|webm|videos?|video files?)\b",
    re.IGNORECASE,
)


def _positive_clauses(request: str) -> List[str]:
    """Return clauses that contain positive video-generation intent."""
    clauses = [c.strip() for c in re.split(r"[;.!?\n]+", request or "") if c.strip()]
    positive: List[str] = []
    for clause in clauses:
        if _NEGATED_VIDEO.search(clause):
            continue
        if re.search(
            r"\b(do\s+not|don't|dont|never|without|no)\b[^.?!;]{0,30}"
            r"\banimate(?:s|d|ing)?\b",
            clause,
            re.IGNORECASE,
        ):
            continue
        if _IMAGE_TO_VIDEO.search(clause):
            positive.append(clause)
            continue
        if _MEDIA_HANDLING_ONLY.search(clause) and not _GENERATED_VIDEO.search(clause):
            continue
        if _GENERATED_VIDEO.search(clause) or _WITH_VIDEO.search(clause):
            positive.append(clause)
    return positive


def requires_video(request: str) -> bool:
    """True only when at least one clause asks Gold Builder to create video."""
    return bool(_positive_clauses(request))


def _derive_prompt(request: str) -> str:
    return re.sub(r"\s+", " ", request).strip()[:400]


def _select_animation_image(request: str, image_specs: List[ImageSpec]) -> Optional[str]:
    if not image_specs:
        return None
    if len(image_specs) == 1:
        return image_specs[0].path

    words = {
        w for w in re.findall(r"[a-z0-9]+", request.lower())
        if len(w) > 2 and w not in {"animate", "image", "photo", "picture", "this", "the"}
    }
    scored = []
    for spec in image_specs:
        haystack = " ".join((spec.path, spec.alt, spec.prompt)).lower()
        score = sum(1 for w in words if w in haystack)
        scored.append((score, spec.path))
    best = max(score for score, _ in scored)
    matches = [path for score, path in scored if score == best and score > 0]
    return matches[0] if len(matches) == 1 else None


def detect_video_requirement(
    request: str,
    image_specs: Optional[List[ImageSpec]] = None,
) -> Optional[VideoSpec]:
    positive = _positive_clauses(request)
    if not positive:
        return None
    generation_request = "; ".join(positive)
    spec = VideoSpec(
        path="generated/video.mp4",
        prompt=_derive_prompt(generation_request),
        operation="generate",
    )
    if _IMAGE_TO_VIDEO.search(generation_request):
        selected = _select_animation_image(generation_request, image_specs or [])
        if selected is None:
            return None
        spec.operation = "animate"
        spec.input_image_path = selected
    return spec
