from __future__ import annotations

import pytest
from code_builder.router import _validate_review_allows_approval
from fastapi import HTTPException


def test_completed_pass_review_allows_approval() -> None:
    _validate_review_allows_approval(
        {"status": "completed", "verdict": "pass"},
        task_id="review-pass",
    )


def test_completed_warn_review_allows_approval() -> None:
    _validate_review_allows_approval(
        {"status": "completed", "verdict": "warn"},
        task_id="review-warn",
    )


def test_block_review_prevents_approval() -> None:
    with pytest.raises(HTTPException) as captured:
        _validate_review_allows_approval(
            {"status": "completed", "verdict": "block"},
            task_id="review-block",
        )
    assert captured.value.status_code == 409
    assert captured.value.detail["error"] == "ai_review_blocked"


def test_unavailable_review_prevents_approval() -> None:
    with pytest.raises(HTTPException) as captured:
        _validate_review_allows_approval(
            {"status": "unavailable"},
            task_id="review-unavailable",
        )
    assert captured.value.status_code == 409
    assert captured.value.detail["error"] == "ai_review_unavailable"
