"""Composition helpers for the autonomous Code Builder runtime."""
from __future__ import annotations

from pathlib import Path

from .autonomous import AutonomousBuildLoop
from .models import BuildTask
from .ollama import OllamaChangeGenerator, OllamaClient
from .runtime import (
    EvidenceDiagnoser,
    VerifiedWorkspacePublisher,
    WorkspaceAttemptRunner,
)


def create_autonomous_loop(
    task: BuildTask,
    *,
    client: OllamaClient,
    runtime_root: Path,
) -> AutonomousBuildLoop:
    if task.plan is None:
        raise ValueError("Cannot create autonomous runtime without a plan")
    runner = WorkspaceAttemptRunner(
        generator=OllamaChangeGenerator(client),
        plan=task.plan,
        request=task.request,
    )
    return AutonomousBuildLoop(
        runner=runner,
        diagnoser=EvidenceDiagnoser(client, model=task.request.model),
        publisher=VerifiedWorkspacePublisher(runtime_root),
        max_attempts=task.request.max_attempts,
    )
