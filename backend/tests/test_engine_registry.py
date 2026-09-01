import pytest
from code_builder.engine_registry import CodingEngineRegistry
from code_builder.openhands_engine import OpenHandsEngine
class FakeAdapter:
    def __init__(self,available):self.available=available
    def is_available(self):return self.available
class FakeResult:
    def public_summary(self):return{"successful":True,"changed_files":1,"changes":[]}
class FakeExecutionService:
    def __init__(self,available):self.adapter=FakeAdapter(available)
    def execute(self,*,repository_root,instruction):return FakeResult()
def registry(available):return CodingEngineRegistry(OpenHandsEngine(FakeExecutionService(available)))
def test_registry_keeps_native_default():assert registry(False).validate_selection(None)=="native"
def test_registry_reports_openhands_safe_mode():assert registry(True).options()[1].safe_mode is True
def test_registry_public_status_is_ui_ready():assert registry(True).public_status()["engines"][1]["name"]=="openhands"
def test_review_is_safe_requires_approval_and_is_not_applied():
    p=registry(True).execute_for_review(engine="openhands",repository_root="repo",instruction="fix it")
    assert p["successful"] is True and p["requires_approval"] is True and p["safe_mode"] is True and p["applied"] is False
def test_registry_does_not_replace_native_task_service():
    with pytest.raises(RuntimeError,match="existing Code Builder task service"):registry(True).execute(engine="native",repository_root="repo",instruction="fix it")
def test_registry_rejects_unavailable_openhands():
    with pytest.raises(RuntimeError):registry(False).validate_selection("openhands")
