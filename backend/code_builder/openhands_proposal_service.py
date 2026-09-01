"""Convert reviewed OpenHands sandbox changes into native Code Builder proposals."""
from __future__ import annotations

import hashlib
from typing import Final

from .models import ChangeType, ProposedFileChange, RiskLevel
from .openhands_change_capture_service import OpenHandsFileChange

RISKY_PATH_MARKERS: Final[tuple[str, ...]] = (
    ".github/", "backend/server.py", "launcher/", "docker-compose", "package.json",
    "backend/requirements", "pyproject.toml",
)


def _sha256(text: str | None) -> str | None:
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _risk_for_path(relative_path: str) -> RiskLevel:
    normalized = relative_path.replace("\\", "/").lower()
    if any(marker in normalized for marker in RISKY_PATH_MARKERS):
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


class OpenHandsProposalService:
    """Bridge OpenHands changes into LUMINA's existing approval contract."""

    def convert(
        self,
        changes: tuple[OpenHandsFileChange, ...],
        *,
        reason: str = "Proposed by OpenHands inside an isolated LUMINA workspace.",
    ) -> tuple[ProposedFileChange, ...]:
        proposals: list[ProposedFileChange] = []
        mapping = {
            "created": ChangeType.CREATE,
            "modified": ChangeType.MODIFY,
            "deleted": ChangeType.DELETE,
        }
        for change in changes:
            change_type = mapping[change.change_type]
            proposals.append(
                ProposedFileChange(
                    relative_path=change.relative_path,
                    change_type=change_type,
                    old_content=change.before_text,
                    new_content=change.after_text,
                    old_sha256=_sha256(change.before_text),
                    new_sha256=_sha256(change.after_text),
                    summary=f"OpenHands {change.change_type}: {change.relative_path}",
                    reason=reason,
                    risk_level=_risk_for_path(change.relative_path),
                    approved=False,
                )
            )
        return tuple(proposals)
