"""Single-owner authentication for Lumina AI Desktop.

Uses simple email + bcrypt password verified against env vars.
Issues signed JWT tokens for session persistence.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import bcrypt
import jwt
from dotenv import load_dotenv
from fastapi import HTTPException, Request

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
        subject = payload.get("sub")
        return str(subject).strip().lower() if subject else None
    except jwt.PyJWTError:
        return None


def _is_loopback_request(request: Request) -> bool:
    client = request.client
    host = (client.host if client else "").strip()
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"


async def require_owner(request: Request) -> str:
    """Authenticate the owner, with passwordless access only on loopback.

    Local desktop requests may omit the Authorization header. If a token is
    supplied, however, it is always validated so malformed, forged, or expired
    credentials can never be converted into passwordless access by the local
    fallback. Non-loopback requests always require a valid owner JWT.
    """
    owner_email = _owner_email() or "owner@lumina.local"
    authorization = (request.headers.get("authorization") or "").strip()

    if authorization:
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(status_code=401, detail="Invalid authorization header")
        subject = decode_token(token.strip())
        if not subject or not hmac.compare_digest(subject, owner_email):
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        return owner_email

    if _is_loopback_request(request):
        return owner_email

    raise HTTPException(status_code=401, detail="Authentication required")
