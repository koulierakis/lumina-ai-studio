"""Shared connector primitives for LUMINA Mind outbound actions.

A connector is environment-configured and capability-driven. When it is not
configured (or is explicitly disabled) it runs in **dry-run** mode: the request
is validated and reported, but nothing leaves the machine. This keeps the Mind
studio usable without credentials while never fabricating that a message was
sent.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

_SENSITIVE_MARKERS = ("token", "secret", "password", "authorization", "api_key", "apikey")


def env_str(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else default


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def redact(value: Any) -> Any:
    """Recursively replace values whose key looks secret-bearing."""
    if isinstance(value, dict):
        return {
            str(key): "[redacted]" if any(marker in str(key).lower() for marker in _SENSITIVE_MARKERS) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def header_safe(value: str) -> bool:
    """Reject CR/LF so a value cannot inject extra mail headers."""
    return "\r" not in value and "\n" not in value


@dataclass
class ConnectorResult:
    """Outcome of a connector action. ``dry_run`` means nothing left the host."""

    ok: bool
    connector: str
    status: str
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "connector": self.connector,
            "status": self.status,
            "detail": self.detail,
            "dry_run": self.dry_run,
            "data": redact(self.data),
        }


class Connector(ABC):
    id: str = "abstract"
    label: str = ""
    description: str = ""

    @abstractmethod
    def configured(self) -> bool:
        """True when the connector holds enough configuration to act for real."""

    def disabled(self) -> bool:
        return env_flag(f"LUMINA_{self.id.upper()}_DISABLED")

    def mode(self) -> str:
        if self.disabled():
            return "disabled"
        return "live" if self.configured() else "dry_run"

    def status(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "configured": self.configured(),
            "disabled": self.disabled(),
            "mode": self.mode(),
        }
