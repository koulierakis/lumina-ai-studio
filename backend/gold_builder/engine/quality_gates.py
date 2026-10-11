"""Configurable quality gates.

A job is only COMPLETED when every ENABLED gate has status == PASS AND
browser verification and runtime startup passed. Generated files alone can NEVER mean success.

Explicit states:
  PASS
  FAIL
  NOT_APPLICABLE
  NOT_CONFIGURED
"""
from __future__ import annotations

from typing import Any, List, Optional

from ..models import BuildEvidence, GateReport, GateStatus, QualityGates, VerificationResult


def default_gates(stack) -> QualityGates:
    """Return the default gate config appropriate to a stack."""
    return QualityGates(
        install=bool(stack.install_pipeline),
        build=bool(stack.build_pipeline),
        typecheck=bool(stack.typecheck_pipeline),
        test=bool(stack.test_pipeline),
        lint=bool(stack.lint_pipeline),
        startup=True,
        verify=True,
        workflows=True,
    )


def _pipeline_status(results, pipeline_configured: bool, enabled: bool) -> str:
    if not enabled:
        return GateStatus.NOT_CONFIGURED.value
    if not pipeline_configured:
        return GateStatus.NOT_APPLICABLE.value
    if not results:
        return GateStatus.FAIL.value
    last = results[-1]
    return GateStatus.PASS.value if last.rc == 0 else GateStatus.FAIL.value


def _failure_signature(text: str) -> tuple[str, ...]:
    import re
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    diagnostics = []
    for line in lines:
        clean = re.sub(r"\x1b\[[0-9;]*m", "", line)
        if re.search(r"\berror\b|\bfail(?:ed|ure)?\b|TS\d+:", clean, re.I):
            diagnostics.append(re.sub(r"\s+", " ", clean))
    if diagnostics:
        return tuple(diagnostics)
    return tuple(re.sub(r"\s+", " ", line) for line in lines)


def _baseline_matches(results, baseline_results, gate_name: str | None = None) -> bool:
    if not results or not baseline_results:
        return False
    current = results[-1]
    baseline = baseline_results[-1]
    if current.rc == 0 or baseline.rc == 0:
        return False
    current_sig = _failure_signature(current.output_tail)
    baseline_sig = _failure_signature(baseline.output_tail)
    return bool(current_sig) and current_sig == baseline_sig


def evaluate(
    ev: Optional[BuildEvidence],
    verification: Optional[VerificationResult],
    gates: QualityGates,
    stack: Optional[Any] = None,
    startup_ok: Optional[bool] = None,
    baseline_ev: Optional[BuildEvidence] = None,
) -> List[GateReport]:
    """Return a report per gate, respecting explicit states and blocking behavior."""
    reports: List[GateReport] = []
    ev = ev or BuildEvidence()

    def _add_pipeline_gate(name: str, enabled: bool, results, pipeline_configured: bool):
        status = _pipeline_status(results, pipeline_configured, enabled)
        baseline_results = getattr(baseline_ev, name, []) if baseline_ev else []
        baseline_match = status == GateStatus.FAIL.value and _baseline_matches(results, baseline_results)
        if baseline_match:
            status = GateStatus.PASS.value
        blocking = enabled and status == GateStatus.FAIL.value
        detail = (results[-1].output_tail[-2000:] if results else None)
        if baseline_match:
            detail = "Pre-existing pipeline failure unchanged from baseline; no regression introduced."
        reports.append(GateReport(
            name=name,
            enabled=enabled,
            status=status,
            blocking=blocking,
            detail=detail,
        ))

    has_install = bool(getattr(stack, 'install_pipeline', None)) or bool(ev.install)
    has_build = bool(getattr(stack, 'build_pipeline', None)) or bool(ev.build)
    has_typecheck = bool(getattr(stack, 'typecheck_pipeline', None)) or bool(ev.typecheck)
    has_test = bool(getattr(stack, 'test_pipeline', None)) or bool(ev.test)
    has_lint = bool(getattr(stack, 'lint_pipeline', None)) or bool(ev.lint)

    _add_pipeline_gate("install", gates.install, ev.install, has_install)
    _add_pipeline_gate("build", gates.build, ev.build, has_build)
    _add_pipeline_gate("typecheck", gates.typecheck, ev.typecheck, has_typecheck)
    _add_pipeline_gate("test", gates.test, ev.test, has_test)
    _add_pipeline_gate("lint", gates.lint, ev.lint, has_lint)

    # startup gate
    if not gates.startup:
        s_status = GateStatus.NOT_CONFIGURED.value
    elif startup_ok is None:
        s_status = GateStatus.NOT_APPLICABLE.value
    else:
        s_status = GateStatus.PASS.value if startup_ok else GateStatus.FAIL.value
    reports.append(GateReport(
        name="startup",
        enabled=gates.startup,
        status=s_status,
        blocking=(gates.startup and s_status == GateStatus.FAIL.value),
        detail=None if startup_ok else "Runtime startup failed",
    ))

    # Real browser evidence is mandatory for COMPLETED, even if an older plan
    # disabled the configurable smoke gate. HTTP success is never proof.
    browser_ok = bool(verification and verification.passed
                      and verification.details.get("browser_executed") is True
                      and not verification.console_errors and not verification.network_errors
                      and not verification.page_errors)
    v_status = GateStatus.PASS.value if browser_ok else GateStatus.FAIL.value
    reports.append(GateReport(
        name="verify", enabled=True, status=v_status, blocking=not browser_ok,
        detail=(None if browser_ok else
                (verification.error if verification and verification.error else
                 "Real browser verification evidence is required")),
    ))

    # workflows gate (required scenario interaction workflows)
    if not gates.workflows:
        w_status = GateStatus.NOT_CONFIGURED.value
    elif verification is None:
        w_status = GateStatus.NOT_APPLICABLE.value
    else:
        steps = (verification.details or {}).get("scenario_steps", [])
        if not steps:
            w_status = GateStatus.NOT_APPLICABLE.value
        else:
            failed_steps = [s for s in steps if not s.get("passed", True)]
            w_status = GateStatus.FAIL.value if failed_steps else GateStatus.PASS.value
    reports.append(GateReport(
        name="workflows",
        enabled=gates.workflows,
        status=w_status,
        blocking=(gates.workflows and w_status == GateStatus.FAIL.value),
        detail=("One or more required browser interaction steps failed" if w_status == GateStatus.FAIL.value else None),
    ))

    # Semantic acceptance cannot be disabled when the original request calls
    # for behavioural proof. It is distinct from a generic browser smoke test.
    semantic_required = bool(verification and verification.semantic_required)
    if not semantic_required:
        semantic_status = GateStatus.NOT_APPLICABLE.value
    else:
        semantic_status = (GateStatus.PASS.value if verification.semantic_passed
                           else GateStatus.FAIL.value)
    reports.append(GateReport(
        name="semantic_acceptance", enabled=semantic_required,
        status=semantic_status,
        blocking=semantic_required and semantic_status == GateStatus.FAIL.value,
        detail=(verification.error if semantic_required and not verification.semantic_passed else None),
    ))

    return reports


def all_passed(reports: List[GateReport]) -> bool:
    if not reports:
        return False
    if not any(r.name == "verify" and r.enabled and r.status == GateStatus.PASS.value
               for r in reports):
        return False
    has_executed_pass = False
    for r in reports:
        # Any failing enabled check prevents COMPLETED
        if r.enabled and r.status.upper() == GateStatus.FAIL.value:
            return False
        if r.enabled and r.status.upper() == GateStatus.PASS.value:
            has_executed_pass = True
    # Generated files alone can NEVER mean success
    return has_executed_pass
