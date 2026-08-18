from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "backend" / "code_builder" / "planning_service.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"Could not find {label} in {TARGET}")
    return text.replace(old, new, 1)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'DEFAULT_MAX_OUTPUT_TOKENS: Final[int] = 2_048',
        'DEFAULT_MAX_OUTPUT_TOKENS: Final[int] = 1_024',
        'default output-token budget',
    )
    text = replace_once(
        text,
        'DEFAULT_INPUT_TOKEN_SAFETY_MARGIN: Final[int] = 2_048',
        'DEFAULT_INPUT_TOKEN_SAFETY_MARGIN: Final[int] = 256',
        'default input safety margin',
    )
    TARGET.write_text(text, encoding="utf-8")
    print("CODE BUILDER PLANNING DEFAULTS APPLIED")


if __name__ == "__main__":
    main()
