from __future__ import annotations

import base64
import io
import json
import os
import urllib.request
import wave


class GeminiVoiceProvider:
    name = "gemini"
    capabilities = {
        "modes": ["text-to-speech"],
        "formats": ["wav"],
        "languages": ["el-GR"],
        "voices": ["Kore"],
        "credential_ready": True,
        "mock": False,
    }

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY"))

    @staticmethod
    def _pcm_to_wav(pcm: bytes, sample_rate: int = 24000) -> bytes:
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm)
        return output.getvalue()

    async def generate(self, text: str, voice: str, output_format: str, **options):
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        if output_format != "wav":
            raise ValueError("Gemini voice currently outputs WAV only.")

        model = str(options.get("model") or "gemini-3.1-flash-tts-preview")
        voice_name = voice if voice and voice != "personal-user" else "Kore"
        style = str(options.get("style") or "calm")

        prompt = (
            "Speak naturally in Greek (Greece). Preserve the text exactly. "
            f"Delivery style: {style}. Do not translate or add commentary.\n\n{text}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": voice_name}
                    }
                },
            },
        }
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))

        parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        inline = next((part.get("inlineData") for part in parts if part.get("inlineData")), None)
        if not inline or not inline.get("data"):
            raise RuntimeError("Gemini returned no audio data.")

        pcm = base64.b64decode(inline["data"])
        wav = self._pcm_to_wav(pcm, 24000)
        return wav, "audio/wav", {
            "provider": "gemini",
            "model": model,
            "voice": voice_name,
            "language": "el-GR",
            "sample_rate": 24000,
            "channels": 1,
            "bit_depth": 16,
            "mock": False,
        }
