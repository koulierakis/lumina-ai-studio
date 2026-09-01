from pathlib import Path

import pytest

from code_builder.openhands_adapter import OpenHandsRunResult
from code_builder.openhands_execution_service import MAX_REVIEW_DIFF_CHARACTERS, OpenHandsExecutionService


class FakeAdapter:
    def run(self, *, prompt, workspace_root, disposable_workspace):
        assert disposable_workspace is True
        root = Path(workspace_root)
        (root / "existing.txt").write_text("changed\n", encoding="utf-8")
        (root / "new.txt").write_text("new\n", encoding="utf-8")
        return OpenHandsRunResult(("fake",), 0, (), "", "")


def test_openhands_changes_only_disposable_copy(tmp_path: Path):
    (tmp_path / "existing.txt").write_text("original\n", encoding="utf-8")
    result = OpenHandsExecutionService(adapter=FakeAdapter()).execute(repository_root=tmp_path, instruction="change files")
    assert (tmp_path / "existing.txt").read_text(encoding="utf-8") == "original\n"
    assert [(c.path, c.change_type) for c in result.changes] == [("existing.txt", "modified"), ("new.txt", "created")]


def test_openhands_result_has_review_ready_summary(tmp_path: Path):
    (tmp_path / "existing.txt").write_text("original\n", encoding="utf-8")
    summary = OpenHandsExecutionService(adapter=FakeAdapter()).execute(repository_root=tmp_path, instruction="change files").public_summary()
    assert summary["successful"] is True and summary["changed_files"] == 2


def test_empty_instruction_is_rejected_before_workspace_creation(tmp_path: Path):
    with pytest.raises(ValueError, match="must not be empty"):
        OpenHandsExecutionService(adapter=FakeAdapter()).execute(repository_root=tmp_path, instruction="   ")


def test_large_review_diff_is_truncated():
    before = ("a" * (MAX_REVIEW_DIFF_CHARACTERS + 1000)).encode()
    after = ("b" * (MAX_REVIEW_DIFF_CHARACTERS + 1000)).encode()
    diff = OpenHandsExecutionService._text_diff("large.txt", before, after)
    assert len(diff) <= MAX_REVIEW_DIFF_CHARACTERS + 100
    assert "truncated for safe review" in diff
