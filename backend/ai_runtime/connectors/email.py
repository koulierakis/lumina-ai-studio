"""Email connector (SMTP) for LUMINA Mind.

Configuration (environment only; never committed):

- ``LUMINA_SMTP_HOST``      SMTP host (enables the connector)
- ``LUMINA_SMTP_PORT``      default 587
- ``LUMINA_SMTP_USER``      optional username
- ``LUMINA_SMTP_PASSWORD``  optional password
- ``LUMINA_SMTP_FROM``      optional From address (defaults to the user)
- ``LUMINA_SMTP_USE_TLS``   default true (STARTTLS); set false for implicit TLS
- ``LUMINA_EMAIL_DISABLED`` set true to force dry-run
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from .base import Connector, ConnectorResult, env_flag, env_str, header_safe


class EmailConnector(Connector):
    id = "email"
    label = "Email"
    description = "Send email through the owner's SMTP account."

    def __init__(self) -> None:
        self.host = env_str("LUMINA_SMTP_HOST")
        self.port = int(env_str("LUMINA_SMTP_PORT", "587"))
        self.user = env_str("LUMINA_SMTP_USER")
        self.password = env_str("LUMINA_SMTP_PASSWORD")
        self.sender = env_str("LUMINA_SMTP_FROM", self.user)
        self.use_tls = env_flag("LUMINA_SMTP_USE_TLS", True)

    def configured(self) -> bool:
        return bool(self.host and self.sender)

    async def send(self, *, to: str, subject: str, body: str) -> ConnectorResult:
        to = (to or "").strip()
        subject = (subject or "").strip()
        body = body or ""
        if not to or "@" not in to:
            return ConnectorResult(False, self.id, "invalid", "A valid recipient address is required.")
        if not header_safe(to) or not header_safe(subject):
            return ConnectorResult(False, self.id, "invalid", "Recipient and subject must not contain line breaks.")

        if not self.configured() or self.disabled():
            return ConnectorResult(
                True,
                self.id,
                "dry_run",
                f"[dry-run] Would email {to} — subject {subject!r} ({len(body)} chars). "
                "Set LUMINA_SMTP_HOST and LUMINA_SMTP_FROM to send for real.",
                data={"to": to, "subject": subject, "body_chars": len(body)},
                dry_run=True,
            )

        message = EmailMessage()
        message["To"] = to
        message["From"] = self.sender
        message["Subject"] = subject or "(no subject)"
        message.set_content(body)

        def _deliver() -> None:
            if self.use_tls:
                with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                    server.starttls()
                    if self.user:
                        server.login(self.user, self.password)
                    server.send_message(message)
            else:
                with smtplib.SMTP_SSL(self.host, self.port, timeout=30) as server:
                    if self.user:
                        server.login(self.user, self.password)
                    server.send_message(message)

        try:
            await asyncio.to_thread(_deliver)
        except Exception as exc:  # noqa: BLE001 - surface a clean, non-secret error
            return ConnectorResult(False, self.id, "failed", f"SMTP delivery failed: {type(exc).__name__}")
        return ConnectorResult(
            True,
            self.id,
            "sent",
            f"Email sent to {to}.",
            data={"to": to, "subject": subject},
        )
