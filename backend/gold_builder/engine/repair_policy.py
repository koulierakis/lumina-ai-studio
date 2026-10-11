"""Deterministic repair acceptance, rollback comparison, and syntax checks."""
from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from ..models import GateReport, VerificationResult

_FAIL = {"FAIL", "FAILED"}
_JS_SUFFIXES = {".js", ".mjs", ".cjs"}


def _status(gate: GateReport) -> str:
    return (gate.status or "").upper()


def blocking_failures(gates: Optional[Sequence[GateReport]]) -> List[str]:
    return [g.name for g in (gates or []) if _status(g) in _FAIL and g.blocking]


def repair_improved(
    gates_before: Optional[Sequence[GateReport]],
    gates_after: Optional[Sequence[GateReport]],
    result_before: Optional[VerificationResult] = None,
    result_after: Optional[VerificationResult] = None,
) -> Tuple[bool, str]:
    """Accept only when a blocking failure is reduced without new blocking failures."""
    before = blocking_failures(gates_before)
    after = blocking_failures(gates_after)
    before_set = set(before)
    after_set = set(after)
    regressions = sorted(after_set - before_set)
    if regressions:
        return False, f"new blocking failures: {regressions}"
    recovered = sorted(before_set - after_set)
    if recovered:
        return True, f"blocking gates now passing: {recovered}"
    if len(after) < len(before):
        return True, f"blocking failures decreased ({len(before)} -> {len(after)})"
    if result_before and not result_before.passed and result_after and result_after.passed:
        return True, "verification now passing"
    return False, "no measurable gate improvement"


def validate_source_syntax(path: str, content: str) -> Optional[str]:
    """Return an error string if the source cannot be parsed. Unknown types are skipped."""
    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        try:
            ast.parse(content)
        except SyntaxError as exc:
            return f"{path}: {exc.msg} (line {exc.lineno})"
        return None
    if suffix == ".json":
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            return f"{path}: {exc.msg} (line {exc.lineno})"
        return None
    if suffix in _JS_SUFFIXES:
        node = shutil.which("node")
        if not node:
            return None
        try:
            proc = subprocess.run(
                [node, "--check", "-"],
                input=content,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "invalid JavaScript").strip()
            return f"{path}: {err[:500]}"
    return None


def validate_modified_sources(project: Path, paths: Iterable[str]) -> Optional[str]:
    for rel in paths:
        target = project / rel
        if not target.is_file():
            continue
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        err = validate_source_syntax(rel, content)
        if err:
            return err
    return None
