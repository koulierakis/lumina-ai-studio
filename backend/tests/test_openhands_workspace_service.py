from pathlib import Path
import os
import pytest
from code_builder.openhands_workspace_service import OpenHandsWorkspaceService

def test_workspace_is_copy_and_excludes_runtime_secrets_and_venv(tmp_path:Path):
    (tmp_path/"app.txt").write_text("safe",encoding="utf-8");(tmp_path/".env").write_text("SECRET=value",encoding="utf-8");(tmp_path/".env.development").write_text("OTHER=value",encoding="utf-8");(tmp_path/".lumina-runtime").mkdir();(tmp_path/".venv").mkdir();w=OpenHandsWorkspaceService().prepare(tmp_path)
    try:
        assert(w.workspace_root/"app.txt").exists();assert not(w.workspace_root/".env").exists();assert not(w.workspace_root/".env.development").exists();assert not(w.workspace_root/".lumina-runtime").exists();assert not(w.workspace_root/".venv").exists();assert(w.workspace_root/".lumina_openhands_sandbox").exists()
    finally:w.cleanup()
    assert not w.workspace_root.exists()

def test_workspace_does_not_follow_repository_symlink(tmp_path:Path):
    outside=tmp_path.parent/"outside-secret.txt";outside.write_text("TOP-SECRET",encoding="utf-8")
    link=tmp_path/"linked-secret.txt"
    try:os.symlink(outside,link)
    except (OSError,NotImplementedError):pytest.skip("Symlinks are not available in this environment")
    w=OpenHandsWorkspaceService().prepare(tmp_path)
    try:assert not(w.workspace_root/"linked-secret.txt").exists()
    finally:w.cleanup()
