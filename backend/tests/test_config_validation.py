import pytest
from config_validation import (
    ConfigurationError,
    database_dsn,
    is_production,
    validate_auth_config,
    validate_database_config,
)

_PLACEHOLDER = "postgresql://DB_USER:DB_PASSWORD@DB_HOST:5432/postgres"


_CONFIG_ENV = (
    "LUMINA_DATABASE_PROVIDER",
    "DATABASE_URL",
    "POSTGRES_DSN",
    "LUMINA_ENV",
    "OWNER_EMAIL",
    "OWNER_PASSWORD_HASH",
    "OWNER_PASSWORD",
    "JWT_SECRET",
)


@pytest.fixture(autouse=True)
def _preserve_env():
    import os

    # These tests assign directly through ``os.environ`` rather than through
    # monkeypatch, so any variable they set would otherwise survive the test.
    # A leaked ``LUMINA_ENV=production`` flips unrelated storage/health suites
    # into production mode; snapshotting and restoring also protects the
    # auth/DB secrets that conftest sets for other suites from being deleted.
    saved = {name: os.environ.get(name) for name in _CONFIG_ENV}
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def test_defaults_to_sqlite_when_provider_unset():
    assert validate_database_config() == "sqlite"


def test_explicit_sqlite_is_honoured():
    import os

    os.environ["LUMINA_DATABASE_PROVIDER"] = "sqlite"
    assert validate_database_config() == "sqlite"


def test_placeholder_dsn_falls_back_to_sqlite_in_development():
    import os

    os.environ["LUMINA_DATABASE_PROVIDER"] = "postgres"
    os.environ["DATABASE_URL"] = _PLACEHOLDER
    assert not is_production()
    assert validate_database_config() == "sqlite"


def test_placeholder_dsn_raises_in_production():
    import os

    os.environ["LUMINA_ENV"] = "production"
    os.environ["LUMINA_DATABASE_PROVIDER"] = "postgres"
    os.environ["DATABASE_URL"] = _PLACEHOLDER
    with pytest.raises(ConfigurationError):
        validate_database_config()


def test_real_dsn_is_used_as_postgres():
    import os

    os.environ["LUMINA_DATABASE_PROVIDER"] = "postgres"
    os.environ["DATABASE_URL"] = "postgresql://owner:s3cret@db.example.com:5432/lumina"
    assert validate_database_config() == "postgres"
    assert database_dsn().startswith("postgresql://owner")


def test_missing_dsn_raises_in_production():
    import os

    os.environ["LUMINA_ENV"] = "production"
    os.environ["LUMINA_DATABASE_PROVIDER"] = "postgres"
    with pytest.raises(ConfigurationError):
        validate_database_config()


def test_unknown_provider_is_rejected():
    import os

    os.environ["LUMINA_DATABASE_PROVIDER"] = "oracle"
    with pytest.raises(ConfigurationError):
        validate_database_config()


def test_auth_allows_development_defaults_with_warning():
    validate_auth_config()  # must not raise in development


def test_auth_raises_in_production_when_secrets_missing(monkeypatch):

    monkeypatch.setenv("LUMINA_ENV", "production")
    # conftest supplies owner/JWT secrets for the suite; a production auth check
    # must still fail when they are genuinely absent, so clear them explicitly.
    for name in ("OWNER_EMAIL", "OWNER_PASSWORD_HASH", "OWNER_PASSWORD", "JWT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConfigurationError):
        validate_auth_config()


def test_auth_passes_when_configured():
    import os

    os.environ["LUMINA_ENV"] = "production"
    os.environ["OWNER_EMAIL"] = "owner@lumina.local"
    os.environ["OWNER_PASSWORD_HASH"] = "$2b$12$examplehash"
    os.environ["JWT_SECRET"] = "a-real-secret-value"
    validate_auth_config()


def test_persistence_mode_uses_validation(monkeypatch):
    import importlib

    monkeypatch.setenv("LUMINA_DATABASE_PROVIDER", "postgres")
    monkeypatch.setenv("DATABASE_URL", _PLACEHOLDER)
    import persistence

    importlib.reload(persistence)
    assert persistence._database_mode() == "sqlite"
