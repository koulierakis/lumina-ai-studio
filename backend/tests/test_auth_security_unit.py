from __future__ import annotations

import bcrypt
from dotenv import dotenv_values
from pathlib import Path
import pytest

from auth import verify_credentials
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
