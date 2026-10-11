"""Startup configuration validation.

Distinguishes safe development defaults from mandatory production settings.
Development may fall back to local SQLite when a cloud database is only
half-configured; production must fail fast instead of silently degrading.

Placeholders shipped in ``.env.example`` (``DB_HOST``, ``DB_USER``,
``DB_PASSWORD``, ``YOUR_`` prefixes) are never treated as real values.
"""
from __future__ import annotations

import os

_PLACEHOLDER_TOKENS = ("db_host", "db_user", "db_password", "db_name", "db_port", "your_", "changeme")


class ConfigurationError(RuntimeError):
    """Raised when mandatory production configuration is missing or invalid."""


def is_production() -> bool:
    return os.environ.get("LUMINA_ENV", "development").strip().lower() in {"production", "prod"}


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    return any(token in lowered for token in _PLACEHOLDER_TOKENS)


def database_dsn() -> str:
    return (os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_DSN") or "").strip()


def validate_database_config() -> str:
    """Return the effective database mode, applying a safe development fallback.

    Raises :class:`ConfigurationError` in production when PostgreSQL is selected
    but no real DSN is configured, so deployment never silently writes to a
    throwaway SQLite file.
    """
    mode = os.environ.get("LUMINA_DATABASE_PROVIDER", "").strip().lower()
    dsn = database_dsn()

    if mode in {"postgres", "postgresql"}:
        if not dsn:
            return _missing_postgres("DATABASE_URL / POSTGRES_DSN is empty")
        if _looks_like_placeholder(dsn):
            return _missing_postgres("DATABASE_URL still contains the .env.example placeholder host")
        return "postgres"

    if mode in {"mongo", "sqlite", "auto", ""}:
        return mode or "sqlite"

    raise ConfigurationError(
        f"Unknown LUMINA_DATABASE_PROVIDER={mode!r}. Use one of: sqlite, mongo, postgres, auto."
    )


def _missing_postgres(reason: str) -> str:
    if is_production():
        raise ConfigurationError(
            f"PostgreSQL persistence is selected but not configured ({reason}). "
            "Set a real DATABASE_URL (or POSTGRES_DSN) before starting in production. "
            "Indices must never fall back to local SQLite."
        )
    import logging

    logging.getLogger("lumina").warning(
        "PostgreSQL selected but not configured (%s); falling back to local SQLite for development. "
        "Set a real DATABASE_URL to use PostgreSQL.",
        reason,
    )
    return "sqlite"


def validate_auth_config() -> None:
    """Fail fast in production when owner/JWT secrets are absent."""
    problems: list[str] = []
    if not os.environ.get("OWNER_EMAIL", "").strip():
        problems.append("OWNER_EMAIL")
    if not (os.environ.get("OWNER_PASSWORD_HASH") or os.environ.get("OWNER_PASSWORD")):
        problems.append("OWNER_PASSWORD_HASH")
    if not os.environ.get("JWT_SECRET", "").strip():
        problems.append("JWT_SECRET")
    if not problems:
        return
    message = "Missing mandatory authentication configuration: " + ", ".join(problems)
    if is_production():
        raise ConfigurationError(message + ". These are required in production.")
    import logging

    logging.getLogger("lumina").warning("%s. Login will fail until they are set.", message)
