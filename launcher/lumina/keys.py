"""Interactive API key setup for backend/.env.

Keys are entered with hidden input and written straight to ``backend/.env``.
Values are never echoed, logged, or passed as command-line arguments, so they
do not leak into shell history.
"""
from __future__ import annotations

import getpass
from pathlib import Path
from typing import Callable

KEY_CATALOG: list[tuple[str, str]] = [
    ("GROQ_API_KEY", "Groq - Documents AI + Mind advisor (free tier)"),
    ("GEMINI_API_KEY", "Gemini - Photo / Image Studio (free tier)"),
    ("OPENAI_API_KEY", "OpenAI Images (paid)"),
    ("CLOUDFLARE_API_TOKEN", "Cloudflare Workers AI - FLUX images"),
    ("CLOUDFLARE_ACCOUNT_ID", "Cloudflare account ID (needed with the token)"),
    ("REPLICATE_API_TOKEN", "Replicate - FLUX (HF) images"),
    ("HF_TOKEN", "Hugging Face - Video Studio"),
    ("LUMA_API_KEY", "Luma Dream Machine - Video Studio (paid)"),
    ("ELEVENLABS_API_KEY", "ElevenLabs - Voice Studio"),
    ("HEYGEN_API_KEY", "HeyGen - talking face"),
]


def env_path(repo_root: Path) -> Path:
    return repo_root / "backend" / ".env"


def apply_keys(path: Path, updates: dict[str, str]) -> int:
    """Replace existing ``KEY=`` lines and append new ones. Returns keys written."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(updates)
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        name = None
        if "=" in stripped and not stripped.startswith("#"):
            name = stripped.split("=", 1)[0]
        if name in remaining:
            output.append(f"{name}={remaining.pop(name)}")
        else:
            output.append(line)
    for name, value in remaining.items():
        output.append(f"{name}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    return len(updates)


def parse_selection(raw: str, catalog: list[tuple[str, str]] = KEY_CATALOG) -> list[str]:
    """Turn "1,2" or "groq gemini" or "all" into a unique list of env names."""
    text = (raw or "").strip().lower()
    if text in {"all", "*"}:
        return [name for name, _ in catalog]
    chosen: list[str] = []
    for token in text.replace(",", " ").split():
        if token.isdigit():
            index = int(token)
            if 1 <= index <= len(catalog):
                chosen.append(catalog[index - 1][0])
        else:
            upper = token.upper()
            matches = [name for name, _ in catalog if name == upper or name.startswith(upper + "_")]
            chosen.extend(matches)
    seen: set[str] = set()
    result: list[str] = []
    for name in chosen:
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def set_keys_interactively(
    repo_root: Path,
    *,
    prompt: Callable[[str], str] = input,
    secret: Callable[[str], str] = getpass.getpass,
    out: Callable[[str], None] = print,
) -> dict[str, str]:
    path = env_path(repo_root)
    if not path.exists():
        example = repo_root / "backend" / ".env.example"
        template = example.read_text(encoding="utf-8") if example.exists() else ""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template, encoding="utf-8")

    out(f"Writing to {path}")
    out("Available API keys:")
    for index, (name, label) in enumerate(KEY_CATALOG, 1):
        out(f"  {index:>2}. {name:<24} {label}")

    selection = prompt("Which to set? numbers/comma, or 'all' (Enter cancels): ")
    chosen = parse_selection(selection)
    if not chosen:
        out("Nothing selected. No changes made.")
        return {}

    updates: dict[str, str] = {}
    for name in chosen:
        try:
            value = secret(f"{name} (hidden input, Enter to skip): ")
        except (EOFError, KeyboardInterrupt):
            out("Cancelled.")
            break
        value = (value or "").strip()
        if value:
            updates[name] = value

    if not updates:
        out("No keys entered. No changes made.")
        return {}

    apply_keys(path, updates)
    out(f"Saved {len(updates)} key(s). Values were not printed or logged.")
    out("Restart LUMINA for the new keys to take effect.")
    return updates
