from pathlib import Path

from code_builder.openhands_workspace_service import OpenHandsWorkspaceService


def test_workspace_is_copy_and_excludes_runtime_and_secrets(tmp_path: Path):
    (tmp_path / "app.txt").write_text("safe", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=value", encoding="utf-8")
    (tmp_path / ".lumina-runtime").mkdir()
    (tmp_path / ".lumina-runtime" / "state.json").write_text("{}", encoding="utf-8")
    workspace = OpenHandsWorkspaceService().prepare(tmp_path)
    try:
        assert (workspace.workspace_root / "app.txt").read_text(encoding="utf-8") == "safe"
        assert not (workspace.workspace_root / ".env").exists()
        assert not (workspace.workspace_root / ".lumina-runtime").exists()
        assert (workspace.workspace_root / ".lumina_openhands_sandbox").exists()
    finally:
        workspace.cleanup()
    assert not workspace.workspace_root.exists()
