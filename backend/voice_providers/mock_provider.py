"""Deterministic local WAV generator for Voice Studio development."""
from __future__ import annotations
import io, math, wave

class MockVoiceProvider:
    name = "mock"
    capabilities = {"modes": ["text-to-speech", "speech-to-speech", "live-voice-conversion", "voice-style-transfer", "voice-clone", "enhance", "noise-reduction", "echo-removal", "click-removal", "pop-removal", "breath-control", "de-esser", "normalize", "compressor", "equalizer", "limiter", "reverb", "delay", "stereo-enhancement", "loudness-correction", "singing-conversion", "vocal-isolation", "instrumental-separation", "stem-separation", "pitch-detection", "pitch-correction", "timing-correction", "harmony-generation", "vocal-layering", "backing-vocals", "podcast-mastering", "silence-detection", "automatic-cleanup", "intro", "outro", "chapters", "cut", "trim", "split", "merge", "fade-in", "fade-out", "convert", "batch"], "formats": ["wav", "mp3", "flac", "aac"], "credential_ready": True, "voice_cloning": True, "identity_preservation": True, "singing_voice_conversion": True}
    async def generate(self, text: str, voice: str, output_format: str, **options) -> tuple[bytes, str, dict]:
        if output_format not in self.capabilities["formats"]: raise ValueError("The local voice engine does not support this format.")
        rate, seconds = int(options.get("sample_rate") or 48000), max(1, min(12, len(text or "audio") // 12 + 1))
        style = str(options.get("style") or "podcast")
        frequency = 180 + (sum(ord(ch) for ch in f"{voice}:{style}") % 180)
        frames = bytearray()
        for i in range(rate * seconds):
            envelope = (0.35 + 0.65 * min(1, i / (rate * .08))) * max(0.08, min(1, (rate * seconds - i) / (rate * .12)))
            value = int(7000 * math.sin(2 * math.pi * frequency * i / rate) * envelope)
            frames.extend(value.to_bytes(2, "little", signed=True))
        out = io.BytesIO()
        with wave.open(out, "wb") as wav: wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(rate); wav.writeframes(frames)
        mime = {"wav": "audio/wav", "mp3": "audio/mpeg", "flac": "audio/flac", "aac": "audio/aac"}[output_format]
        return out.getvalue(), mime, {"duration_seconds": seconds, "sample_rate": rate, "channels": 1, "bit_depth": int(options.get("bit_depth") or 24), "bitrate": options.get("bitrate") or rate * 16, "loudness_lufs": float(options.get("loudness_lufs") or -16), "style": style, "mode": options.get("mode") or "text-to-speech", "preset_id": options.get("preset_id"), "identity_preservation": True, "mock": True}
