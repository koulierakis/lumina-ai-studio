from __future__ import annotations

import asyncio

from server import health


def test_backend_health_check_contract(monkeypatch):
    async def fake_statuses():
        return {'mock': {'status': 'ok'}}

    async def fake_health_summary():
        return {'healthy': True}

    monkeypatch.setattr('server.provider_manager.statuses', fake_statuses)
    monkeypatch.setattr(
        'server.provider_manager.health_summary',
        fake_health_summary,
    )
    monkeypatch.setattr('server.available_providers', lambda: ['mock'])
    monkeypatch.setattr('server.now_iso', lambda: '2026-01-01T00:00:00Z')

    payload = asyncio.run(health())

    assert payload['status'] == 'ok'
    assert payload['backend'] == 'ok'
    assert payload['database']['provider'] in {'sqlite', 'mongo'}
    assert 'ready' in payload['database']
    assert 'fallback_active' in payload['database']
    assert 'mongo_configured' in payload['database']
    assert 'mongo_available' in payload['database']
    assert payload['providers_available'] == ['mock']
