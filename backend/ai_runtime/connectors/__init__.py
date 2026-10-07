"""LUMINA Mind outbound connectors.

Registers the owner's communication channels (email, WhatsApp, social) behind a
small registry the orchestrator can route to. Each connector degrades to a
validated dry-run when unconfigured, so the Mind studio works without
credentials and never claims a message was sent when it was not.
"""

from __future__ import annotations

from .base import Connector, ConnectorResult  # noqa: F401
from .email import EmailConnector
from .social import SocialConnector
from .whatsapp import WhatsAppConnector

_CONNECTORS: dict[str, Connector] = {
    connector.id: connector
    for connector in (EmailConnector(), WhatsAppConnector(), SocialConnector())
}


def get_connector(connector_id: str) -> Connector | None:
    return _CONNECTORS.get((connector_id or "").strip().lower())


def connector_status() -> list[dict]:
    """Public status of every connector (for UI and model grounding)."""
    return [connector.status() for connector in _CONNECTORS.values()]


__all__ = [
    "Connector",
    "ConnectorResult",
    "EmailConnector",
    "SocialConnector",
    "WhatsAppConnector",
    "connector_status",
    "get_connector",
]
