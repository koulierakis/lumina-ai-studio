"""Social connector for LUMINA Mind.

Publishes a text post to a webhook-driven gateway (Zapier/Make/n8n or a custom
endpoint). This keeps the connector provider-neutral: the gateway owns the
platform-specific OAuth. Configuration:

- ``LUMINA_SOCIAL_WEBHOOK_URL``  webhook that publishes the post (enables it)
- ``LUMINA_SOCIAL_CHANNELS``     comma-separated channel labels (default ``facebook``)
- ``LUMINA_SOCIAL_TOKEN``        optional bearer token for the webhook
- ``LUMINA_SOCIAL_DISABLED``     set true to force dry-run
"""

from __future__ import annotations

import httpx

from .base import Connector, ConnectorResult, env_str


class SocialConnector(Connector):
    id = "social"
    label = "Social media"
    description = "Publish a post to a social channel through a webhook gateway."

    def __init__(self) -> None:
        self.webhook_url = env_str("LUMINA_SOCIAL_WEBHOOK_URL")
        self.token = env_str("LUMINA_SOCIAL_TOKEN")
        channels = env_str("LUMINA_SOCIAL_CHANNELS", "facebook")
        self.channels = [part.strip() for part in channels.split(",") if part.strip()] or ["facebook"]

    def configured(self) -> bool:
        return bool(self.webhook_url)

    async def publish(self, *, text: str, channel: str = "") -> ConnectorResult:
        body = (text or "").strip()
        if not body:
            return ConnectorResult(False, self.id, "invalid", "Post text is required.")
        target = (channel or (self.channels[0] if self.channels else "facebook")).strip().lower()

        if not self.configured() or self.disabled():
            return ConnectorResult(
                True,
                self.id,
                "dry_run",
                f"[dry-run] Would publish to {target} ({len(body)} chars). "
                "Set LUMINA_SOCIAL_WEBHOOK_URL to publish for real.",
                data={"channel": target, "text_chars": len(body)},
                dry_run=True,
            )

        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        payload = {"channel": target, "text": body}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self.webhook_url, json=payload, headers=headers)
        except Exception as exc:  # noqa: BLE001
            return ConnectorResult(False, self.id, "failed", f"Social publish failed: {type(exc).__name__}")
        if response.status_code < 200 or response.status_code >= 300:
            return ConnectorResult(
                False, self.id, "failed", f"Social webhook rejected the post (HTTP {response.status_code})."
            )
        return ConnectorResult(
            True, self.id, "published", f"Post published to {target}.", data={"channel": target}
        )
