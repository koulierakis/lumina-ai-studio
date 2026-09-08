"""Standalone Hugging Face text-to-video smoke test for LUMINA."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from huggingface_hub import InferenceClient

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env")

HF_TOKEN = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACEHUB_API_TOKEN")
if not HF_TOKEN:
    raise RuntimeError("HF_TOKEN was not found. Set it in backend/.env or as an environment variable.")

# Wan 2.1 is the published 1.3B text-to-video model. Wan 2.2 does not publish a T2V-1.3B model ID.
MODEL = "Wan-AI/Wan2.1-T2V-1.3B"
PROMPT = "a cinematic shot of a neon sign"
OUTPUT_FILE = BACKEND_DIR / "test_output.mp4"

client = InferenceClient(api_key=HF_TOKEN, timeout=600)

print("Connecting to Hugging Face...")
print(f"Model: {MODEL}")
print("Generating test video...")

try:
    video_bytes = client.text_to_video(PROMPT, model=MODEL)
    if not video_bytes:
        raise RuntimeError("Hugging Face returned an empty result.")
    OUTPUT_FILE.write_bytes(video_bytes)
    print("SUCCESS")
    print(f"Video saved to: {OUTPUT_FILE}")
    print(f"Size: {len(video_bytes) / (1024 * 1024):.2f} MB")
except Exception as exc:
    print("FAILED")
    print(f"{type(exc).__name__}: {exc}")
    raise
