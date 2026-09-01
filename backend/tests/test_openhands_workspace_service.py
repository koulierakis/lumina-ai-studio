from __future__ import annotations

from pathlib import Path

from code_builder.openhands_workspace_service import OpenHandsWorkspaceService


def test_prepare_copies_project_without_heavy_or_runtime_directories(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    (source / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (source / ".lumina-runtime").mkdir()
    (source / ".lumina-runtime" / "state.json").write_text("{}", encoding="utf-8")
    (source / "node_modules").mkdir()
    (source / "node_modules" / "package.txt").write_text("skip", encoding="utf-8")

    workspace = OpenHandsWorkspaceService().prepare(source)
    try:
        assert workspace.workspace_root != source
        assert (workspace.workspace_root / "app.py").read_text(encoding="utf-8") == "print('hello')\n"
        assert not (workspace.workspace_root / ".lumina-runtime").exists()
        assert not (workspace.workspace_root / "node_modules").exists()
        assert (workspace.workspace_root / ".lumina_openhands_sandbox").is_file()
    finally:
        workspace.cleanup()


def test_cleanup_removes_disposable_workspace(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    (source / "README.md").write_text("test\n", encoding="utf-8")

    workspace = OpenHandsWorkspaceService().prepare(source)
    temp_parent = workspace.workspace_root.parent
    assert temp_parent.exists()

    workspace.cleanup()

    assert not temp_parent.exists()
