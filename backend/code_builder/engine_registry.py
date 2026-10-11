"""Coding-engine selection without removing the existing native Code Builder.

Policy (see docs/architecture/ENGINE_POLICY.md):

    gold_builder  PRIMARY   (opt-in service boundary; recommended when available)
    openhands     SECONDARY (experimental alternate agent)
    native        LEGACY    (safe default fallback, always available)

The native engine stays the default until Gold Builder is verified available on
this machine, so a machine without the service never breaks.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from .gold_builder_engine import GoldBuilderEngine
from .openhands_engine import OpenHandsEngine

NATIVE_ENGINE: Final[str] = "native"
OPENHANDS_ENGINE: Final[str] = "openhands"
GOLD_BUILDER_ENGINE: Final[str] = "gold_builder"

_ORDER: Final[tuple[str, ...]] = (GOLD_BUILDER_ENGINE, OPENHANDS_ENGINE, NATIVE_ENGINE)
_ROLES: Final[dict[str, str]] = {
    GOLD_BUILDER_ENGINE: "primary",
    OPENHANDS_ENGINE: "secondary",
    NATIVE_ENGINE: "legacy_fallback",
}


@dataclass(frozen=True, slots=True)
class CodingEngineOption:
    name: str
    available: bool
    experimental: bool
    safe_mode: bool
    role: str = ""
    detail: str = ""


class CodingEngineRegistry:
    def __init__(self, openhands: OpenHandsEngine | None = None, gold_builder: GoldBuilderEngine | None = None) -> None:
        self.openhands = openhands or OpenHandsEngine()
        self.gold_builder = gold_builder or GoldBuilderEngine()

    def options(self) -> tuple[CodingEngineOption, ...]:
        gold = self.gold_builder.status()
        openhands = self.openhands.status()
        return (
            CodingEngineOption(GOLD_BUILDER_ENGINE, gold.available, False, True, "primary", gold.detail),
            CodingEngineOption(OPENHANDS_ENGINE, openhands.available, True, openhands.safe_mode, "secondary", "experimental"),
            CodingEngineOption(NATIVE_ENGINE, True, False, True, "legacy_fallback", "always available"),
        )

    def _by_name(self) -> dict[str, CodingEngineOption]:
        return {option.name: option for option in self.options()}

    def public_status(self) -> dict[str, object]:
        options = self._by_name()
        preferred = GOLD_BUILDER_ENGINE if options[GOLD_BUILDER_ENGINE].available else NATIVE_ENGINE
        return {
            # The safe default stays native until Gold Builder is verified here.
            "default": NATIVE_ENGINE,
            "preferred": preferred,
            "engines": [asdict(options[name]) for name in _ORDER],
            "roles": dict(_ROLES),
            "order": list(_ORDER),
            "selection": list(_ORDER),
            "migration_mode": "parallel",
            "native_preserved": True,
            "approval_required_for_openhands": True,
            "openhands_runtime_validated": False,
            "openhands_ready": False,
        }

    def suggest_engine(self, requested: str | None = None) -> str:
        """Deterministic, understandable auto-routing."""
        if requested:
            return self.validate_selection(requested)
        options = self._by_name()
        if options[GOLD_BUILDER_ENGINE].available:
            return GOLD_BUILDER_ENGINE
        if options[OPENHANDS_ENGINE].available:
            return OPENHANDS_ENGINE
        return NATIVE_ENGINE

    def validate_selection(self, name: str | None) -> str:
        selected = (name or NATIVE_ENGINE).strip().lower()
        if selected == NATIVE_ENGINE:
            return NATIVE_ENGINE
        if selected == OPENHANDS_ENGINE:
            if not self.openhands.status().available:
                raise RuntimeError("OpenHands engine is not available on this machine.")
            return OPENHANDS_ENGINE
        if selected == GOLD_BUILDER_ENGINE:
            if not self.gold_builder.status().available:
                raise RuntimeError("Gold Builder engine is not reachable on this machine.")
            return GOLD_BUILDER_ENGINE
        raise ValueError(f"Unknown coding engine: {name}")

    def execute(self, *, engine: str | None, repository_root: str | Path, instruction: str):
        if self.validate_selection(engine) == OPENHANDS_ENGINE:
            return self.openhands.execute(repository_root=repository_root, instruction=instruction)
        raise RuntimeError("Native execution remains owned by the existing Code Builder task service.")

    def execute_for_review(self, *, engine: str | None, repository_root: str | Path, instruction: str) -> dict[str, object]:
        result = self.execute(engine=engine, repository_root=repository_root, instruction=instruction)
        payload = result.public_summary()
        payload.update({"engine": OPENHANDS_ENGINE, "requires_approval": True, "safe_mode": True, "applied": False, "status": "awaiting_approval", "can_apply": False, "source_repository_unchanged": True, "review_only": True, "message": "OpenHands finished in a safe copy. Review the proposed changes before LUMINA can apply anything.", "next_action": "review_changes", "ready": False, "runtime_validated": False, "backup_required_before_apply": True, "rollback_required_after_apply": True})
        return payload
