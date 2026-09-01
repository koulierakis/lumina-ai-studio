from pathlib import Path
import pytest

from code_builder.openhands_adapter import OpenHandsRunResult
from code_builder.openhands_engine_service import OpenHandsEngineService
from code_builder.openhands_workspace_service import OpenHandsWorkspaceService


class RecordingWorkspaceService(OpenHandsWorkspaceService):
    def __init__(self):
        super().__init__()
        self.last_workspace = None

    def prepare(self, repository_root):
        self.last_workspace = super().prepare(repository_root)
        return self.last_workspace


class EditingAdapter:
    def run(self, *, prompt, workspace_root, disposable_workspace=False):
        assert disposable_workspace is True
        root = Path(workspace_root)
        (root / "existing.py").write_text("print('after')\n", encoding="utf-8")
        (root / "created.txt").write_text("created\n", encoding="utf-8")
        return OpenHandsRunResult(
            command=("openhands",), returncode=0, events=(), stdout="{}\n", stderr=""
        )


class FailingAdapter:
    def run(self, **_kwargs):
        raise RuntimeError("agent failed")


def test_engine_runs_only_in_copy_and_returns_reviewable_changes(tmp_path: Path):
    (tmp_path / "existing.py").write_text("print('before')\n", encoding="utf-8")
    workspaces = RecordingWorkspaceService()
    engine = OpenHandsEngineService(adapter=EditingAdapter(), workspace_service=workspaces)

    result = engine.run(repository_root=tmp_path, prompt="Edit the file")

    assert (tmp_path / "existing.py").read_text(encoding="utf-8") == "print('before')\n"
    changes = {change.relative_path: change for change in result.changes}
    assert changes["existing.py"].change_type == "modified"
    assert changes["created.txt"].change_type == "created"
    assert workspaces.last_workspace is not None
    assert not workspaces.last_workspace.workspace_root.exists()


def test_engine_always_cleans_workspace_when_agent_fails(tmp_path: Path):
    (tmp_path / "app.py").write_text("pass\n", encoding="utf-8")
    workspaces = RecordingWorkspaceService()
    engine = OpenHandsEngineService(adapter=FailingAdapter(), workspace_service=workspaces)

    with pytest.raises(RuntimeError, match="agent failed"):
        engine.run(repository_root=tmp_path, prompt="Fail safely")

    assert workspaces.last_workspace is not None
    assert not workspaces.last_workspace.workspace_root.exists()
