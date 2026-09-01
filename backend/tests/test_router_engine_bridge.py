from code_builder.router_engine_bridge import (
    approved_request_metadata,
    prepare_for_router,
    requested_engine,
)


class FakePreparationService:
    def prepare(self, **kwargs):
        return kwargs

    def approval_metadata(self, preparation_result):
        return {
            "approved_patch_operations": [{"operation": "create", "path": "demo.txt", "content": "ok\n"}],
            "approved_preparation_plan": {"files": ["demo.txt"]},
            "approved_preparation_task_id": "task-1",
            "coding_engine": preparation_result.get("engine", "native"),
        }


def test_requested_engine_defaults_to_native():
    assert requested_engine(None) == "native"
    assert requested_engine({}) == "native"


def test_requested_engine_normalizes_value():
    assert requested_engine({"coding_engine": " OpenHands "}) == "openhands"


def test_prepare_for_router_preserves_native_callback():
    result = prepare_for_router(
        preparation_service=FakePreparationService(),
        task_id="task-1",
        repository_root="repo",
        instruction="fix it",
        metadata={},
        native_prepare=lambda: "native-result",
    )
    assert result["engine"] == "native"
    assert result["native_prepare"]() == "native-result"


def test_prepare_for_router_routes_openhands():
    result = prepare_for_router(
        preparation_service=FakePreparationService(),
        task_id="task-1",
        repository_root="repo",
        instruction="fix it",
        metadata={"coding_engine": "openhands"},
        native_prepare=lambda: "native-result",
    )
    assert result["engine"] == "openhands"


def test_approved_request_metadata_keeps_existing_values_and_replaces_patch_keys():
    metadata = approved_request_metadata(
        preparation_service=FakePreparationService(),
        existing_metadata={
            "keep_me": 7,
            "patch_operations": ["old"],
            "execution_patch_operations": ["old"],
        },
        preparation_result={"engine": "openhands"},
    )
    assert metadata["keep_me"] == 7
    assert "patch_operations" not in metadata
    assert "execution_patch_operations" not in metadata
    assert metadata["coding_engine"] == "openhands"
    assert metadata["approved_patch_operations"][0]["path"] == "demo.txt"
