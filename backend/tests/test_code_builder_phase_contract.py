from __future__ import annotations

from pathlib import Path


def test_phase_contract_migration_contains_complete_runtime_state_machine() -> None:
    root = Path(__file__).resolve().parents[2]
    migration = root / "tools" / "apply_code_builder_phase_contract.py"
    source = migration.read_text(encoding="utf-8")

    expected_phases = (
        'PLANNING = "planning"',
        'VALIDATING = "validating"',
        'APPLYING = "applying"',
        'VERIFYING = "verifying"',
    )
    for phase in expected_phases:
        assert phase in source

    assert "pre-approval write boundary guard" in source
    assert "cancellation phase guard" in source
    assert "active task deletion guard" in source
    assert "AI review approval gate" in source
    assert "ai_review_blocked" in source


def test_phase_contract_migration_preserves_legacy_execution_compatibility() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "tools" / "apply_code_builder_phase_contract.py").read_text(encoding="utf-8")
    assert 'EXECUTING = "executing"' in source
    assert "Backward-compatible aggregate retained for stored/legacy clients" in source
