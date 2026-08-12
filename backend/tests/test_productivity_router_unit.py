from __future__ import annotations

from datetime import datetime, timezone

import pytest

from productivity_router import _next_run, _validate_public_url


def test_next_run_cadences() -> None:
    current = datetime(2026, 8, 12, 6, 0, tzinfo=timezone.utc)
    assert (_next_run(current, "hourly") - current).total_seconds() == 3600
    assert (_next_run(current, "daily") - current).days == 1
    assert (_next_run(current, "weekly") - current).days == 7
    assert _next_run(current, "once") is None


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/private",
        "http://localhost/private",
        "http://10.0.0.1/private",
        "ftp://example.com/file",
        "http://user:pass@example.com/secret",
        "https://example.com:8443/private",
    ],
)
def test_research_url_validation_rejects_unsafe_targets(url: str) -> None:
    with pytest.raises(ValueError):
        _validate_public_url(url)
