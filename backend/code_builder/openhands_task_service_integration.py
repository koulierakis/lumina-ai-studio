"""Optional OpenHands integration at the existing TaskService lifecycle boundary.

The router already performs a two-pass workflow for approval-required tasks:
1. dry-run preparation
2. approved execution

This installer reuses that workflow without changing the router API contract.  A
client opts in with metadata.coding_engine="openhands".  Native behavior remains
untouched for every other task.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .openhands_preparation_service import OpenHandsPreparationService

_INSTALLED = False


def _is_openhands(request: Any) -> bool:
    metadata = getattr(request, "metadata", None)
    if not isinstance(metadata, Mapping):
        return False
    return str(metadata.get("coding_engine", "native")).strip().casefold() == "openhands"


def _is_preparation(request: Any) -> bool:
    metadata = getattr(request, "metadata", None)
    return bool(isinstance(metadata, Mapping) and metadata.get("code_builder_preparation"))


def install_openhands_task_service_integration() -> None:
    """Install once; preserve the original TaskService implementation."""
    global _INSTALLED
    if _INSTALLED:
        return

    from . import task_service as module

    original_execute = module.TaskService.execute
    original_planning_stage = module.TaskService._execute_planning_stage

    def execute(self, task, *, event_callback=None, cancellation_token=None, return_domain_model=True):
        request = module._task_request_from_domain_model(task)
        if _is_openhands(request) and _is_preparation(request):
            # OpenHands works only in its disposable copy.  The returned patch is
            # review metadata; it does not modify the source repository.
            preparation = OpenHandsPreparationService().prepare(
                task_id=request.task_id,
                repository_root=self.configuration.repository_root,
                instruction=request.instruction,
            )
            return preparation

        return original_execute(
            self,
            task,
            event_callback=event_callback,
            cancellation_token=cancellation_token,
            return_domain_model=return_domain_model,
        )

    def planning_stage(self, context, recorder):
        metadata = getattr(context.request, "metadata", {})
        approved_plan = (
            metadata.get("approved_preparation_plan")
            if isinstance(metadata, Mapping)
            else None
        )
        if _is_openhands(context.request) and approved_plan is not None:
            # The patch was approved against this exact OpenHands plan.  Reusing
            # it prevents a second AI planner from silently changing scope.
            self._record_event(
                context,
                recorder,
                stage=module.TaskStage.PLANNING,
                status=module.TaskStatus.PLANNING,
                level=module.TaskEventLevel.INFO,
                message="Approved OpenHands implementation plan loaded.",
                details={"coding_engine": "openhands", "approved_plan": True},
            )
            context.plan = approved_plan
            return
        return original_planning_stage(self, context, recorder)

    module.TaskService.execute = execute
    module.TaskService._execute_planning_stage = planning_stage
    _INSTALLED = True
