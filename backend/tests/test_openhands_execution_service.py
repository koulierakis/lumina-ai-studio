from pathlib import Path
import pytest
from code_builder.openhands_adapter import OpenHandsRunResult
from code_builder.openhands_execution_service import MAX_REVIEW_DIFF_CHARACTERS,OpenHandsExecutionService
class FakeAdapter:
    def run(self,*,prompt,workspace_root,disposable_workspace):
        assert disposable_workspace is True;root=Path(workspace_root);(root/"existing.txt").write_text("changed\n",encoding="utf-8");(root/"new.txt").write_text("new\n",encoding="utf-8");return OpenHandsRunResult(("fake",),0,(),"","")
def test_openhands_changes_only_copy(tmp_path:Path):
    (tmp_path/"existing.txt").write_text("original\n",encoding="utf-8");r=OpenHandsExecutionService(adapter=FakeAdapter()).execute(repository_root=tmp_path,instruction="change files");assert(tmp_path/"existing.txt").read_text(encoding="utf-8")=="original\n";assert len(r.changes)==2
def test_review_summary(tmp_path:Path):
    (tmp_path/"existing.txt").write_text("original\n",encoding="utf-8");s=OpenHandsExecutionService(adapter=FakeAdapter()).execute(repository_root=tmp_path,instruction="change files").public_summary();assert s["successful"]is True and s["changed_files"]==2
def test_empty_instruction_rejected(tmp_path:Path):
    with pytest.raises(ValueError):OpenHandsExecutionService(adapter=FakeAdapter()).execute(repository_root=tmp_path,instruction=" ")
def test_large_diff_truncated():
    d=OpenHandsExecutionService._text_diff("large.txt",("a"*(MAX_REVIEW_DIFF_CHARACTERS+1000)).encode(),("b"*(MAX_REVIEW_DIFF_CHARACTERS+1000)).encode());assert"truncated for safe review"in d
