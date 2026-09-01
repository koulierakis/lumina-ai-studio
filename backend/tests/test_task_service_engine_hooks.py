from pathlib import Path
from types import SimpleNamespace

from code_builder import task_service_engine_hooks as hooks


def context(tmp_path: Path, *, metadata=None, dry_run=True):
    request = SimpleNamespace(
        task_id="t1",
        instruction="change demo",
        target_paths=("demo.txt",),
        excluded_paths=("secret.txt",),
        allow_file_creation=True,
        allow_file_deletion=False,
        dry_run=dry_run,
        metadata=dict(metadata or {}),
    )
    return SimpleNamespace(
        request=request,
        configuration=SimpleNamespace(repository_root=tmp_path),
        metadata={},
    )


def test_native_request_does_not_activate_hooks(tmp_path):
    c = context(tmp_path, metadata={})
    assert hooks.is_openhands_request(c) is False
    assert hooks.should_bypass_native_analysis(c) is False
    assert hooks.prepare_or_reuse_plan(c) is None


def test_openhands_preparation_uses_minimal_analysis(tmp_path):
    c = context(tmp_path, metadata={"coding_engine": "openhands", "code_builder_preparation": True})
    assert hooks.is_openhands_preparation(c) is True
    analysis = hooks.build_minimal_analysis(c)
    assert analysis["engine"] == "openhands"
    assert analysis["repository_root"] == str(tmp_path.resolve())
    assert analysis["analysis_mode"] == "openhands_sandbox"


def test_approved_openhands_execution_reuses_plan_without_new_agent_run(tmp_path):
    plan = {"files": ["demo.txt"], "engine": "openhands"}
    c = context(
        tmp_path,
        metadata={
            "coding_engine": "openhands",
            "approved_preparation_plan": plan,
            "approved_patch_operations": [
                {"operation": "modify", "path": "demo.txt", "content": "new\n"}
            ],
        },
        dry_run=False,
    )
    assert hooks.should_bypass_native_analysis(c) is True
    assert hooks.prepare_or_reuse_plan(c) == plan
    assert hooks.prepared_patch_for_context(c) is None


def test_prepared_patch_is_rehydrated_for_dry_run(tmp_path):
    c = context(tmp_path, metadata={"coding_engine": "openhands", "code_builder_preparation": True})
    c.metadata["_openhands_preparation_result"] = {
        "patch": {
            "operations": [
                {"operation": "create", "path": "demo.txt", "content": "ok\n"}
            ],
            "dry_run": True,
            "rollback_on_failure": True,
            "description": "OpenHands proposal",
        },
        "source_repository_unchanged": True,
    }
    patch = hooks.prepared_patch_for_context(c)
    assert patch is not None
    assert patch.dry_run is True
    assert patch.operations[0].path == "demo.txt"
    public = hooks.public_engine_metadata(c)
    assert public["coding_engine"] == "openhands"
    assert public["source_repository_unchanged"] is True
