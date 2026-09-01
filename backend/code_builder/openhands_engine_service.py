"""Safe OpenHands execution pipeline for LUMINA Code Builder experiments."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .openhands_adapter import OpenHandsAdapter, OpenHandsRunResult
from .openhands_change_capture_service import (
    OpenHandsChangeCaptureService,
    OpenHandsFileChange,
)
from .openhands_workspace_service import OpenHandsWorkspaceService


@dataclass(frozen=True, slots=True)
class OpenHandsEngineResult:
    run_result: OpenHandsRunResult
    changes: tuple[OpenHandsFileChange, ...]


class OpenHandsEngineService:
    """Run OpenHands only in a disposable copy and return reviewable text changes."""

    def __init__(
        self,
        *,
        adapter: OpenHandsAdapter | Any | None = None,
        workspace_service: OpenHandsWorkspaceService | None = None,
        change_capture_service: OpenHandsChangeCaptureService | None = None,
    ) -> None:
        self.adapter = adapter or OpenHandsAdapter()
        self.workspace_service = workspace_service or OpenHandsWorkspaceService()
        self.change_capture_service = change_capture_service or OpenHandsChangeCaptureService()

    def run(
        self,
        *,
        repository_root: str | Path,
        prompt: str,
    ) -> OpenHandsEngineResult:
        workspace = self.workspace_service.prepare(repository_root)
        try:
            before = self.change_capture_service.snapshot(workspace.workspace_root)
            run_result = self.adapter.run(
                prompt=prompt,
                workspace_root=workspace.workspace_root,
                disposable_workspace=True,
            )
            after = self.change_capture_service.snapshot(workspace.workspace_root)
            changes = self.change_capture_service.compare(before, after)
            return OpenHandsEngineResult(run_result=run_result, changes=changes)
        finally:
            workspace.cleanup()
