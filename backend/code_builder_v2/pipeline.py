from __future__ import annotations

from dataclasses import dataclass

from .applier import AtomicChangeApplier
from .generator import ChangeGenerator
from .models import ChangePlan, TaskRequest
from .repository import Repository
from .validation import ValidationError, ValidationRunner


class PipelineError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PipelineResult:
    backup_id: str
    changed_paths: tuple[str, ...]
    validation_commands: tuple[str, ...]


@dataclass(slots=True)
class ExecutionPipeline:
    repository: Repository
    generator: ChangeGenerator
    applier: AtomicChangeApplier
    validation_runner: ValidationRunner

    def execute(self, request: TaskRequest, plan: ChangePlan) -> PipelineResult:
        context: dict[str, str] = {}
        for planned in plan.changes:
            if planned.operation in {"modify", "delete"} and self.repository.exists(planned.path):
                context[planned.path] = self.repository.read_text(planned.path)

        proposed = self.generator.generate(request, plan, context)
        applied = self.applier.apply(plan, proposed)
        try:
            self.validation_runner.run(plan.validation_commands, request.timeout_seconds)
        except ValidationError as exc:
            self.applier.rollback(applied.backup_id)
            raise PipelineError(
                f"Validation failed; repository rolled back: {exc.result.command}"
            ) from exc
        except Exception as exc:
            self.applier.rollback(applied.backup_id)
            raise PipelineError(f"Validation crashed; repository rolled back: {exc}") from exc

        return PipelineResult(
            backup_id=applied.backup_id,
            changed_paths=applied.changed_paths,
            validation_commands=tuple(plan.validation_commands),
        )
