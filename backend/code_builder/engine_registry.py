"""Coding-engine selection without removing the existing native Code Builder."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Final

from .openhands_engine import OpenHandsEngine

NATIVE_ENGINE: Final[str] = "native"
OPENHANDS_ENGINE: Final[str] = "openhands"


@dataclass(frozen=True, slots=True)
class CodingEngineOption:
    name: str
    available: bool
    experimental: bool


class CodingEngineRegistry:
    """Advertises native and optional OpenHands engines for a gradual migration."""

    def __init__(self, openhands: OpenHandsEngine | None = None) -> None:
        self.openhands = openhands or OpenHandsEngine()

    def options(self) -> tuple[CodingEngineOption, ...]:
        openhands_status = self.openhands.status()
        return (
            CodingEngineOption(NATIVE_ENGINE, True, False),
            CodingEngineOption(OPENHANDS_ENGINE, openhands_status.available, True),
        )

    def public_status(self) -> dict[str, object]:
        return {"default": NATIVE_ENGINE, "engines": [asdict(option) for option in self.options()]}

    def validate_selection(self, name: str | None) -> str:
        normalized = (name or NATIVE_ENGINE).strip().lower()
        if normalized == NATIVE_ENGINE:
            return NATIVE_ENGINE
        if normalized == OPENHANDS_ENGINE:
            if not self.openhands.status().available:
                raise RuntimeError("OpenHands engine is not available on this machine.")
            return OPENHANDS_ENGINE
        raise ValueError(f"Unknown coding engine: {name}")

    def execute_openhands(self, *, repository_root: str, instruction: str):
        self.validate_selection(OPENHANDS_ENGINE)
        return self.openhands.execute(repository_root=repository_root, instruction=instruction)
