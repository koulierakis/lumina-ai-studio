from __future__ import annotations

import time

import pytest
from fastapi import HTTPException

from code_builder.router import (
    ApprovalDecision,
    CodeBuilderTaskPhase,
    StoredTask,
    TaskApprovalRequest,
    TaskCreateRequest,
    _phase_allows_cancellation,
    _update_phase_from_event,
)
from code_builder.task_service import TaskCancellationToken, TaskRequest


def _stored(*, approved: bool) -> StoredTask:
    request = TaskRequest(instruction="hardening contract")
    api_request = TaskCreateRequest(
        instruction="hardening contract",
        require_approval=True,
        auto_start_after_approval=False,
    )
    return StoredTask(
        request=request,
        api_request=api_request,
        phase=CodeBuilderTaskPhase.QUEUED,
        created_at_epoch=time.time(),
        updated_at_epoch=time.time(),
        require_approval=True,
        auto_start_after_approval=False,
        cancellation_token=TaskCancellationToken(task_id=request.task_id),
        approved_at_epoch=time.time() if approved else None,
    )


def test_phase_enum_exposes_full_runtime_contract() -> None:
    expected = {
        "queued",
        "analyzing",
        "planning",
        "validating",
        "awaiting_approval",
        "approved",
        "applying",
        "verifying",
        "completed",
        "failed",
        "cancelled",
        "timed_out",
        "rolling_back",
        "rolled_back",
        "rollback_failed",
    }
    assert expected.issubset({item.value for item in CodeBuilderTaskPhase})


def test_preapproval_events_never_cross_write_boundary() -> None:
    stored = _stored(approved=False)
    _update_phase_from_event(stored, {"status": "analyzing", "stage": "analysis"})
    assert stored.phase.value == "analyzing"
    _update_phase_from_event(stored, {"status": "planning", "stage": "planning"})
    assert stored.phase.value == "planning"
    _update_phase_from_event(stored, {"status": "validating_patch", "stage": "patch_validation"})
    assert stored.phase.value == "validating"
    _update_phase_from_event(stored, {"status": "applying_patch", "stage": "patch_application"})
    assert stored.phase.value == "validating"


def test_postapproval_events_expose_apply_and_verify_phases() -> None:
    stored = _stored(approved=True)
    stored.phase = CodeBuilderTaskPhase.APPROVED
    _update_phase_from_event(stored, {"status": "backing_up", "stage": "backup"})
    assert stored.phase.value == "applying"
    _update_phase_from_event(stored, {"status": "applying_patch", "stage": "patch_application"})
    assert stored.phase.value == "applying"
    _update_phase_from_event(stored, {"status": "building", "stage": "build"})
    assert stored.phase.value == "verifying"
    _update_phase_from_event(stored, {"status": "succeeded", "stage": "completion"})
    assert stored.phase.value == "completed"


def test_all_nonterminal_work_phases_are_cancellable() -> None:
    for phase in (
        CodeBuilderTaskPhase.QUEUED,
        CodeBuilderTaskPhase.ANALYZING,
        CodeBuilderTaskPhase.PLANNING,
        CodeBuilderTaskPhase.VALIDATING,
        CodeBuilderTaskPhase.AWAITING_APPROVAL,
        CodeBuilderTaskPhase.APPROVED,
        CodeBuilderTaskPhase.APPLYING,
        CodeBuilderTaskPhase.VERIFYING,
    ):
        assert _phase_allows_cancellation(phase)
