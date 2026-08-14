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


def _local_passwordless_enabled() -> bool:
    value = os.environ.get("LUMINA_LOCAL_PASSWORDLESS", "1")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _tailscale_passwordless_enabled() -> bool:
    value = os.environ.get("LUMINA_TAILSCALE_PASSWORDLESS", "1")
    return value.strip().lower() in {"1", "true", "yes", "on"}


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


def _client_ip(request: Request) -> ipaddress._BaseAddress | None:
    client = request.client
    host = (client.host if client else "").strip()
    if not host:
        return None
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _is_loopback_request(request: Request) -> bool:
    address = _client_ip(request)
    if address is not None:
        return address.is_loopback

    client = request.client
    host = (client.host if client else "").strip().lower()
    return host == "localhost"


def _is_tailscale_request(request: Request) -> bool:
    """Return True only for source addresses from Tailscale address space.

    Tailscale peers use 100.64.0.0/10 for IPv4 and fd7a:115c:a1e0::/48
    for IPv6. This keeps passwordless remote access confined to the private
    tailnet instead of opening the owner API to arbitrary LAN/Internet clients.
    """
    address = _client_ip(request)
    if address is None:
        return False

    if isinstance(address, ipaddress.IPv4Address):
        return address in ipaddress.ip_network("100.64.0.0/10")

    return address in ipaddress.ip_network("fd7a:115c:a1e0::/48")


async def require_owner(request: Request) -> str:
    """Authenticate the owner for local desktop and trusted Tailscale access.

    Desktop installations default to passwordless access for requests originating
    from the same computer. Trusted Tailscale peers are also allowed by default so
    the owner's phone/laptop can use the same private LUMINA instance remotely.

    Set ``LUMINA_LOCAL_PASSWORDLESS=0`` and/or
    ``LUMINA_TAILSCALE_PASSWORDLESS=0`` to require a valid JWT for those paths.

    If an Authorization header is supplied it is always validated. A malformed,
    forged, expired, or wrong-owner token is never converted into passwordless
    access by either trusted-network fallback.
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

    if _local_passwordless_enabled() and _is_loopback_request(request):
        return owner_email

    if _tailscale_passwordless_enabled() and _is_tailscale_request(request):
        return owner_email

    raise HTTPException(status_code=401, detail="Authentication required")
