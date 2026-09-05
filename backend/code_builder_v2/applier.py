from __future__ import annotations

from dataclasses import dataclass

from .backup import BackupService
from .models import ChangePlan
from .repository import Repository
from .transaction import GeneratedChange, validate_generated_transaction


class ApplyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProposedFileChange:
    path: str
    operation: str
    content: str | None = None

    def as_generated_change(self) -> GeneratedChange:
        return GeneratedChange(path=self.path, operation=self.operation)


@dataclass(frozen=True, slots=True)
class ApplyResult:
    backup_id: str
    changed_paths: tuple[str, ...]


@dataclass(slots=True)
class AtomicChangeApplier:
    repository: Repository
    backup_service: BackupService

    def apply(self, plan: ChangePlan, changes: list[ProposedFileChange]) -> ApplyResult:
        validate_generated_transaction(
            plan,
            [change.as_generated_change() for change in changes],
        )
        self._validate_preconditions(changes)

        paths = [change.path for change in changes]
        backup = self.backup_service.create(paths)

        try:
            for change in changes:
                operation = self._normalise_operation(change.operation)
                if operation in {"create", "modify"}:
                    if change.content is None:
                        raise ApplyError(f"Missing content for {operation}: {change.path}")
                    self.repository.write_text(change.path, change.content)
                elif operation == "delete":
                    self.repository.delete(change.path)
                else:
                    raise ApplyError(f"Unsupported operation: {change.operation}")
        except Exception as exc:
            try:
                self.backup_service.restore(backup.id)
            except Exception as rollback_exc:
                raise ApplyError(
                    f"Apply failed and rollback also failed: apply={exc}; rollback={rollback_exc}"
                ) from rollback_exc
            raise ApplyError(f"Apply failed; repository restored: {exc}") from exc

        return ApplyResult(backup_id=backup.id, changed_paths=tuple(paths))

    def rollback(self, backup_id: str) -> None:
        self.backup_service.restore(backup_id)

    def _validate_preconditions(self, changes: list[ProposedFileChange]) -> None:
        for change in changes:
            operation = self._normalise_operation(change.operation)
            exists = self.repository.exists(change.path)
            if operation == "create" and exists:
                raise ApplyError(f"Create target already exists: {change.path}")
            if operation in {"modify", "delete"} and not exists:
                raise ApplyError(f"{operation.title()} target does not exist: {change.path}")
            if operation in {"create", "modify"} and change.content is None:
                raise ApplyError(f"Missing content for {operation}: {change.path}")

    @staticmethod
    def _normalise_operation(operation: str) -> str:
        value = operation.strip().lower()
        return {"update": "modify", "remove": "delete"}.get(value, value)
