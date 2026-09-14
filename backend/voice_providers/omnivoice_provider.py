"""Personal Voice provider backed by ResembleAI Chatterbox Multilingual.

The historical ``omnivoice`` provider key is retained so existing LUMINA jobs
and UI contracts do not need a migration. Synthesis is performed by the
validated official ResembleAI Chatterbox Multilingual ZeroGPU Space: text +
the user's saved reference sample -> cloned Greek speech.

The public Chatterbox demo accepts at most 300 characters per request. LUMINA
therefore splits longer text into sentence-aware chunks, synthesizes each
chunk, and joins the WAV files into one continuous output.
"""
from __future__ import annotations

import asyncio
import io
import re
import tempfile
import wave
from pathlib import Path

import httpx


class OmniVoiceExternalProvider:
    name = "omnivoice"
    MAX_OUTPUT_BYTES = 50 * 1024 * 1024
    MAX_CHUNK_CHARACTERS = 290
    MAX_TEXT_CHARACTERS = 5000
    DEFAULT_SPACE_ID = "ResembleAI/Chatterbox-Multilingual-TTS"
    DEFAULT_SPACE_URL = "https://resembleai-chatterbox-multilingual-tts.hf.space"
    DEFAULT_API_NAME = "/generate_tts_audio"

    capabilities = {
        "modes": ["voice-clone"],
        "formats": ["wav"],
        "credential_ready": True,
        "voice_cloning": True,
        "identity_preservation": True,
        "singing_voice_conversion": False,
        "languages": ["el-GR"],
        "shared_runtime": True,
        "max_text_characters": MAX_TEXT_CHARACTERS,
        "chunked_generation": True,
    }

    def __init__(self):
        # Pin production to the exact official Space/API contract we runtime-test.
        # This intentionally ignores stale Render overrides that previously routed
        # Personal Voice to a different Space with an incompatible Gradio API.
        self.space_id = self.DEFAULT_SPACE_ID
        self.space_url = self.DEFAULT_SPACE_URL
        self.api_name = self.DEFAULT_API_NAME

    async def health(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True, trust_env=False) as client:
                response = await client.get(self.space_url)
                response.raise_for_status()
            return {
                "ok": True,
                "provider": self.name,
                "engine": "chatterbox-multilingual",
                "space_id": self.space_id,
            }
        except Exception as exc:
            return {"ok": False, "provider": self.name, "error": str(exc)}

    @staticmethod
    def _suffix_for_mime(mime: str) -> str:
        value = (mime or "").lower().split(";", 1)[0]
        return {
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
            "audio/mpeg": ".mp3",
            "audio/mp3": ".mp3",
            "audio/flac": ".flac",
            "audio/ogg": ".ogg",
            "audio/webm": ".webm",
            "audio/mp4": ".m4a",
            "audio/x-m4a": ".m4a",
            "audio/aac": ".aac",
        }.get(value, ".wav")

    @classmethod
    def _split_text(cls, text: str) -> list[str]:
        """Split text into natural chunks that stay under the provider limit."""
        clean = " ".join((text or "").split()).strip()
        if not clean:
            return []
        if len(clean) <= cls.MAX_CHUNK_CHARACTERS:
            return [clean]

        sentences = [part.strip() for part in re.split(r"(?<=[.!?;·…])\s+", clean) if part.strip()]
        chunks: list[str] = []
        current = ""

        def push_current() -> None:
            nonlocal current
            if current:
                chunks.append(current)
                current = ""

        for sentence in sentences:
            if len(sentence) <= cls.MAX_CHUNK_CHARACTERS:
                candidate = f"{current} {sentence}".strip()
                if len(candidate) <= cls.MAX_CHUNK_CHARACTERS:
                    current = candidate
                else:
                    push_current()
                    current = sentence
                continue

            push_current()
            words = sentence.split()
            piece = ""
            for word in words:
                candidate = f"{piece} {word}".strip()
                if len(candidate) <= cls.MAX_CHUNK_CHARACTERS:
                    piece = candidate
                else:
                    if piece:
                        chunks.append(piece)
                    while len(word) > cls.MAX_CHUNK_CHARACTERS:
                        chunks.append(word[: cls.MAX_CHUNK_CHARACTERS])
                        word = word[cls.MAX_CHUNK_CHARACTERS :]
                    piece = word
            if piece:
                current = piece

        push_current()
        return chunks

    def _generate_sync(self, text: str, reference_audio: bytes, reference_mime: str) -> bytes:
        try:
            from gradio_client import Client, handle_file
        except Exception as exc:
            raise RuntimeError("The Chatterbox client is not installed.") from exc

        suffix = self._suffix_for_mime(reference_mime)
        with tempfile.TemporaryDirectory(prefix="lumina-chatterbox-") as workdir:
            reference_path = Path(workdir) / f"reference{suffix}"
            reference_path.write_bytes(reference_audio)

            client = Client(self.space_id)
            result = client.predict(
                text,
                "el",
                handle_file(str(reference_path)),
                0.5,
                0.8,
                0,
                0.5,
                api_name=self.api_name,
            )

            output_path = None
            if isinstance(result, str):
                output_path = result
            elif isinstance(result, (list, tuple)) and result:
                first = result[0]
                if isinstance(first, str):
                    output_path = first
                elif isinstance(first, dict):
                    output_path = first.get("path") or first.get("name")
            elif isinstance(result, dict):
                output_path = result.get("path") or result.get("name")

            if not output_path:
                raise RuntimeError("Chatterbox returned no audio file.")
            try:
                payload = Path(str(output_path)).read_bytes()
            except OSError as exc:
                raise RuntimeError("Chatterbox output could not be read.") from exc

        return payload

    @staticmethod
    def _join_wav_chunks(chunks: list[bytes], pause_ms: int = 140) -> bytes:
        if not chunks:
            raise RuntimeError("No audio chunks were generated.")
        if len(chunks) == 1:
            return chunks[0]

        decoded: list[tuple[wave._wave_params, bytes]] = []
        for index, payload in enumerate(chunks, start=1):
            try:
                with wave.open(io.BytesIO(payload), "rb") as reader:
                    params = reader.getparams()
                    frames = reader.readframes(reader.getnframes())
            except (wave.Error, EOFError) as exc:
                raise RuntimeError(f"Generated audio chunk {index} is not a valid WAV file.") from exc
            decoded.append((params, frames))

        base = decoded[0][0]
        for params, _frames in decoded[1:]:
            if (
                params.nchannels != base.nchannels
                or params.sampwidth != base.sampwidth
                or params.framerate != base.framerate
                or params.comptype != base.comptype
            ):
                raise RuntimeError("Generated WAV chunks use incompatible audio formats.")

        silence_frames = max(0, int(base.framerate * pause_ms / 1000))
        silence = b"\x00" * silence_frames * base.nchannels * base.sampwidth
        output = io.BytesIO()
        with wave.open(output, "wb") as writer:
            writer.setnchannels(base.nchannels)
            writer.setsampwidth(base.sampwidth)
            writer.setframerate(base.framerate)
            writer.setcomptype(base.comptype, base.compname)
            for index, (_params, frames) in enumerate(decoded):
                if index:
                    writer.writeframesraw(silence)
                writer.writeframesraw(frames)
        return output.getvalue()

    async def generate(self, text: str, voice: str, output_format: str, **options) -> tuple[bytes, str, dict]:
        clean_text = " ".join((text or "").split()).strip()
        reference_audio = options.get("reference_audio")
        if not clean_text:
            raise ValueError("Enter text to generate speech.")
        if len(clean_text) > self.MAX_TEXT_CHARACTERS:
            raise ValueError(f"Personal Voice supports up to {self.MAX_TEXT_CHARACTERS} characters per generation.")
        if voice != "personal-user":
            raise ValueError("Personal Voice requires the personal-user voice.")
        if output_format != "wav":
            raise ValueError("Personal Voice currently generates WAV audio.")
        if not isinstance(reference_audio, bytes) or not reference_audio:
            raise ValueError("Record or upload a clean voice sample.")

        reference_mime = str(options.get("reference_mime") or "audio/wav")
        text_chunks = self._split_text(clean_text)
        generated_chunks: list[bytes] = []
        try:
            for text_chunk in text_chunks:
                payload = await asyncio.to_thread(
                    self._generate_sync,
                    text_chunk,
                    reference_audio,
                    reference_mime,
                )
                if len(payload) < 1000 or payload[:4] != b"RIFF":
                    raise RuntimeError("Chatterbox returned an invalid audio chunk.")
                generated_chunks.append(payload)
            payload = self._join_wav_chunks(generated_chunks)
        except Exception as exc:
            raise RuntimeError(f"Chatterbox Personal Voice could not complete the request: {exc}") from exc

        if len(payload) < 1000 or len(payload) > self.MAX_OUTPUT_BYTES:
            raise RuntimeError("Chatterbox returned an invalid audio file.")
        if payload[:4] != b"RIFF":
            raise RuntimeError("Chatterbox returned an unsupported audio format.")

        return payload, "audio/wav", {
            "provider": self.name,
            "engine": "chatterbox-multilingual",
            "runtime": "huggingface-zerogpu",
            "space_id": self.space_id,
            "voice": voice,
            "language": "el-GR",
            "voice_cloning": True,
            "identity_preservation": True,
            "shared_runtime": True,
            "chunked_generation": len(text_chunks) > 1,
            "chunk_count": len(text_chunks),
            "max_text_characters": self.MAX_TEXT_CHARACTERS,
            "mock": False,
        }
