"""Diagnose + repair loop.

Given a VerificationResult with failures, pick the file most likely at fault
(heuristic: JS console error mentions app.js → repair app.js, else index.html)
and ask the LLM to rewrite it. Bounded by max_repair_attempts.
"""
from __future__ import annotations

from typing import Optional

from ..models import GeneratedFile, Plan, VerificationResult
from .generator import repair_file


def pick_target(files: list[GeneratedFile], evidence: str) -> Optional[GeneratedFile]:
    """Best-effort selection of which file to repair based on error text."""
    lower = evidence.lower()

    # explicit mention wins
    for f in files:
        if f.path.lower() in lower:
            return f

    # JS errors point at app.js
    if any(k in lower for k in ("uncaught", "referenceerror", "typeerror", "syntaxerror")):
        for f in files:
            if f.path.endswith(".js"):
                return f

    # 404 on stylesheet → repair index.html link
    if "styles.css" in lower or "stylesheet" in lower:
        for f in files:
            if f.path == "index.html":
                return f

    # Default: index.html
    for f in files:
        if f.path == "index.html":
            return f
    return files[0] if files else None


def build_evidence(result: VerificationResult) -> str:
    parts: list[str] = []
    if result.http_status is not None:
        parts.append(f"HTTP status: {result.http_status}")
    if result.error:
        parts.append(f"Runtime error: {result.error}")
    if result.console_errors:
        parts.append("Console errors:\n" + "\n".join(result.console_errors[:10]))
    if result.network_errors:
        parts.append("Network errors:\n" + "\n".join(result.network_errors[:10]))
    if result.rendered_text_snippet:
        parts.append(f"Rendered text snippet: {result.rendered_text_snippet[:200]}")
    return "\n\n".join(parts) or "Unknown failure — no evidence captured."


async def attempt_repair(
    plan: Plan,
    files: list[GeneratedFile],
    result: VerificationResult,
    preferred_provider: Optional[str] = None,
) -> Optional[GeneratedFile]:
    evidence = build_evidence(result)
    target = pick_target(files, evidence)
    if not target:
        return None
    return await repair_file(plan, target, evidence, preferred_provider=preferred_provider)
