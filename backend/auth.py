"""Single-owner authentication for Lumina AI Desktop.

Uses simple email + bcrypt password verified against env vars.
Issues signed JWT tokens for session persistence.
"""
from __future__ import annotations

import hmac
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import bcrypt
import jwt
from dotenv import load_dotenv

# Authentication is also imported by local maintenance commands and tests.
# Load the backend-owned configuration here so credential verification never
# relies on another module having imported the application first. Existing
# process environment values remain authoritative for deployment overrides.
load_dotenv(Path(__file__).resolve().with_name(".env"), override=False)


def _secret() -> str:
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET not configured")
    return secret


def _owner_email() -> str:
    return (os.environ.get("OWNER_EMAIL") or "").strip().lower()


def _owner_password() -> str:
    return os.environ.get("OWNER_PASSWORD") or ""


def _owner_password_hash() -> str:
    return (os.environ.get("OWNER_PASSWORD_HASH") or "").strip()


def verify_credentials(email: str, password: str) -> bool:
    if not email or not password:
        return False

    if not hmac.compare_digest(email.strip().lower(), _owner_email()):
        return False

    password_hash = _owner_password_hash()
    if password_hash:
        try:
            return bcrypt.checkpw(
                password.encode("utf-8"),
                password_hash.encode("utf-8"),
            )
        except (ValueError, TypeError):
            return False

    # Backward compatibility for existing installations. Production deployments
    # should set OWNER_PASSWORD_HASH and remove OWNER_PASSWORD.
    return hmac.compare_digest(password, _owner_password())


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def issue_token(email: str, hours: int = 24 * 30) -> str:
    payload = {
        "sub": email.strip().lower(),
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(hours=hours),
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, _secret(), algorithms=["HS256"])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


async def require_owner() -> str:
    """Local single-owner mode: allow access without authentication."""
    return _owner_email() or "owner@lumina.local"
