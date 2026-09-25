"""Bounded autonomous build/repair orchestration for Code Builder V2.

This module owns policy and task-state transitions only. Coding engines, runtime
execution, and browser verification are injected behind narrow protocols so
Lumina can replace providers without changing orchestration policy.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol

from code_builder.openhands_workspace_service import OpenHandsWorkspaceService


class AutonomousPhase(str, Enum):
    PREPARING = "preparing"
    BUILDING = "building"
    RUNNING = "running"
    TESTING = "testing"
    DIAGNOSING = "diagnosing"
    REPAIRING = "repairing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class FailureEvidence:
    summary: str
    command: str | None = None
    stdout: str = ""
    stderr: str = ""
    console_errors: tuple[str, ...] = ()
    network_errors: tuple[str, ...] = ()
    screenshot_paths: tuple[str, ...] = ()

    @property
    def fingerprint(self) -> str:
        payload = "\n".join(
            (
                self.summary,
                self.command or "",
                self.stdout[-20_000:],
                self.stderr[-20_000:],
                *self.console_errors,
                *self.network_errors,
            )
        )
        return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()


@dataclass(frozen=True, slots=True)
class AttemptResult:
    successful: bool
    changed_paths: tuple[str, ...] = ()
    evidence: FailureEvidence | None = None


@dataclass(frozen=True, slots=True)
class RepairInstruction:
    instruction: str
    relevant_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AutonomousEvent:
    phase: AutonomousPhase
    attempt: int
    message: str


@dataclass(frozen=True, slots=True)
class AutonomousBuildResult:
    successful: bool
    attempts: int
    changed_paths: tuple[str, ...]
    events: tuple[AutonomousEvent, ...]
    final_evidence: FailureEvidence | None = None
    stop_reason: str | None = None


class BuildAttemptRunner(Protocol):
    def run_attempt(
        self,
        *,
        workspace_root: Path,
        instruction: str,
        attempt: int,
        previous_evidence: FailureEvidence | None,
    ) -> AttemptResult: ...


class FailureDiagnoser(Protocol):
    def diagnose(
        self,
        *,
        original_instruction: str,
        attempt: int,
        evidence: FailureEvidence,
    ) -> RepairInstruction: ...


@dataclass(slots=True)
class AutonomousBuildLoop:
    runner: BuildAttemptRunner
    diagnoser: FailureDiagnoser
    workspace_service: OpenHandsWorkspaceService = field(
        default_factory=OpenHandsWorkspaceService
    )
    max_attempts: int = 3
    max_repeated_failure_fingerprints: int = 2

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        if not 1 <= self.max_repeated_failure_fingerprints <= self.max_attempts:
            raise ValueError(
                "max_repeated_failure_fingerprints must be between 1 and max_attempts"
            )

    def execute(
        self,
        *,
        repository_root: str | Path,
        instruction: str,
    ) -> AutonomousBuildResult:
        normalized = instruction.strip()
        if not normalized:
            raise ValueError("Autonomous build instruction must not be empty")

        workspace = self.workspace_service.prepare(repository_root)
        events: list[AutonomousEvent] = [
            AutonomousEvent(AutonomousPhase.PREPARING, 0, "Disposable workspace prepared")
        ]
        changed_paths: set[str] = set()
        fingerprints: dict[str, int] = {}
        current_instruction = normalized
        previous_evidence: FailureEvidence | None = None

        try:
            for attempt in range(1, self.max_attempts + 1):
                phase = AutonomousPhase.BUILDING if attempt == 1 else AutonomousPhase.REPAIRING
                events.append(
                    AutonomousEvent(phase, attempt, "Executing coding attempt in disposable workspace")
                )
                result = self.runner.run_attempt(
                    workspace_root=workspace.workspace_root,
                    instruction=current_instruction,
                    attempt=attempt,
                    previous_evidence=previous_evidence,
                )
                changed_paths.update(result.changed_paths)

                if result.successful:
                    events.append(
                        AutonomousEvent(
                            AutonomousPhase.COMPLETED,
                            attempt,
                            "Acceptance criteria passed in disposable workspace",
                        )
                    )
                    return AutonomousBuildResult(
                        successful=True,
                        attempts=attempt,
                        changed_paths=tuple(sorted(changed_paths)),
                        events=tuple(events),
                    )

                evidence = result.evidence
                if evidence is None:
                    evidence = FailureEvidence(
                        summary="Attempt failed without structured evidence"
                    )
                previous_evidence = evidence
                count = fingerprints.get(evidence.fingerprint, 0) + 1
                fingerprints[evidence.fingerprint] = count

                events.append(
                    AutonomousEvent(
                        AutonomousPhase.DIAGNOSING,
                        attempt,
                        evidence.summary,
                    )
                )
                if count >= self.max_repeated_failure_fingerprints:
                    reason = "Repeated identical failure evidence; repair loop stopped"
                    events.append(AutonomousEvent(AutonomousPhase.FAILED, attempt, reason))
                    return AutonomousBuildResult(
                        successful=False,
                        attempts=attempt,
                        changed_paths=tuple(sorted(changed_paths)),
                        events=tuple(events),
                        final_evidence=evidence,
                        stop_reason=reason,
                    )

                if attempt == self.max_attempts:
                    reason = "Maximum repair attempts reached"
                    events.append(AutonomousEvent(AutonomousPhase.FAILED, attempt, reason))
                    return AutonomousBuildResult(
                        successful=False,
                        attempts=attempt,
                        changed_paths=tuple(sorted(changed_paths)),
                        events=tuple(events),
                        final_evidence=evidence,
                        stop_reason=reason,
                    )

                repair = self.diagnoser.diagnose(
                    original_instruction=normalized,
                    attempt=attempt,
                    evidence=evidence,
                )
                if not repair.instruction.strip():
                    reason = "Diagnoser returned an empty repair instruction"
                    events.append(AutonomousEvent(AutonomousPhase.FAILED, attempt, reason))
                    return AutonomousBuildResult(
                        successful=False,
                        attempts=attempt,
                        changed_paths=tuple(sorted(changed_paths)),
                        events=tuple(events),
                        final_evidence=evidence,
                        stop_reason=reason,
                    )
                current_instruction = repair.instruction

            raise AssertionError("bounded loop exhausted without returning")
        finally:
            workspace.cleanup()
