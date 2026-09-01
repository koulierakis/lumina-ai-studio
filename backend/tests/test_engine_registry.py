import pytest
from code_builder.engine_registry import CodingEngineRegistry
from code_builder.openhands_engine import OpenHandsEngine
class FakeAdapter:
    def __init__(self,available):self.available=available
    def is_available(self):return self.available
class FakeResult:
    def public_summary(self):return{"successful":True,"changed_files":1,"change_counts":{"created":0,"modified":1,"deleted":0},"changes":[]}
class FakeExecutionService:
    def __init__(self,available):self.adapter=FakeAdapter(available)
    def execute(self,*,repository_root,instruction):return FakeResult()
def registry(available):return CodingEngineRegistry(OpenHandsEngine(FakeExecutionService(available)))
def test_registry_keeps_native_default():assert registry(False).validate_selection(None)=="native"
def test_review_requires_approval_backup_rollback_and_runtime_validation():
    p=registry(True).execute_for_review(engine="openhands",repository_root="repo",instruction="fix it");assert p["status"]=="awaiting_approval"and p["can_apply"]is False and p["backup_required_before_apply"]is True and p["rollback_required_after_apply"]is True and p["runtime_validated"]is False
def test_registry_does_not_replace_native_task_service():
    with pytest.raises(RuntimeError,match="existing Code Builder task service"):registry(True).execute(engine="native",repository_root="repo",instruction="fix it")
def test_registry_rejects_unavailable_openhands():
    with pytest.raises(RuntimeError):registry(False).validate_selection("openhands")
