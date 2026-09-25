"""Concrete autonomous Code Builder runtime adapters."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .applier import AtomicChangeApplier, ProposedFileChange
from .autonomous import AttemptResult, FailureEvidence, RepairInstruction
from .backup import BackupService
from .generator import ChangeGenerator
from .models import ChangePlan, PlannedChange, TaskRequest
from .repository import Repository
from .validation import ValidationError, ValidationRunner
from .executor import CommandExecutor


class JsonCodeClient(Protocol):
    def generate_json(
        self, prompt: str, model: str | None = None
    ) -> dict[str, Any]: ...


@dataclass(slots=True)
class EvidenceDiagnoser:
    """Turn structured runtime evidence into one bounded repair instruction."""

    client: JsonCodeClient
    model: str | None = None

    def diagnose(
        self,
        *,
        original_instruction: str,
        attempt: int,
        evidence: FailureEvidence,
    ) -> RepairInstruction:
        prompt = f"""You diagnose a failed autonomous coding attempt.
Return ONLY JSON matching:
{{"instruction":"specific repair instruction","relevant_paths":["path"]}}
Target only the observed failure.
Original request: {original_instruction}
Attempt: {attempt}
Summary: {evidence.summary}
Command: {evidence.command or "unknown"}
Stdout: {evidence.stdout[-8000:]}
Stderr: {evidence.stderr[-8000:]}
Console errors: {list(evidence.console_errors)}
Network errors: {list(evidence.network_errors)}
"""
        data = self.client.generate_json(prompt, self.model)
        instruction = str(data.get("instruction", "")).strip()
        raw_paths = data.get("relevant_paths", [])
        paths = (
            tuple(str(path) for path in raw_paths if str(path).strip())
            if isinstance(raw_paths, list)
            else ()
        )
        return RepairInstruction(
            instruction=instruction,
            relevant_paths=paths,
        )


@dataclass(slots=True)
class WorkspaceAttemptRunner:
    """Generate, apply, and validate one attempt inside a disposable workspace."""

    generator: ChangeGenerator
    plan: ChangePlan
    request: TaskRequest
    _changed_paths: set[str] = field(default_factory=set)

    def run_attempt(
        self,
        *,
        workspace_root: Path,
        instruction: str,
        attempt: int,
        previous_evidence: FailureEvidence | None,
    ) -> AttemptResult:
        repository = Repository(workspace_root)
        effective_plan = self._effective_plan(repository)
        context = {
            change.path: repository.read_text(change.path)
            for change in effective_plan.changes
            if repository.exists(change.path) and change.operation in {"modify", "delete"}
        }
        prompt = instruction
        if previous_evidence is not None:
            prompt += (
                "\n\nFailure evidence from the previous attempt:\n"
                f"{previous_evidence.summary}\n"
                f"command={previous_evidence.command or 'unknown'}\n"
                f"stderr={previous_evidence.stderr[-8000:]}"
            )
        request = self.request.model_copy(update={"prompt": prompt})
        proposed = self.generator.generate(request, effective_plan, context)

        backup = BackupService(workspace_root, workspace_root.parent / "attempt-backups")
        applier = AtomicChangeApplier(repository, backup)
        applied = applier.apply(effective_plan, proposed)
        self._changed_paths.update(applied.changed_paths)

        for cache in workspace_root.rglob("__pycache__"):
            if cache.is_dir():
                shutil.rmtree(cache, ignore_errors=True)
        for bytecode in workspace_root.rglob("*.pyc"):
            bytecode.unlink(missing_ok=True)

        validator = ValidationRunner(CommandExecutor(workspace_root))
        try:
            validator.run(
                effective_plan.validation_commands,
                self.request.timeout_seconds,
            )
        except ValidationError as exc:
            result = exc.result
            return AttemptResult(
                successful=False,
                changed_paths=tuple(sorted(self._changed_paths)),
                evidence=FailureEvidence(
                    summary=f"Validation failed with exit code {result.returncode}",
                    command=result.command,
                    stdout=result.stdout[-20_000:],
                    stderr=result.stderr[-20_000:],
                ),
            )
        except subprocess.TimeoutExpired as exc:
            return AttemptResult(
                successful=False,
                changed_paths=tuple(sorted(self._changed_paths)),
                evidence=FailureEvidence(
                    summary="Validation command timed out",
                    command=str(exc.cmd),
                    stdout=_as_text(exc.stdout)[-20_000:],
                    stderr=_as_text(exc.stderr)[-20_000:],
                ),
            )

        return AttemptResult(
            successful=True,
            changed_paths=tuple(sorted(self._changed_paths)),
        )

    def _effective_plan(self, repository: Repository) -> ChangePlan:
        changes: list[PlannedChange] = []
        for change in self.plan.changes:
            exists = repository.exists(change.path)
            operation = change.operation
            if operation == "create" and exists:
                operation = "modify"
            elif operation == "modify" and not exists:
                operation = "create"
            elif operation == "delete" and not exists:
                continue
            changes.append(
                PlannedChange(
                    path=change.path,
                    operation=operation,
                    reason=change.reason,
                )
            )
        return ChangePlan(
            summary=self.plan.summary,
            changes=changes,
            validation_commands=self.plan.validation_commands,
        )


@dataclass(frozen=True, slots=True)
class PublishResult:
    backup_id: str
    changed_paths: tuple[str, ...]


@dataclass(slots=True)
class VerifiedWorkspacePublisher:
    """Atomically publish only verified workspace paths to the source repository."""

    runtime_root: Path
    max_changed_files: int = 100

    def publish(
        self,
        *,
        source_root: Path,
        workspace_root: Path,
        changed_paths: tuple[str, ...],
    ) -> PublishResult:
        unique_paths = tuple(sorted(set(changed_paths)))
        if len(unique_paths) > self.max_changed_files:
            raise ValueError(
                f"Refusing to publish {len(unique_paths)} files; "
                f"limit is {self.max_changed_files}"
            )

        source = Repository(source_root)
        workspace = Repository(workspace_root)
        plan_changes: list[PlannedChange] = []
        proposed: list[ProposedFileChange] = []
        for path in unique_paths:
            source_exists = source.exists(path)
            workspace_exists = workspace.exists(path)
            if workspace_exists:
                operation = "modify" if source_exists else "create"
                content = workspace.read_text(path)
            elif source_exists:
                operation = "delete"
                content = None
            else:
                continue
            plan_changes.append(
                PlannedChange(
                    path=path,
                    operation=operation,
                    reason="Verified autonomous build result",
                )
            )
            proposed.append(
                ProposedFileChange(path=path, operation=operation, content=content)
            )

        if not proposed:
            return PublishResult(backup_id="", changed_paths=())

        plan = ChangePlan(
            summary="Publish verified autonomous build",
            changes=plan_changes,
        )
        backup = BackupService(source_root, self.runtime_root / "backups")
        result = AtomicChangeApplier(source, backup).apply(plan, proposed)
        return PublishResult(
            backup_id=result.backup_id,
            changed_paths=result.changed_paths,
        )


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
