import pytest

from code_builder.engine_preparation_service import (
    CodeBuilderEnginePreparationService,
    EnginePreparationError,
)


class FakeRegistry:
    def validate_selection(self, name):
        return name or "native"


class FakeOpenHandsPreparation:
    def __init__(self):
        self.last_kwargs = None

    def prepare(self, **kwargs):
        self.last_kwargs = kwargs
        return {
            "task_id": kwargs["task_id"],
            "engine": "openhands",
            "plan": {"files": ["demo.txt"]},
            "patch": {"operations": [{"operation": "create", "path": "demo.txt", "content": "ok\n"}]},
        }


def service(openhands=None):
    return CodeBuilderEnginePreparationService(
        registry=FakeRegistry(),
        openhands=openhands or FakeOpenHandsPreparation(),
    )


def test_native_engine_uses_existing_preparation_callback():
    result = service().prepare(
        engine="native",
        task_id="t1",
        repository_root="repo",
        instruction="fix",
        native_prepare=lambda: {"engine": "native", "value": 1},
    )
    assert result == {"engine": "native", "value": 1}


def test_openhands_engine_uses_openhands_preparation():
    result = service().prepare(
        engine="openhands",
        task_id="t2",
        repository_root="repo",
        instruction="fix",
        native_prepare=lambda: pytest.fail("native preparation should not run"),
    )
    assert result["engine"] == "openhands"
    assert result["patch"]["operations"][0]["path"] == "demo.txt"


def test_openhands_engine_preserves_task_scope_and_file_permissions():
    fake = FakeOpenHandsPreparation()
    service(fake).prepare(
        engine="openhands",
        task_id="t-scope",
        repository_root="repo",
        instruction="fix only backend",
        target_paths=("backend",),
        excluded_paths=("backend/secrets",),
        allow_file_creation=False,
        allow_file_deletion=True,
        native_prepare=lambda: pytest.fail("native preparation should not run"),
    )
    assert fake.last_kwargs["target_paths"] == ("backend",)
    assert fake.last_kwargs["excluded_paths"] == ("backend/secrets",)
    assert fake.last_kwargs["allow_file_creation"] is False
    assert fake.last_kwargs["allow_file_deletion"] is True


def test_approval_metadata_matches_existing_task_service_contract():
    metadata = service().approval_metadata(
        {
            "task_id": "t3",
            "engine": "openhands",
            "plan": {"files": ["demo.txt"]},
            "patch": {"operations": [{"operation": "create", "path": "demo.txt", "content": "ok\n"}]},
        }
    )
    assert metadata["approved_preparation_task_id"] == "t3"
    assert metadata["coding_engine"] == "openhands"
    assert metadata["approved_preparation_plan"] == {"files": ["demo.txt"]}
    assert metadata["approved_patch_operations"][0]["path"] == "demo.txt"


def test_approval_metadata_rejects_missing_operations():
    with pytest.raises(EnginePreparationError):
        service().approval_metadata({"task_id": "t4", "patch": {"operations": []}})
