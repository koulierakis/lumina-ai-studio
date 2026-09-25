from pathlib import Path

from code_builder_v2.applier import ProposedFileChange
from code_builder_v2.models import ChangePlan, PlannedChange, TaskRequest
from code_builder_v2.runtime import VerifiedWorkspacePublisher, WorkspaceAttemptRunner


class RepairingGenerator:
    def __init__(self):
        self.calls = 0

    def generate(self, request, plan, file_context):
        self.calls += 1
        operation = plan.changes[0].operation
        value = 1 if self.calls == 1 else 2
        return [
            ProposedFileChange(
                path="app.py",
                operation=operation,
                content=f"VALUE = {value}\n",
            )
        ]


def test_workspace_attempt_runner_preserves_failed_change_for_repair(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    generator = RepairingGenerator()
    plan = ChangePlan(
        summary="Create app",
        changes=[
            PlannedChange(path="app.py", operation="create", reason="requested")
        ],
        validation_commands=[
            'python -c "import app;assert app.VALUE==2"'
        ],
    )
    runner = WorkspaceAttemptRunner(
        generator=generator,
        plan=plan,
        request=TaskRequest(prompt="Create app", timeout_seconds=30),
    )

    first = runner.run_attempt(
        workspace_root=workspace,
        instruction="Create app",
        attempt=1,
        previous_evidence=None,
    )
    second = runner.run_attempt(
        workspace_root=workspace,
        instruction="Repair app",
        attempt=2,
        previous_evidence=first.evidence,
    )

    assert first.successful is False
    assert first.evidence is not None
    assert first.evidence.command == 'python -c "import app;assert app.VALUE==2"'
    assert second.successful is True
    assert generator.calls == 2
    assert (workspace / "app.py").read_text(encoding="utf-8") == "VALUE = 2\n"


def test_verified_workspace_publisher_atomically_syncs_changed_paths(tmp_path: Path):
    source = tmp_path / "source"
    workspace = tmp_path / "workspace"
    runtime = tmp_path / "runtime"
    source.mkdir()
    workspace.mkdir()
    (source / "modify.py").write_text("OLD = True\n", encoding="utf-8")
    (source / "delete.py").write_text("DELETE = True\n", encoding="utf-8")
    (workspace / "modify.py").write_text("OLD = False\n", encoding="utf-8")
    (workspace / "create.py").write_text("CREATED = True\n", encoding="utf-8")

    result = VerifiedWorkspacePublisher(runtime).publish(
        source_root=source,
        workspace_root=workspace,
        changed_paths=("modify.py", "create.py", "delete.py"),
    )

    assert result.backup_id
    assert result.changed_paths == ("create.py", "delete.py", "modify.py")
    assert (source / "modify.py").read_text(encoding="utf-8") == "OLD = False\n"
    assert (source / "create.py").read_text(encoding="utf-8") == "CREATED = True\n"
    assert not (source / "delete.py").exists()


def test_verified_workspace_publisher_enforces_file_limit(tmp_path: Path):
    source = tmp_path / "source"
    workspace = tmp_path / "workspace"
    source.mkdir()
    workspace.mkdir()

    publisher = VerifiedWorkspacePublisher(
        tmp_path / "runtime",
        max_changed_files=1,
    )

    try:
        publisher.publish(
            source_root=source,
            workspace_root=workspace,
            changed_paths=("one.py", "two.py"),
        )
    except ValueError as exc:
        assert "limit is 1" in str(exc)
    else:
        raise AssertionError("Expected file limit to be enforced")
