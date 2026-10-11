"""Provider-outage detection for Guardian pause/resume.

Uses the live provider router's cooldown/availability state only. No network
call is made here; the router already tracks configured providers and their
cooldowns. This keeps pause/resume deterministic and cheap.
"""
from __future__ import annotations


def _router():
    from ..providers.router import router
    return router


def llm_providers_available() -> bool:
    """True when at least one configured LLM provider is not cooling down."""
    try:
        r = _router()
    except Exception:
        return False
    try:
        if r.available_llm():
            return True
    except Exception:
        return False
    # Degraded-but-configured providers are still attempted (retry/cooldown is
    # handled by the router). Only treat a hard outage as unavailable: no
    # configured provider at all, or every configured provider is cooling down.
    try:
        configured = [p for p in r.list_llm() if p.available()]
    except Exception:
        return False
    if not configured:
        return False
    try:
        return any(r._cooldown_remaining(p.id) <= 0 for p in configured)  # noqa: SLF001
    except Exception:
        return True


def provider_snapshot() -> dict:
    """Secret-free provider state for Guardian events."""
    try:
        r = _router()
        providers = r.list_llm()
    except Exception:
        return {"configured": 0, "available": 0, "cooling_down": 0}
    configured = 0
    available = 0
    cooling = 0
    for p in providers:
        try:
            if not p.available():
                continue
        except Exception:
            continue
        configured += 1
        try:
            remaining = r._cooldown_remaining(p.id)  # noqa: SLF001
        except Exception:
            remaining = 0
        if remaining > 0:
            cooling += 1
        else:
            available += 1
    return {"configured": configured, "available": available, "cooling_down": cooling}
