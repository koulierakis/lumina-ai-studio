from code_builder.planning_service import (
    CompactGeneratedChangePlan,
    _expand_compact_generated_plan,
)


def test_compact_plan_expands_to_canonical_schema():
    compact = CompactGeneratedChangePlan.model_validate({
        "title": "Create smoke file",
        "summary": "Create one repository-root smoke file.",
        "objective": "Verify controlled Code Builder planning.",
        "files": [{
            "path": "CODE_BUILDER_SMOKE_TEST.txt",
            "operation": "create",
            "summary": "Create smoke file.",
            "rationale": "Exercise the approval pipeline."
        }],
        "steps": [{
            "order": 1,
            "title": "Create file",
            "description": "Create the requested repository-root file.",
            "file_paths": ["CODE_BUILDER_SMOKE_TEST.txt"]
        }],
        "acceptance_criteria": ["File contains the requested text."],
        "test_plan": ["Verify exact file contents."]
    })
    expanded = _expand_compact_generated_plan(compact)
    assert expanded.files[0].path == "CODE_BUILDER_SMOKE_TEST.txt"
    assert expanded.files[0].operation == "create"
    assert expanded.steps[0].file_paths == ["CODE_BUILDER_SMOKE_TEST.txt"]
    assert expanded.acceptance_criteria
    assert expanded.test_plan
    assert expanded.rollback_plan
