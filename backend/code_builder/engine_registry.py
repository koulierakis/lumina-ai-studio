"""Coding-engine selection without removing the existing native Code Builder."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from .openhands_engine import OpenHandsEngine

NATIVE_ENGINE: Final[str] = "native"
OPENHANDS_ENGINE: Final[str] = "openhands"


@dataclass(frozen=True, slots=True)
class CodingEngineOption:
    name: str
    available: bool
    experimental: bool
    safe_mode: bool


class CodingEngineRegistry:
    def __init__(self, openhands: OpenHandsEngine | None = None) -> None:
        self.openhands = openhands or OpenHandsEngine()

    def options(self) -> tuple[CodingEngineOption, ...]:
        status = self.openhands.status()
        return (
            CodingEngineOption(NATIVE_ENGINE, True, False, True),
            CodingEngineOption(OPENHANDS_ENGINE, status.available, True, status.safe_mode),
        )

    def public_status(self) -> dict[str, object]:
        return {"default": NATIVE_ENGINE, "engines": [asdict(option) for option in self.options()]}

    def validate_selection(self, name: str | None) -> str:
        normalized = (name or NATIVE_ENGINE).strip().lower()
        if normalized == NATIVE_ENGINE: return NATIVE_ENGINE
        if normalized == OPENHANDS_ENGINE:
            if not self.openhands.status().available: raise RuntimeError("OpenHands engine is not available on this machine.")
            return OPENHANDS_ENGINE
        raise ValueError(f"Unknown coding engine: {name}")

    def execute_openhands(self, *, repository_root: str | Path, instruction: str):
        self.validate_selection(OPENHANDS_ENGINE)
        return self.openhands.execute(repository_root=repository_root, instruction=instruction)

    def execute(self, *, engine: str | None, repository_root: str | Path, instruction: str):
        selected = self.validate_selection(engine)
        if selected == OPENHANDS_ENGINE: return self.execute_openhands(repository_root=repository_root, instruction=instruction)
        raise RuntimeError("Native execution remains owned by the existing Code Builder task service.")

    def execute_for_review(self, *, engine: str | None, repository_root: str | Path, instruction: str) -> dict[str, object]:
        result = self.execute(engine=engine, repository_root=repository_root, instruction=instruction)
        payload = result.public_summary()
        payload.update({"engine": OPENHANDS_ENGINE, "requires_approval": True, "safe_mode": True})
        return payload
