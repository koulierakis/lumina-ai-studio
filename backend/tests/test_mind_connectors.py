"""LUMINA Mind connectors: configuration, dry-run, real send, and gating.

Deterministic and network-free: SMTP and HTTP are monkeypatched, so the tests
exercise the real connector code paths (validation, dry-run, header-safety,
phone normalisation) without contacting any external service.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ai_runtime.capabilities import MindOrchestrator, resolve_intent
from ai_runtime.connectors import connector_status, get_connector
from ai_runtime.connectors.email import EmailConnector
from ai_runtime.connectors.social import SocialConnector
from ai_runtime.connectors.whatsapp import WhatsAppConnector, normalise_phone

OWNER = "owner@lumina.local"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (
        "LUMINA_SMTP_HOST", "LUMINA_SMTP_PORT", "LUMINA_SMTP_USER", "LUMINA_SMTP_PASSWORD",
        "LUMINA_SMTP_FROM", "LUMINA_SMTP_USE_TLS", "LUMINA_EMAIL_DISABLED",
        "LUMINA_WHATSAPP_TOKEN", "LUMINA_WHATSAPP_PHONE_ID", "LUMINA_WHATSAPP_BASE_URL",
        "LUMINA_WHATSAPP_DISABLED", "LUMINA_SOCIAL_WEBHOOK_URL", "LUMINA_SOCIAL_TOKEN",
        "LUMINA_SOCIAL_CHANNELS", "LUMINA_SOCIAL_DISABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    yield


# --------------------------------------------------------------------- email
def test_email_dry_run_when_unconfigured():
    connector = EmailConnector()
    assert connector.configured() is False
    assert connector.mode() == "dry_run"
    result = asyncio.run(connector.send(to="a@b.com", subject="Hi", body="Hello"))
    assert result.ok and result.dry_run and result.status == "dry_run"


def test_email_rejects_invalid_recipient():
    result = asyncio.run(EmailConnector().send(to="not-an-address", subject="x", body="y"))
    assert result.ok is False and result.status == "invalid"


def test_email_rejects_header_injection():
    connector = EmailConnector()
    result = asyncio.run(connector.send(to="a@b.com", subject="ok\r\nBcc: evil@x.com", body="y"))
    assert result.ok is False and result.status == "invalid"


def test_email_real_send_uses_smtp(monkeypatch):
    monkeypatch.setenv("LUMINA_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("LUMINA_SMTP_FROM", "owner@example.com")
    monkeypatch.setenv("LUMINA_SMTP_USER", "owner@example.com")
    monkeypatch.setenv("LUMINA_SMTP_PASSWORD", "secret")
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent["host"] = host
            sent["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            sent["tls"] = True

        def login(self, user, password):
            sent["login"] = (user, password)

        def send_message(self, message):
            sent["to"] = message["To"]
            sent["subject"] = message["Subject"]

    import ai_runtime.connectors.email as email_mod

    monkeypatch.setattr(email_mod.smtplib, "SMTP", FakeSMTP)
    connector = EmailConnector()
    assert connector.mode() == "live"
    result = asyncio.run(connector.send(to="client@example.com", subject="Quote", body="Here it is"))
    assert result.ok and result.status == "sent" and result.dry_run is False
    assert sent["host"] == "smtp.example.com"
    assert sent["to"] == "client@example.com"
    assert sent["subject"] == "Quote"
    assert sent["login"] == ("owner@example.com", "secret")


def test_email_disabled_forces_dry_run(monkeypatch):
    monkeypatch.setenv("LUMINA_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("LUMINA_SMTP_FROM", "owner@example.com")
    monkeypatch.setenv("LUMINA_EMAIL_DISABLED", "true")
    connector = EmailConnector()
    assert connector.mode() == "disabled"
    assert asyncio.run(connector.send(to="a@b.com", subject="x", body="y")).dry_run is True


# ------------------------------------------------------------------ whatsapp
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+30 694 123 4567", "306941234567"),
        ("6941234567", "306941234567"),
        ("06941234567", "306941234567"),
        ("00306941234567", "306941234567"),
        ("447700900123", "447700900123"),
        ("", ""),
        ("abc", ""),
    ],
)
def test_normalise_phone(raw, expected):
    assert normalise_phone(raw) == expected


def test_whatsapp_dry_run_when_unconfigured():
    connector = WhatsAppConnector()
    assert connector.configured() is False
    result = asyncio.run(connector.send(to="6941234567", text="Γεια"))
    assert result.ok and result.dry_run and result.data["to"] == "306941234567"


def test_whatsapp_requires_recipient():
    result = asyncio.run(WhatsAppConnector().send(to="", text="x"))
    assert result.ok is False and result.status == "invalid"


def test_whatsapp_real_send(monkeypatch):
    monkeypatch.setenv("LUMINA_WHATSAPP_TOKEN", "token-123")
    monkeypatch.setenv("LUMINA_WHATSAPP_PHONE_ID", "555000")
    captured = {}

    class FakeResponse:
        status_code = 200

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResponse()

    import ai_runtime.connectors.whatsapp as wa_mod

    monkeypatch.setattr(wa_mod.httpx, "AsyncClient", FakeClient)
    connector = WhatsAppConnector()
    assert connector.mode() == "live"
    result = asyncio.run(connector.send(to="+306941234567", text="Καλημέρα"))
    assert result.ok and result.status == "sent"
    assert captured["url"].endswith("/555000/messages")
    assert captured["json"]["to"] == "306941234567"
    assert captured["headers"]["Authorization"] == "Bearer token-123"


def test_whatsapp_api_failure_is_reported(monkeypatch):
    monkeypatch.setenv("LUMINA_WHATSAPP_TOKEN", "token-123")
    monkeypatch.setenv("LUMINA_WHATSAPP_PHONE_ID", "555000")

    class FakeResponse:
        status_code = 401

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            return FakeResponse()

    import ai_runtime.connectors.whatsapp as wa_mod

    monkeypatch.setattr(wa_mod.httpx, "AsyncClient", FakeClient)
    result = asyncio.run(WhatsAppConnector().send(to="6941234567", text="x"))
    assert result.ok is False and result.status == "failed"


# -------------------------------------------------------------------- social
def test_social_dry_run_when_unconfigured():
    connector = SocialConnector()
    result = asyncio.run(connector.publish(text="Νέο πρόγραμμα γυμναστηρίου", channel="instagram"))
    assert result.ok and result.dry_run and result.data["channel"] == "instagram"


def test_social_real_publish(monkeypatch):
    monkeypatch.setenv("LUMINA_SOCIAL_WEBHOOK_URL", "https://hooks.example/publish")
    captured = {}

    class FakeResponse:
        status_code = 200

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            return FakeResponse()

    import ai_runtime.connectors.social as social_mod

    monkeypatch.setattr(social_mod.httpx, "AsyncClient", FakeClient)
    result = asyncio.run(SocialConnector().publish(text="Post body", channel="facebook"))
    assert result.ok and result.status == "published"
    assert captured["url"] == "https://hooks.example/publish"
    assert captured["json"] == {"channel": "facebook", "text": "Post body"}


# ------------------------------------------------------------------ registry
def test_connector_status_lists_all_channels():
    ids = {entry["id"] for entry in connector_status()}
    assert ids == {"email", "whatsapp", "social"}
    assert all(entry["mode"] == "dry_run" for entry in connector_status())
    assert get_connector("whatsapp") is not None
    assert get_connector("nope") is None


# -------------------------------------------------------------------- intent
@pytest.mark.parametrize(
    ("message", "action", "expected"),
    [
        ("στείλε email στο client@example.com να επιβεβαιώσεις το ραντεβού", "send_email",
         {"to": "client@example.com"}),
        ("στείλε whatsapp στο 6941234567 ότι άνοιξε το μάθημα", "send_whatsapp",
         {"to": "6941234567"}),
        ("δημοσίευσε στο facebook το νέο πρόγραμμα του γυμναστηρίου", "publish_social",
         {"channel": "facebook"}),
    ],
)
def test_resolve_connect_intents(message, action, expected):
    intent = resolve_intent(message)
    assert intent is not None, message
    assert intent.capability == "connect"
    assert intent.action == action
    for key, value in expected.items():
        assert intent.params[key] == value


def test_connect_intent_is_approval_gated():
    intent = resolve_intent("στείλε email στο a@b.com ένα μήνυμα")
    assert intent is not None and intent.risk == "approval"


def test_plain_chat_is_not_a_connect_intent():
    assert resolve_intent("πώς πάει η επιχείρηση σήμερα;") is None


# ---------------------------------------------------------------- gating E2E
def _orchestrator(tmp_path: Path) -> MindOrchestrator:
    return MindOrchestrator(root=tmp_path / "mind")


def test_connector_action_requires_approval_then_executes_dry_run(tmp_path):
    orchestrator = _orchestrator(tmp_path)
    pending = asyncio.run(
        orchestrator.execute(
            OWNER, "connect", "send_email",
            {"to": "client@example.com", "subject": "Hi", "body": "Hello"},
            session_id="s-connect",
        )
    )
    assert pending["status"] == "needs_approval"
    stored = orchestrator.pending(OWNER, "s-connect")
    assert stored is not None and stored["capability"] == "connect"

    approved = asyncio.run(orchestrator.handle_decision(OWNER, "s-connect", "ναι"))
    assert approved is not None and approved["status"] == "executed"
    assert approved["result"]["dry_run"] is True
    assert orchestrator.pending(OWNER, "s-connect") is None


def test_connector_decline_does_not_send(tmp_path):
    orchestrator = _orchestrator(tmp_path)
    asyncio.run(
        orchestrator.execute(
            OWNER, "connect", "send_whatsapp",
            {"to": "6941234567", "body": "Γεια"},
            session_id="s-decline",
        )
    )
    declined = asyncio.run(orchestrator.handle_decision(OWNER, "s-decline", "όχι"))
    assert declined is not None and declined["status"] == "declined"


def test_connector_missing_params_rejected(tmp_path):
    from ai_runtime.capabilities import CapabilityExecutionError

    orchestrator = _orchestrator(tmp_path)
    with pytest.raises(CapabilityExecutionError):
        asyncio.run(orchestrator.execute(OWNER, "connect", "send_email", {"to": "a@b.com"}))


# ------------------------------------------------------------- HTTP surface
def test_mind_connector_endpoints(tmp_path) -> None:
    """The connector routes exist, report status, and gate execution via Mind."""
    import httpx

    from auth import issue_token
    from server import app

    headers = {"Authorization": f"Bearer {issue_token(OWNER)}"}
    transport = httpx.ASGITransport(app=app)
    base = "http://127.0.0.1:8000"

    async def run() -> None:
        async with httpx.AsyncClient(transport=transport, base_url=base, headers=headers) as client:
            status = (await client.get("/api/runtime/mind/connectors")).json()
            assert {c["id"] for c in status["connectors"]} == {"email", "whatsapp", "social"}

            catalog = (await client.get("/api/runtime/mind/capabilities")).json()["capabilities"]
            connect = next(c for c in catalog if c["id"] == "connect")
            assert "send_email" in connect["operations"]

            gated = (await client.post("/api/runtime/mind/execute", json={
                "capability": "connect",
                "action": "send_whatsapp",
                "params": {"to": "6941234567", "body": "Γεια"},
                "session_id": "s-http",
            })).json()
            assert gated["status"] == "needs_approval"

            approved = (await client.post("/api/runtime/mind/decide", json={
                "decision": "approve", "session_id": "s-http",
            })).json()
            assert approved["status"] == "executed"
            assert approved["result"]["dry_run"] is True

            direct = (await client.post(
                "/api/runtime/mind/connectors/social/publish",
                json={"body": "Δοκιμή", "channel": "instagram"},
            )).json()
            assert direct["status"] == "dry_run" and direct["data"]["channel"] == "instagram"

    asyncio.run(run())

