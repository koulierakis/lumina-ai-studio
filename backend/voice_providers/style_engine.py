"""Provider-neutral Greek delivery profiles for the LUMINA voices."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceStyle:
    id: str
    rate: str
    pitch: str
    volume: str
    sentence_pause: str
    personality: str

    def prepare_text(self, text: str) -> str:
        """Shape sentence boundaries without changing the words being spoken."""
        clean = " ".join(text.split()).strip()
        if not self.sentence_pause:
            return clean
        return re.sub(r"([.!;?])(?=\s|$)", rf"\1{self.sentence_pause}", clean)


class VoiceStyleEngine:
    """Single source of truth for the six production delivery styles.

    Greek Edge voices do not expose native expressive-style controls.  These
    profiles therefore use the controls the neural voices actually support:
    deliberately separated pace, register, presence and sentence timing.
    """

    STYLES = {
        "natural": VoiceStyle("natural", "+0%", "+0Hz", "+0%", "", "balanced and conversational"),
        "calm": VoiceStyle("calm", "-22%", "-5Hz", "-5%", " …", "slow, grounded and spacious"),
        "warm": VoiceStyle("warm", "-9%", "-9Hz", "+1%", " …", "close, gentle and reassuring"),
        "professional": VoiceStyle("professional", "+3%", "-2Hz", "+4%", "", "precise, controlled and authoritative"),
        "energetic": VoiceStyle("energetic", "+22%", "+9Hz", "+8%", "", "bright, fast and high-impact"),
        "storytelling": VoiceStyle("storytelling", "-14%", "-11Hz", "+2%", " …", "dramatic, intimate and unhurried"),
    }

    # Old jobs and clients remain deploy-safe while the UI moves to v2 names.
    ALIASES = {
        "podcast": "natural",
        "audiobook": "storytelling",
        "corporate": "professional",
        "confident": "professional",
    }

    @classmethod
    def resolve(cls, requested: str | None) -> VoiceStyle:
        style_id = str(requested or "natural").strip().lower()
        style_id = cls.ALIASES.get(style_id, style_id)
        try:
            return cls.STYLES[style_id]
        except KeyError as exc:
            raise ValueError("Unsupported LUMINA voice style.") from exc

    @classmethod
    def catalog(cls) -> list[str]:
        return list(cls.STYLES)
