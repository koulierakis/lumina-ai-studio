import pytest

from code_builder_v2.models import ChangePlan, PlannedChange
from code_builder_v2.transaction import (
    GeneratedChange,
    TransactionValidationError,
    validate_generated_transaction,
)


def multi_file_plan() -> ChangePlan:
    return ChangePlan(
        summary="Modify greeting and settings and add a regression test",
        changes=[
            PlannedChange(path="greeting.py", operation="modify", reason="Update greeting"),
            PlannedChange(path="settings.json", operation="modify", reason="Update settings"),
            PlannedChange(path="test_greeting.py", operation="create", reason="Add test"),
        ],
        validation_commands=["python -m pytest test_greeting.py -q"],
    )


def test_complete_three_file_transaction_is_accepted():
    result = validate_generated_transaction(
        multi_file_plan(),
        [
            GeneratedChange(path="greeting.py", operation="modify"),
            GeneratedChange(path="settings.json", operation="modify"),
            GeneratedChange(path="test_greeting.py", operation="create"),
        ],
    )

    assert result.complete is True
    assert not result.missing_paths
    assert not result.unexpected_paths


def test_one_file_patch_for_three_file_plan_is_rejected():
    with pytest.raises(TransactionValidationError, match="missing planned files") as exc:
        validate_generated_transaction(
            multi_file_plan(),
            [GeneratedChange(path="settings.json", operation="modify")],
        )

    message = str(exc.value)
    assert "greeting.py" in message
    assert "test_greeting.py" in message


def test_unplanned_file_is_rejected():
    with pytest.raises(TransactionValidationError, match="unplanned files"):
        validate_generated_transaction(
            multi_file_plan(),
            [
                GeneratedChange(path="greeting.py", operation="modify"),
                GeneratedChange(path="settings.json", operation="modify"),
                GeneratedChange(path="test_greeting.py", operation="create"),
                GeneratedChange(path="surprise.py", operation="create"),
            ],
        )


def test_wrong_operation_is_rejected():
    with pytest.raises(TransactionValidationError, match="operation mismatch"):
        validate_generated_transaction(
            ChangePlan(
                summary="Delete obsolete file",
                changes=[
                    PlannedChange(path="obsolete.py", operation="delete", reason="Remove obsolete code")
                ],
            ),
            [GeneratedChange(path="obsolete.py", operation="modify")],
        )


def test_path_aliases_are_normalised_before_comparison():
    result = validate_generated_transaction(
        ChangePlan(
            summary="Update file",
            changes=[PlannedChange(path="src/app.py", operation="modify", reason="Change app")],
        ),
        [GeneratedChange(path="src/app.py", operation="update")],
    )

    assert result.complete is True
