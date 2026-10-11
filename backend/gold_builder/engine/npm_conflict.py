"""Deterministic npm ERESOLVE peer-dependency conflict parser."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import List, Optional

_PREFIX_RE = re.compile(r"^\s*npm\s+(?:error|ERR!|warn|WARN)\s?", re.IGNORECASE)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_PKG = r"@?[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)?"
_VER = r"[0-9][A-Za-z0-9._+-]*"
_PEER_RE = re.compile(
    rf'peer\s+(?P<peer>{_PKG})@"(?P<range>[^"]+)"\s+from\s+'
    rf"(?P<pkg>{_PKG})@(?P<ver>{_VER})",
)
_FOUND_RE = re.compile(rf"Found:\s+(?P<pkg>{_PKG})@(?P<ver>{_VER})")
_RESOLVING_RE = re.compile(rf"While resolving:\s+(?P<pkg>{_PKG})@(?P<ver>\S+)")

REPAIR_GUIDANCE = (
    "Resolve this by editing the declared versions in package.json so the peer "
    "constraint is satisfied: upgrade the package imposing the obsolete peer "
    "range, or downgrade/select a mutually compatible declared version. Do NOT "
    "add --force or --legacy-peer-deps and do NOT suppress the ERESOLVE error."
)


@dataclass
class PeerConflict:
    conflicting_package: Optional[str] = None
    conflicting_version: Optional[str] = None
    peer_package: Optional[str] = None
    required_range: Optional[str] = None
    found_version: Optional[str] = None
    dependent_package: Optional[str] = None

    def is_actionable(self) -> bool:
        return bool(self.peer_package and self.required_range)


def _clean_lines(text: str) -> List[str]:
    lines = []
    for raw in (text or "").splitlines():
        line = _ANSI_RE.sub("", raw)
        line = _PREFIX_RE.sub("", line)
        lines.append(line.strip())
    return lines


def is_eresolve(text: str) -> bool:
    cleaned = "\n".join(_clean_lines(text)).lower()
    return "eresolve" in cleaned and ("peer" in cleaned or "could not resolve" in cleaned)


def parse_eresolve(text: str) -> List[PeerConflict]:
    lines = _clean_lines(text)
    joined = "\n".join(lines)
    dependent: Optional[str] = None
    m = _RESOLVING_RE.search(joined)
    if m:
        dependent = m.group("pkg")
    found_versions: dict[str, str] = {}
    for line in lines:
        fm = _FOUND_RE.search(line)
        if fm:
            found_versions[fm.group("pkg")] = fm.group("ver")
    conflicts: List[PeerConflict] = []
    for line in lines:
        pm = _PEER_RE.search(line)
        if pm:
            peer_pkg = pm.group("peer")
            conflicts.append(PeerConflict(
                conflicting_package=pm.group("pkg"),
                conflicting_version=pm.group("ver"),
                peer_package=peer_pkg,
                required_range=pm.group("range"),
                found_version=found_versions.get(peer_pkg),
                dependent_package=dependent,
            ))
    return conflicts


def format_conflicts(conflicts: List[PeerConflict]) -> str:
    if not conflicts:
        return ""
    out: List[str] = [
        "npm reported an ERESOLVE peer-dependency conflict. "
        "Actual package constraints (authoritative — edit package.json to satisfy these):",
    ]
    for i, c in enumerate(conflicts, 1):
        out.append(f"- Conflict {i}:")
        if c.conflicting_package:
            ver = f"@{c.conflicting_version}" if c.conflicting_version else ""
            out.append(f"    conflicting_package: {c.conflicting_package}{ver}")
        if c.peer_package:
            rng = f'@"{c.required_range}"' if c.required_range else ""
            out.append(f"    requires_peer: {c.peer_package}{rng}")
        if c.found_version:
            peer = c.peer_package or "peer"
            out.append(f"    found_installed: {peer}@{c.found_version}")
        if c.dependent_package:
            out.append(f"    dependent: {c.dependent_package}")
    out.append(REPAIR_GUIDANCE)
    return "\n".join(out)


def _range_candidates(required_range: str) -> List[str]:
    """Return only candidates that are provably inside simple npm ranges.

    Be deliberately conservative: upper bounds, comparator sets, wildcards,
    workspace/file protocols and other compound syntax fall through to the
    normal diagnosis path rather than risking a wrong deterministic edit.
    """
    candidates: List[str] = []
    for alternative in (required_range or "").split("||"):
        part = alternative.strip()
        m = re.fullmatch(r"\^(\d+)(?:\.(\d+))?(?:\.(\d+))?", part)
        if m:
            major, minor, patch = m.groups()
            candidates.append(f"^{major}.{minor or '0'}.{patch or '0'}")
            continue
        m = re.fullmatch(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", part)
        if m:
            major, minor, patch = m.groups()
            candidates.append(f"{major}.{minor or '0'}.{patch or '0'}")
            continue
        # Unsupported syntax means this constraint is not safe for the
        # deterministic path.
        return []
    return candidates


def propose_manifest_peer_repair(manifest: dict, conflicts: List[PeerConflict]) -> tuple[dict, List[str]]:
    repaired = copy.deepcopy(manifest)
    changes: List[str] = []
    grouped: dict[str, List[PeerConflict]] = {}
    for conflict in conflicts:
        if conflict.is_actionable() and conflict.peer_package:
            grouped.setdefault(conflict.peer_package, []).append(conflict)

    for peer_package, peer_conflicts in grouped.items():
        candidate_sets = [
            set(_range_candidates(c.required_range or ""))
            for c in peer_conflicts
        ]
        if not candidate_sets or any(not s for s in candidate_sets):
            continue
        common = set.intersection(*candidate_sets)
        if not common:
            # Multiple reported constraints disagree. Let the normal repair
            # path reason about upgrading the package imposing the old peer.
            continue
        candidate = sorted(common)[0]
        for section in ("dependencies", "devDependencies", "optionalDependencies"):
            deps = repaired.get(section)
            if not isinstance(deps, dict) or peer_package not in deps:
                continue
            old = str(deps[peer_package])
            if old == candidate:
                break
            deps[peer_package] = candidate
            changes.append(f"{section}.{peer_package}: {old} -> {candidate}")
            break
    return repaired, changes
