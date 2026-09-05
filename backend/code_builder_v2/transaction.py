from __future__ import annotations

from dataclasses import dataclass

from .models import ChangePlan
from .security import normalize_relative_path


class TransactionValidationError(ValueError):
    """Raised when generated changes do not faithfully implement the approved plan."""


@dataclass(frozen=True, slots=True)
class GeneratedChange:
    path: str
    operation: str


@dataclass(frozen=True, slots=True)
class TransactionValidationResult:
    required_paths: frozenset[str]
    generated_paths: frozenset[str]

    @property
    def missing_paths(self) -> frozenset[str]:
        return self.required_paths - self.generated_paths

    @property
    def unexpected_paths(self) -> frozenset[str]:
        return self.generated_paths - self.required_paths

    @property
    def complete(self) -> bool:
        return not self.missing_paths and not self.unexpected_paths


def _normalise_operation(operation: str) -> str:
    value = operation.strip().lower()
    aliases = {"update": "modify", "remove": "delete"}
    return aliases.get(value, value)


def validate_generated_transaction(
    plan: ChangePlan,
    generated_changes: list[GeneratedChange],
) -> TransactionValidationResult:
    """Require a one-to-one path/operation match between approved plan and generated work.

    This validator intentionally checks both directions:
    - every planned file must be generated;
    - no unplanned file may be generated;
    - the operation for each path must match the approved operation.
    """
    planned_by_path: dict[str, str] = {}
    for item in plan.changes:
        path = normalize_relative_path(item.path)
        operation = _normalise_operation(item.operation)
        previous = planned_by_path.get(path)
        if previous is not None and previous != operation:
            raise TransactionValidationError(
                f"Plan contains conflicting operations for {path}: {previous} vs {operation}"
            )
        planned_by_path[path] = operation

    generated_by_path: dict[str, str] = {}
    for item in generated_changes:
        path = normalize_relative_path(item.path)
        operation = _normalise_operation(item.operation)
        previous = generated_by_path.get(path)
        if previous is not None and previous != operation:
            raise TransactionValidationError(
                f"Generated transaction contains conflicting operations for {path}: "
                f"{previous} vs {operation}"
            )
        generated_by_path[path] = operation

    result = TransactionValidationResult(
        required_paths=frozenset(planned_by_path),
        generated_paths=frozenset(generated_by_path),
    )

    problems: list[str] = []
    if result.missing_paths:
        problems.append("missing planned files: " + ", ".join(sorted(result.missing_paths)))
    if result.unexpected_paths:
        problems.append("unplanned files: " + ", ".join(sorted(result.unexpected_paths)))

    for path in sorted(result.required_paths & result.generated_paths):
        planned_operation = planned_by_path[path]
        generated_operation = generated_by_path[path]
        if planned_operation != generated_operation:
            problems.append(
                f"operation mismatch for {path}: planned={planned_operation}, "
                f"generated={generated_operation}"
            )

    if problems:
        raise TransactionValidationError("; ".join(problems))

    return result
