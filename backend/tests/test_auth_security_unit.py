from __future__ import annotations

from pathlib import Path

import bcrypt
import pytest
from auth import verify_credentials, _allowed_emails, _is_e2e_email, _is_owner_email
from dotenv import dotenv_values
from login_limiter import LoginRateLimiter


def test_hashed_password_takes_precedence(monkeypatch):
    password_hash = bcrypt.hashpw(b"correct horse", bcrypt.gensalt()).decode()
    monkeypatch.setenv("OWNER_EMAIL", "owner@example.com")
    monkeypatch.setenv("OWNER_PASSWORD_HASH", password_hash)
    monkeypatch.setenv("OWNER_PASSWORD", "legacy-password")

    assert verify_credentials(" OWNER@example.com ", "correct horse")
    assert not verify_credentials("owner@example.com", "legacy-password")
    assert not verify_credentials("other@example.com", "correct horse")


def test_malformed_hash_fails_closed(monkeypatch):
    monkeypatch.setenv("OWNER_EMAIL", "owner@example.com")
    monkeypatch.setenv("OWNER_PASSWORD_HASH", "not-a-bcrypt-hash")
    monkeypatch.setenv("OWNER_PASSWORD", "legacy-password")

    assert not verify_credentials("owner@example.com", "legacy-password")


def test_plaintext_password_remains_backward_compatible(monkeypatch):
    monkeypatch.setenv("OWNER_EMAIL", "owner@example.com")
    monkeypatch.delenv("OWNER_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("OWNER_PASSWORD", "legacy-password")

    assert verify_credentials("owner@example.com", "legacy-password")
    assert not verify_credentials("owner@example.com", "wrong")


def test_backend_env_owner_credentials_are_accepted(monkeypatch):
    config = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    if not config.get("OWNER_EMAIL") or not config.get("OWNER_PASSWORD"):
        pytest.skip("Local owner credentials are not configured.")
    monkeypatch.setenv("OWNER_EMAIL", config["OWNER_EMAIL"])
    monkeypatch.setenv("OWNER_PASSWORD", config["OWNER_PASSWORD"])
    monkeypatch.delenv("OWNER_PASSWORD_HASH", raising=False)
    assert verify_credentials(config["OWNER_EMAIL"], config["OWNER_PASSWORD"])
    assert not verify_credentials(config["OWNER_EMAIL"], "invalid-password")


# --- E2E account tests ---


def test_e2e_account_with_password_hash(monkeypatch):
    password_hash = bcrypt.hashpw(b"e2e-secret", bcrypt.gensalt()).decode()
    monkeypatch.setenv("OWNER_EMAIL", "owner@example.com")
    monkeypatch.setenv("OWNER_PASSWORD_HASH", bcrypt.hashpw(b"owner-secret", bcrypt.gensalt()).decode())
    monkeypatch.setenv("LUMINA_E2E_EMAIL", "e2e@lumina.test")
    monkeypatch.setenv("LUMINA_E2E_PASSWORD_HASH", password_hash)

    # E2E account works
    assert verify_credentials("e2e@lumina.test", "e2e-secret")
    assert not verify_credentials("e2e@lumina.test", "wrong")

    # Owner account still works
    assert verify_credentials("owner@example.com", "owner-secret")
    assert not verify_credentials("owner@example.com", "wrong")

    # Cross-account fails
    assert not verify_credentials("owner@example.com", "e2e-secret")
    assert not verify_credentials("e2e@lumina.test", "owner-secret")


def test_e2e_account_with_plaintext_password_backward_compat(monkeypatch):
    monkeypatch.setenv("OWNER_EMAIL", "owner@example.com")
    monkeypatch.setenv("OWNER_PASSWORD", "owner-secret")
    monkeypatch.setenv("LUMINA_E2E_EMAIL", "e2e@lumina.test")
    monkeypatch.setenv("LUMINA_E2E_PASSWORD", "e2e-secret")
    monkeypatch.delenv("OWNER_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("LUMINA_E2E_PASSWORD_HASH", raising=False)

    assert verify_credentials("e2e@lumina.test", "e2e-secret")
    assert verify_credentials("owner@example.com", "owner-secret")
    assert not verify_credentials("e2e@lumina.test", "wrong")


def test_e2e_account_case_insensitive_email(monkeypatch):
    password_hash = bcrypt.hashpw(b"e2e-secret", bcrypt.gensalt()).decode()
    monkeypatch.setenv("LUMINA_E2E_EMAIL", "E2E@Lumina.Test")
    monkeypatch.setenv("LUMINA_E2E_PASSWORD_HASH", password_hash)

    assert verify_credentials("e2e@lumina.test", "e2e-secret")
    assert verify_credentials("E2E@LUMINA.TEST", "e2e-secret")
    assert verify_credentials(" E2E@lumina.test ", "e2e-secret")


def test_e2e_account_missing_env_vars(monkeypatch):
    # Only owner configured
    monkeypatch.setenv("OWNER_EMAIL", "owner@example.com")
    monkeypatch.setenv("OWNER_PASSWORD", "owner-secret")
    monkeypatch.delenv("LUMINA_E2E_EMAIL", raising=False)
    monkeypatch.delenv("LUMINA_E2E_PASSWORD", raising=False)
    monkeypatch.delenv("LUMINA_E2E_PASSWORD_HASH", raising=False)

    assert verify_credentials("owner@example.com", "owner-secret")
    assert not verify_credentials("e2e@lumina.test", "anything")


def test_allowed_emails_includes_both(monkeypatch):
    monkeypatch.setenv("OWNER_EMAIL", "owner@example.com")
    monkeypatch.setenv("LUMINA_E2E_EMAIL", "e2e@lumina.test")

    allowed = _allowed_emails()
    assert "owner@example.com" in allowed
    assert "e2e@lumina.test" in allowed
    assert len(allowed) == 2


def test_allowed_emails_only_owner(monkeypatch):
    monkeypatch.setenv("OWNER_EMAIL", "owner@example.com")
    monkeypatch.delenv("LUMINA_E2E_EMAIL", raising=False)

    allowed = _allowed_emails()
    assert allowed == ["owner@example.com"]


def test_allowed_emails_only_e2e(monkeypatch):
    monkeypatch.delenv("OWNER_EMAIL", raising=False)
    monkeypatch.setenv("LUMINA_E2E_EMAIL", "e2e@lumina.test")

    allowed = _allowed_emails()
    assert allowed == ["e2e@lumina.test"]


def test_is_e2e_email_detection(monkeypatch):
    monkeypatch.setenv("LUMINA_E2E_EMAIL", "e2e@lumina.test")
    assert _is_e2e_email("e2e@lumina.test")
    assert _is_e2e_email("E2E@LUMINA.TEST")
    assert not _is_e2e_email("owner@example.com")
    assert not _is_e2e_email("other@test.com")


def test_is_owner_email_detection(monkeypatch):
    monkeypatch.setenv("OWNER_EMAIL", "owner@example.com")
    assert _is_owner_email("owner@example.com")
    assert _is_owner_email("OWNER@EXAMPLE.COM")
    assert not _is_owner_email("e2e@lumina.test")


def test_limiter_blocks_then_expires_and_success_clears():
    now = [100.0]
    limiter = LoginRateLimiter(
        max_failures=3,
        window_seconds=60,
        block_seconds=30,
        clock=lambda: now[0],
    )

    assert limiter.record_failure("client") == 0
    assert limiter.record_failure("client") == 0
    assert limiter.record_failure("client") == 30
    assert limiter.retry_after("client") == 30

    now[0] += 31
    assert limiter.retry_after("client") == 0
    limiter.record_failure("client")
    limiter.record_success("client")
    assert limiter.retry_after("client") == 0


def test_limiter_is_scoped_per_client():
    limiter = LoginRateLimiter(max_failures=1)

    limiter.record_failure("client-a")
    assert limiter.retry_after("client-a") > 0
    assert limiter.retry_after("client-b") == 0
