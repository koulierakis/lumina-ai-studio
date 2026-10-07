"""Autonomy dial for LUMINA Mind.

Controls how much Mind may do without asking. The dial is deliberately
asymmetric: it can make Mind *stricter* than the default, and it can relax only
a narrow, explicitly reversible set of operations. Outbound side effects
(connectors) and destructive operations are never auto-executed at any level.

Levels (most cautious first):

- ``manual``   — every operation requires approval, even harmless ones.
- ``assisted`` — default: safe operations run; approval operations ask.
- ``auto``     — also runs reversible local operations (code-builder apply,
                 which is backed by an automatic rollback). Everything
                 destructive or outbound still asks.
"""

from __future__ import annotations

import os

LEVELS: tuple[str, ...] = ("manual", "assisted", "auto")
DEFAULT_LEVEL = "assisted"
ENV_VAR = "LUMINA_MIND_AUTONOMY"

# Capabilities whose actions may never auto-execute, at any level.
_NEVER_CAPABILITIES = frozenset({"connect"})

# Approval operations that are local and reversible (the engine keeps a backup
# and exposes an explicit rollback). Only ``auto`` relaxes these.
_REVERSIBLE_LOCAL = frozenset({("code_builder", "execute")})

# Which tiers each level is allowed to run without approval.
_ALLOWED_TIERS: dict[str, frozenset[str]] = {
    "manual": frozenset(),
    "assisted": frozenset(),
    "auto": frozenset({"reversible_local"}),
}

LABELS: dict[str, str] = {
    "manual": "Χειροκίνητο",
    "assisted": "Ημιαυτόματο",
    "auto": "Αυτόματο",
}

DESCRIPTIONS: dict[str, str] = {
    "manual": "Κάθε ενέργεια περνά από την έγκρισή σου.",
    "assisted": "Οι ασφαλείς ενέργειες εκτελούνται· οι υπόλοιπες ζητούν έγκριση.",
    "auto": "Εκτελεί και αναστρέψιμες τοπικές ενέργειες· οι εξωτερικές και οι διαγραφές ζητούν πάντα έγκριση.",
}


def normalise_level(value: str | None) -> str:
    """Return a valid level, falling back to the default for unknown input."""
    candidate = str(value or "").strip().lower()
    return candidate if candidate in LEVELS else DEFAULT_LEVEL


def current_level() -> str:
    """The level configured through the environment, if any."""
    return normalise_level(os.environ.get(ENV_VAR))


def _tier(capability_id: str, action: str) -> str:
    """Classify an approval operation. Unknown operations stay gated."""
    if capability_id in _NEVER_CAPABILITIES:
        return "never"
    if action.startswith("delete") or action.startswith("remove"):
        return "never"
    if (capability_id, action) in _REVERSIBLE_LOCAL:
        return "reversible_local"
    return "never"


def requires_approval(level: str | None, risk: str, capability_id: str, action: str) -> bool:
    """Whether an operation must be approved by the owner before it runs."""
    resolved = normalise_level(level)
    if resolved == "manual":
        return True
    if risk != "approval":
        return False
    return _tier(capability_id, action) not in _ALLOWED_TIERS[resolved]


def describe(level: str | None = None) -> dict:
    """Public description of the dial for the UI and model grounding."""
    resolved = normalise_level(level)
    return {
        "level": resolved,
        "default": DEFAULT_LEVEL,
        "levels": list(LEVELS),
        "labels": dict(LABELS),
        "descriptions": dict(DESCRIPTIONS),
    }
