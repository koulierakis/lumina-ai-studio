from pathlib import Path

from code_builder_v2.backup import BackupService
from code_builder_v2.models import ChangePlan, TaskRequest
from code_builder_v2.service import CodeBuilderService
from code_builder_v2.store import JsonTaskStore


class EmptyPlanner:
    def create_plan(self, request: TaskRequest) -> ChangePlan:
        return ChangePlan(summary="No-op")


def test_task_persists_across_service_restart(tmp_path: Path):
    store = JsonTaskStore(tmp_path / "tasks.json")
    first = CodeBuilderService(planner=EmptyPlanner(), store=store)
    task = first.create_task(TaskRequest(prompt="Persist this task"))

    restarted = CodeBuilderService(planner=EmptyPlanner(), store=store)

    assert restarted.get_task(task.id).request.prompt == "Persist this task"


def test_backup_restores_modified_and_created_files(tmp_path: Path):
    repo = tmp_path / "repo"
    backups = tmp_path / "backups"
    repo.mkdir()
    (repo / "existing.txt").write_text("before", encoding="utf-8")

    service = BackupService(repo, backups)
    manifest = service.create(["existing.txt", "created.txt"])

    (repo / "existing.txt").write_text("after", encoding="utf-8")
    (repo / "created.txt").write_text("new", encoding="utf-8")

    service.restore(manifest.id)

    assert (repo / "existing.txt").read_text(encoding="utf-8") == "before"
    assert not (repo / "created.txt").exists()
