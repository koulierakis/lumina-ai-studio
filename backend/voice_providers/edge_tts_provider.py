"""Microsoft Edge TTS provider for LUMINA Voice Studio."""
from __future__ import annotations

import re

import edge_tts

from .base import BaseVoiceProvider
from .voice_text_bridge import remember_source_text


_GREEK_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")


class EdgeTTSVoiceProvider(BaseVoiceProvider):
    name = "microsoft"
    capabilities = {
        "modes": ["text-to-speech"],
        "formats": ["mp3", "wav", "flac", "aac"],
        "credential_ready": True,
        "requires_api_key": False,
        "voice_cloning": False,
        "identity_preservation": False,
        "singing_voice_conversion": False,
    }

    DEFAULT_VOICES = {
        "el": "el-GR-NestorasNeural",
        "en": "en-US-AriaNeural",
    }

    @classmethod
    def _detect_language(cls, text: str, requested_voice: str | None = None) -> str:
        voice = (requested_voice or "").strip()
        if voice.startswith("el-"):
            return "el"
        if voice.startswith("en-"):
            return "en"
        return "el" if _GREEK_RE.search(text or "") else "en"

    @classmethod
    def _select_voice(cls, text: str, requested_voice: str | None = None) -> tuple[str, str]:
        voice = (requested_voice or "").strip()
        if voice.startswith(("el-", "en-")) and voice.endswith("Neural"):
            language = cls._detect_language(text, voice)
            return voice, language
        language = cls._detect_language(text, voice)
        return cls.DEFAULT_VOICES[language], language

    async def generate(
        self,
        text: str,
        voice: str,
        output_format: str,
        **options,
    ) -> tuple[bytes, str, dict]:
        clean_text = (text or "").strip()
        if not clean_text:
            raise ValueError("Enter text to generate speech.")

        selected_voice, language = self._select_voice(clean_text, voice)
        rate = str(options.get("rate") or "+0%")
        volume = str(options.get("volume") or "+0%")
        pitch = str(options.get("pitch") or "+0Hz")

        communicate = edge_tts.Communicate(
            clean_text,
            selected_voice,
            rate=rate,
            volume=volume,
            pitch=pitch,
        )

        audio = bytearray()
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio":
                audio.extend(chunk.get("data") or b"")

        if not audio:
            raise ValueError("Microsoft Edge TTS returned empty audio.")

        audio_bytes = bytes(audio)

        # Preserve the original text for the Personal Voice stage. When a
        # Voice Pack is selected, Chatterbox Multilingual can synthesize the
        # text directly in the reference speaker's voice instead of converting
        # this temporary Edge TTS voice.
        remember_source_text(audio_bytes, clean_text)

        # edge-tts streams MP3 audio. LUMINA stores the provider MIME type,
        # so callers receive valid audio/mpeg even if an older UI preset asked
        # for another export format.
        metadata = {
            "provider": self.name,
            "engine": "edge-tts",
            "voice": selected_voice,
            "language": language,
            "requested_output_format": output_format,
            "actual_output_format": "mp3",
            "mode": options.get("mode") or "text-to-speech",
            "style": options.get("style") or "default",
            "requires_api_key": False,
        }
        return audio_bytes, "audio/mpeg", metadata
