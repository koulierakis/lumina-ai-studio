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
from urllib.parse import urlparse

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


def _parse_ip(value: str) -> ipaddress._BaseAddress | None:
    try:
        return ipaddress.ip_address(value.strip())
    except (ValueError, AttributeError):
        return None


def _client_ip(request: Request) -> ipaddress._BaseAddress | None:
    client = request.client
    host = (client.host if client else "").strip()
    return _parse_ip(host) if host else None


def _is_loopback_request(request: Request) -> bool:
    address = _client_ip(request)
    if address is not None:
        return address.is_loopback

    client = request.client
    host = (client.host if client else "").strip().lower()
    return host == "localhost"


def _is_tailscale_ip(address: ipaddress._BaseAddress | None) -> bool:
    if address is None:
        return False
    if isinstance(address, ipaddress.IPv4Address):
        return address in ipaddress.ip_network("100.64.0.0/10")
    return address in ipaddress.ip_network("fd7a:115c:a1e0::/48")


def _is_tailscale_request(request: Request) -> bool:
    return _is_tailscale_ip(_client_ip(request))


def _is_tailscale_browser_origin(request: Request) -> bool:
    """Recognize the owner SPA when it is opened over a Tailscale address.

    On Windows, Tailscale traffic can be delivered to Uvicorn through a local
    networking layer that does not always preserve the peer's 100.64/10 address
    in ``request.client``. The browser Origin/Referer still identifies the private
    tailnet URL. We only accept an HTTP(S) browser origin whose host itself is a
    Tailscale address, keeping this fallback scoped to tailnet-hosted Lumina UI.
    """
    raw_origin = (request.headers.get("origin") or "").strip()
    raw_referer = (request.headers.get("referer") or "").strip()
    candidate = raw_origin or raw_referer
    if not candidate:
        return False

    try:
        parsed = urlparse(candidate)
    except ValueError:
        return False

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False

    return _is_tailscale_ip(_parse_ip(parsed.hostname))


async def require_owner(request: Request) -> str:
    """Authenticate the owner for local desktop and trusted Tailscale access."""
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

    if _tailscale_passwordless_enabled() and (
        _is_tailscale_request(request) or _is_tailscale_browser_origin(request)
    ):
        return owner_email

    raise HTTPException(status_code=401, detail="Authentication required")
