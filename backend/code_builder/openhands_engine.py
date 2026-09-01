"""Optional OpenHands coding engine boundary for LUMINA Code Builder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .openhands_execution_service import OpenHandsExecutionResult, OpenHandsExecutionService


@dataclass(frozen=True, slots=True)
class OpenHandsEngineStatus:
    name: str
    available: bool
    safe_mode: bool = True


class OpenHandsEngine:
    """Small boundary used by Code Builder without replacing its safety lifecycle."""

    name = "openhands"

    def __init__(self, execution_service: OpenHandsExecutionService | None = None) -> None:
        self.execution_service = execution_service or OpenHandsExecutionService()

    def status(self) -> OpenHandsEngineStatus:
        return OpenHandsEngineStatus(
            name=self.name,
            available=self.execution_service.adapter.is_available(),
            safe_mode=True,
        )

    def execute(self, *, repository_root: str | Path, instruction: str) -> OpenHandsExecutionResult:
        return self.execution_service.execute(
            repository_root=repository_root,
            instruction=instruction,
        )
