"""Read-only HTTP surface for Code Builder engine availability."""
from __future__ import annotations

from fastapi import APIRouter

from .engine_registry import CodingEngineRegistry

router = APIRouter()


@router.get("/engines")
def get_code_builder_engines() -> dict[str, object]:
    """Return engine choices without changing the native-default policy."""
    status = CodingEngineRegistry().public_status()
    status["openhands_apply_enabled"] = False
    return status
