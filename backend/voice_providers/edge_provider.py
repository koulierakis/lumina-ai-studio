"""Free/no-subscription Microsoft Edge TTS provider for LUMINA Voice Studio."""
from __future__ import annotations

import io
from typing import Any

from .style_engine import VoiceStyleEngine


class EdgeVoiceProvider:
    name = "edge"

    VOICE_MAP = {
        "lumina-female": "el-GR-AthinaNeural",
        "lumina-male": "el-GR-NestorasNeural",
    }

    capabilities = {
        "modes": ["text-to-speech"],
        "formats": ["mp3"],
        "credential_ready": True,
        "voice_cloning": False,
        "identity_preservation": False,
        "singing_voice_conversion": False,
        "languages": ["el-GR"],
        "voices": [
            {"id": "lumina-male", "display_name": "LUMINA Male", "provider_voice_id": "el-GR-NestorasNeural", "language": "el-GR", "gender_presentation": "male"},
            {"id": "lumina-female", "display_name": "LUMINA Female", "provider_voice_id": "el-GR-AthinaNeural", "language": "el-GR", "gender_presentation": "female"},
        ],
        "styles": VoiceStyleEngine.catalog(),
    }

    @classmethod
    def list_voices(cls) -> list[dict[str, Any]]:
        return list(cls.capabilities["voices"])

    async def health(self) -> dict[str, Any]:
        try:
            import edge_tts

            voices = await edge_tts.list_voices()
            available = {item.get("ShortName") for item in voices}
            required = set(self.VOICE_MAP.values())
            return {
                "ok": required.issubset(available),
                "provider": self.name,
                "available_voices": sorted(required & available),
                "missing_voices": sorted(required - available),
            }
        except Exception as exc:
            return {"ok": False, "provider": self.name, "error": str(exc)}

    async def generate(self, text: str, voice: str, output_format: str, **options) -> tuple[bytes, str, dict]:
        if output_format != "mp3":
            raise ValueError("LUMINA built-in voices currently generate MP3 audio.")
        clean_text = " ".join((text or "").split()).strip()
        if not clean_text:
            raise ValueError("Enter text to generate speech.")
        if len(clean_text) > 5000:
            raise ValueError("Text is too long. Maximum length is 5000 characters.")

        provider_voice = self.VOICE_MAP.get(voice)
        if not provider_voice:
            raise ValueError("Unknown LUMINA voice.")

        profile = VoiceStyleEngine.resolve(options.get("style"))
        styled_text = profile.prepare_text(clean_text)

        import edge_tts

        communicator = edge_tts.Communicate(
            styled_text,
            provider_voice,
            rate=profile.rate,
            volume=profile.volume,
            pitch=profile.pitch,
        )

        audio = io.BytesIO()
        async for chunk in communicator.stream():
            if chunk.get("type") == "audio":
                audio.write(chunk.get("data") or b"")

        payload = audio.getvalue()
        if len(payload) < 256:
            raise RuntimeError("The TTS provider returned empty audio.")

        return payload, "audio/mpeg", {
            "provider": self.name,
            "provider_voice_id": provider_voice,
            "voice": voice,
            "language": "el-GR",
            "style": profile.id,
            "style_engine": "v2",
            "personality": profile.personality,
            "rate": profile.rate,
            "pitch": profile.pitch,
            "volume": profile.volume,
            "mock": False,
        }
