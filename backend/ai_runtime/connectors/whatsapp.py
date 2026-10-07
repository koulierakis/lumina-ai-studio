"""WhatsApp connector for LUMINA Mind.

Uses the Meta WhatsApp Cloud API (or any compatible gateway with the same
request shape). Configuration:

- ``LUMINA_WHATSAPP_TOKEN``         bearer token (enables the connector)
- ``LUMINA_WHATSAPP_PHONE_ID``      sender phone-number id
- ``LUMINA_WHATSAPP_BASE_URL``      default ``https://graph.facebook.com/v20.0``
- ``LUMINA_WHATSAPP_DISABLED``      set true to force dry-run

Recipients are normalised to E.164 digits (Greek local numbers are prefixed
with the country code 30). Nothing is sent in dry-run mode.
"""

from __future__ import annotations

import re

import httpx

from .base import Connector, ConnectorResult, env_str

_NON_DIGITS = re.compile(r"[^\d]")


def normalise_phone(value: str) -> str:
    """Return an E.164 digit string, or '' when the input cannot be a number."""
    raw = (value or "").strip()
    if not raw:
        return ""
    digits = _NON_DIGITS.sub("", raw)
    if not digits:
        return ""
    if raw.startswith("+"):
        return digits
    if digits.startswith("00"):
        return digits[2:]
    if digits.startswith("30"):
        return digits
    if digits.startswith("0"):
        return "30" + digits[1:]
    if len(digits) == 10:
        return "30" + digits
    return digits


class WhatsAppConnector(Connector):
    id = "whatsapp"
    label = "WhatsApp"
    description = "Send WhatsApp messages through the owner's Cloud API account."

    def __init__(self) -> None:
        self.token = env_str("LUMINA_WHATSAPP_TOKEN")
        self.phone_id = env_str("LUMINA_WHATSAPP_PHONE_ID")
        self.base_url = env_str("LUMINA_WHATSAPP_BASE_URL", "https://graph.facebook.com/v20.0").rstrip("/")

    def configured(self) -> bool:
        return bool(self.token and self.phone_id)

    async def send(self, *, to: str, text: str) -> ConnectorResult:
        recipient = normalise_phone(to)
        body = text or ""
        if not recipient:
            return ConnectorResult(False, self.id, "invalid", "A recipient phone number is required.")
        if not body.strip():
            return ConnectorResult(False, self.id, "invalid", "A message body is required.")

        if not self.configured() or self.disabled():
            return ConnectorResult(
                True,
                self.id,
                "dry_run",
                f"[dry-run] Would WhatsApp +{recipient} ({len(body)} chars). "
                "Set LUMINA_WHATSAPP_TOKEN and LUMINA_WHATSAPP_PHONE_ID to send for real.",
                data={"to": recipient, "body_chars": len(body)},
                dry_run=True,
            )

        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }
        url = f"{self.base_url}/{self.phone_id}/messages"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url, json=payload, headers={"Authorization": f"Bearer {self.token}"}
                )
        except Exception as exc:  # noqa: BLE001
            return ConnectorResult(False, self.id, "failed", f"WhatsApp delivery failed: {type(exc).__name__}")
        if response.status_code < 200 or response.status_code >= 300:
            return ConnectorResult(
                False, self.id, "failed", f"WhatsApp API rejected the message (HTTP {response.status_code})."
            )
        return ConnectorResult(
            True, self.id, "sent", f"WhatsApp message sent to +{recipient}.", data={"to": recipient}
        )
