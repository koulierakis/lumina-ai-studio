"""Deterministic local WAV generator for Voice Studio development."""
from __future__ import annotations
import io, math, wave

class MockVoiceProvider:
    name = "mock"
    capabilities = {"modes": ["text-to-speech", "speech-to-text", "enhance", "noise-reduction", "trim", "normalize", "silence-removal", "volume", "convert", "batch"], "formats": ["wav"], "credential_ready": True, "voice_cloning": False}
    async def generate(self, text: str, voice: str, output_format: str) -> tuple[bytes, str, dict]:
        if output_format != "wav": raise ValueError("The local voice engine currently outputs WAV only.")
        rate, seconds = 24000, max(1, min(12, len(text or "audio") // 12 + 1))
        frames = bytearray()
        for i in range(rate * seconds):
            value = int(7000 * math.sin(2 * math.pi * 220 * i / rate) * (0.35 + 0.65 * min(1, i / (rate * .08))))
            frames.extend(value.to_bytes(2, "little", signed=True))
        out = io.BytesIO()
        with wave.open(out, "wb") as wav: wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(rate); wav.writeframes(frames)
        return out.getvalue(), "audio/wav", {"duration_seconds": seconds, "sample_rate": rate, "channels": 1, "bitrate": rate * 16, "mock": True}
