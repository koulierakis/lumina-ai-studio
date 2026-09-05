from __future__ import annotations

from typing import Protocol

from .models import ChangePlan, TaskRequest


class Planner(Protocol):
    def create_plan(self, request: TaskRequest) -> ChangePlan:
        """Return a structured plan. Implementations may call Ollama/OpenAI/etc."""


class PlannerUnavailable(RuntimeError):
    pass
