from pathlib import Path

import pytest

from code_builder_v2.models import ChangePlan, PlannedChange, TaskRequest, TaskStatus
from code_builder_v2.repository import Repository
from code_builder_v2.security import UnsafePathError
from code_builder_v2.service import CodeBuilderService


class FakePlanner:
    def create_plan(self, request: TaskRequest) -> ChangePlan:
        return ChangePlan(
            summary="Create requested file",
            changes=[PlannedChange(path="example.py", operation="create", reason=request.prompt)],
            validation_commands=["python -m pytest -q"],
        )


def test_task_reaches_approval_after_planning():
    service = CodeBuilderService(planner=FakePlanner())
    task = service.create_task(TaskRequest(prompt="Create an example module"))
    planned = service.plan_task(task.id)

    assert planned.status is TaskStatus.awaiting_approval
    assert planned.plan is not None
    assert planned.plan.changes[0].path == "example.py"


def test_cancel_task():
    service = CodeBuilderService(planner=FakePlanner())
    task = service.create_task(TaskRequest(prompt="Create an example module"))

    cancelled = service.cancel_task(task.id)

    assert cancelled.status is TaskStatus.cancelled


def test_repository_rejects_path_escape(tmp_path: Path):
    repo = Repository(tmp_path)

    with pytest.raises(UnsafePathError):
        repo.write_text("../outside.txt", "blocked")


def test_repository_round_trip(tmp_path: Path):
    repo = Repository(tmp_path)
    repo.write_text("src/example.py", "answer = 42\n")

    assert repo.read_text("src/example.py") == "answer = 42\n"
