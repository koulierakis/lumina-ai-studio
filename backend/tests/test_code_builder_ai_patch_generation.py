from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from code_builder.models import ChangePlan, ChangeType, ProposedFileChange
import code_builder.patch_generation_service as patch_generation
from code_builder.patch_generation_service import (
    AIPatchGenerationError,
    _collect_plan_paths,
    _to_patch_request,
    generate_patch,
    install_ai_patch_generation,
)
from code_builder.patch_service import PatchService


def _production_change_plan(relative_path: str) -> ChangePlan:
    """Build the exact ChangePlan shape PlanningService.plan() returns."""

    return ChangePlan(
        task_id=uuid4(),
        title="Enable the feature flag",
        summary="Flip FLAG to True in allowed.py.",
        changes=[
            ProposedFileChange(
                relative_path=relative_path,
                change_type=ChangeType.MODIFY,
                old_content="FLAG = False\n",
                new_content="FLAG = True\n",
                summary="Replace the flag value.",
                reason="Requested by the user instruction.",
            )
        ],
    )


class _PatchServiceStub(PatchService):
    """Real deterministic patch engine bound to a throwaway repository."""

    def __init__(self, repository_root: Path) -> None:
        super().__init__(repository_root=repository_root)


class _Task:
    """Minimal task surface consumed by generate_patch."""

    def __init__(self, instruction: str) -> None:
        self.instruction = instruction
        self.target_paths: tuple[str, ...] = ()
        self.allow_file_creation = True


_Plan = _production_change_plan


def test_plan_paths_are_collected_from_production_change_plan_model() -> None:
    # Regression: the production plan carries its file paths as
    # ProposedFileChange.relative_path, which the collector previously did not
    # recognize, so every approved plan looked path-less.
    assert _collect_plan_paths(_production_change_plan("allowed.py")) == (
        "allowed.py",
    )


def test_generate_patch_uses_production_plan_paths_without_target_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact runtime failure: no target_paths, plan from models.py."""

    target = tmp_path / "allowed.py"
    target.write_text("FLAG = False\n", encoding="utf-8")

    generated_patch = {
        "operations": [
            {
                "operation": "replace_text",
                "path": "allowed.py",
                "content": None,
                "search_text": "FLAG = False",
                "replacement_text": "FLAG = True",
                "unified_diff": None,
                "description": "Enable the feature flag",
            }
        ],
        "description": "Enable the requested flag",
    }
    envelope = json.dumps(
        {"response": json.dumps(generated_patch)},
        ensure_ascii=False,
    ).encode("utf-8")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _limit: int = -1) -> bytes:
            return envelope

    def fake_urlopen(request, timeout):
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    service = PatchService(repository_root=tmp_path)
    task = SimpleNamespace(
        instruction="Change FLAG = false to FLAG = true.",
        target_paths=(),
        allow_file_creation=False,
    )
    plan = _production_change_plan("allowed.py")

    request = generate_patch(
        service,
        task=task,
        analysis={"repository_root": str(tmp_path)},
        plan=plan,
        ollama_service=SimpleNamespace(model="test-coder"),
        repository_root=tmp_path,
        timeout_seconds=10,
    )

    assert request.operations[0].path == "allowed.py"


def test_generate_patch_still_refuses_plan_without_any_paths(
    tmp_path: Path,
) -> None:
    """The unconstrained-edit refusal must survive the path-key fix."""

    service = PatchService(repository_root=tmp_path)
    task = SimpleNamespace(
        instruction="Change FLAG = false to FLAG = true.",
        target_paths=(),
        allow_file_creation=False,
    )
    empty_plan = ChangePlan(
        task_id=uuid4(),
        title="No explicit changes",
        summary="A plan that names no files.",
        changes=[],
    )

    with pytest.raises(AIPatchGenerationError, match="no explicit file paths"):
        generate_patch(
            service,
            task=task,
            analysis={"repository_root": str(tmp_path)},
            plan=empty_plan,
            ollama_service=SimpleNamespace(model="test-coder"),
            repository_root=tmp_path,
            timeout_seconds=10,
        )


def test_ai_patch_generation_hook_is_installed() -> None:
    install_ai_patch_generation()
    assert callable(getattr(PatchService, "generate_patch", None))


def test_ai_patch_rejects_path_outside_approved_plan(tmp_path: Path) -> None:
    target = tmp_path / "allowed.py"
    target.write_text("FLAG = False\n", encoding="utf-8")

    with pytest.raises(AIPatchGenerationError, match="outside the approved plan"):
        _to_patch_request(
            {
                "operations": [
                    {
                        "operation": "replace_text",
                        "path": "other.py",
                        "content": None,
                        "search_text": "FLAG = False",
                        "replacement_text": "FLAG = True",
                        "unified_diff": None,
                        "description": "change flag",
                    }
                ]
            },
            allowed_paths=frozenset({"allowed.py"}),
            root=tmp_path,
            hashes={},
            allow_file_creation=True,
        )


def test_ai_patch_builds_hash_guarded_replace_text(tmp_path: Path) -> None:
    target = tmp_path / "allowed.py"
    target.write_text("FLAG = False\n", encoding="utf-8")

    request = _to_patch_request(
        {
            "operations": [
                {
                    "operation": "replace_text",
                    "path": "allowed.py",
                    "content": None,
                    "search_text": "FLAG = False",
                    "replacement_text": "FLAG = True",
                    "unified_diff": None,
                    "description": "change flag",
                }
            ],
            "description": "safe test patch",
        },
        allowed_paths=frozenset({"allowed.py"}),
        root=tmp_path,
        hashes={},
        allow_file_creation=True,
    )

    assert len(request.operations) == 1
    operation = request.operations[0]
    assert operation.operation == "replace_text"
    assert operation.expected_occurrences == 1
    assert operation.expected_sha256 is not None

    service = PatchService(repository_root=tmp_path)
    dry_run = service.apply_patch(request, dry_run=True)
    assert dry_run.successful
    assert target.read_text(encoding="utf-8") == "FLAG = False\n"


def test_ai_patch_create_respects_task_permission(tmp_path: Path) -> None:
    with pytest.raises(AIPatchGenerationError, match="does not allow creating files"):
        _to_patch_request(
            {
                "operations": [
                    {
                        "operation": "create",
                        "path": "new_file.py",
                        "content": "VALUE = 1\n",
                        "search_text": None,
                        "replacement_text": None,
                        "unified_diff": None,
                        "description": "create file",
                    }
                ]
            },
            allowed_paths=frozenset({"new_file.py"}),
            root=tmp_path,
            hashes={},
            allow_file_creation=False,
        )


def test_natural_language_instruction_generates_valid_patch_without_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "allowed.py"
    target.write_text("# feature flag\nFLAG = False\n", encoding="utf-8")

    generated_patch = {
        "operations": [
            {
                "operation": "replace_text",
                "path": "allowed.py",
                "content": None,
                "search_text": "FLAG = False",
                "replacement_text": "FLAG = True",
                "unified_diff": None,
                "description": "Enable the feature flag",
            }
        ],
        "description": "Enable the requested flag",
    }
    envelope = json.dumps(
        {"response": json.dumps(generated_patch)},
        ensure_ascii=False,
    ).encode("utf-8")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _limit: int = -1) -> bytes:
            return envelope

    def fake_urlopen(request, timeout):
        assert request.full_url == "http://127.0.0.1:11434/api/generate"
        assert timeout > 0
        request_payload = json.loads(request.data.decode("utf-8"))
        assert request_payload["format"]["type"] == "object"
        assert request_payload["options"]["temperature"] == 0
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    service = PatchService(repository_root=tmp_path)
    task = SimpleNamespace(
        instruction="Change FLAG = false to FLAG = true.",
        target_paths=("allowed.py",),
        allow_file_creation=False,
    )
    plan = {
        "summary": "Enable the existing feature flag",
        "changes": [{"path": "allowed.py", "action": "modify"}],
    }

    request = generate_patch(
        service,
        task=task,
        analysis={"repository_root": str(tmp_path)},
        plan=plan,
        ollama_service=SimpleNamespace(model="test-coder"),
        repository_root=tmp_path,
        timeout_seconds=10,
    )

    assert request.operations[0].path == "allowed.py"
    assert request.operations[0].replacement_text == "FLAG = True"
    assert target.read_text(encoding="utf-8") == "# feature flag\nFLAG = False\n"

    applied = service.apply_patch(request)
    assert applied.successful
    assert target.read_text(encoding="utf-8") == "# feature flag\nFLAG = True\n"

def test_create_style_operation_alias_maps_to_canonical_create(tmp_path):
    service = _PatchServiceStub(tmp_path)
    request = patch_generation._to_patch_request(
        {
            "operations": [
                {
                    "operation": "create_file",
                    "path": "CODE_BUILDER_SMOKE_TEST.md",
                    "content": "# smoke",
                }
            ],
            "description": "alias test",
        },
        allowed_paths=frozenset({"CODE_BUILDER_SMOKE_TEST.md"}),
        root=tmp_path,
        hashes={},
        allow_file_creation=True,
    )

    assert request.operations[0].operation == "create"
    assert request.operations[0].path == "CODE_BUILDER_SMOKE_TEST.md"
    assert request.operations[0].content == "# smoke"
    assert service.apply_patch(request).successful


def test_malformed_first_patch_consumes_the_single_repair_attempt(tmp_path, monkeypatch):
    service = _PatchServiceStub(tmp_path)
    responses = [
        {"operations": [{"operation": "nonsense", "path": "missing.txt"}]},
        {
            "operations": [
                {
                    "operation": "create",
                    "path": "repaired.txt",
                    "content": "repaired",
                }
            ],
            "description": "repaired patch",
        },
    ]
    prompts: list[str] = []

    def fake_request(prompt, **_kwargs):
        prompts.append(prompt)
        return responses.pop(0)

    monkeypatch.setattr(patch_generation, "_request_structured_patch", fake_request)

    patch = patch_generation.generate_patch(
        service,
        task=_Task(instruction="create a file"),
        analysis=None,
        plan=_Plan("repaired.txt"),
        ollama_service=SimpleNamespace(model="test-coder"),
        repository_root=tmp_path,
        cancellation_token=None,
    )

    assert [operation.operation for operation in patch.operations] == ["create"]
    assert len(prompts) == 2
    assert "VALIDATION ERROR" in prompts[1]
    assert "unsupported patch operation" in prompts[1]


def test_incomplete_multifile_patch_is_repaired_with_missing_path_feedback(tmp_path, monkeypatch):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("ONE = False\n", encoding="utf-8")
    second.write_text("TWO = False\n", encoding="utf-8")
    plan = ChangePlan(
        task_id=uuid4(),
        title="Enable both flags",
        summary="Update two simple files.",
        changes=[
            ProposedFileChange(relative_path="first.py", change_type=ChangeType.MODIFY, old_content="ONE = False\n", new_content="ONE = True\n", summary="Enable first flag.", reason="Requested."),
            ProposedFileChange(relative_path="second.py", change_type=ChangeType.MODIFY, old_content="TWO = False\n", new_content="TWO = True\n", summary="Enable second flag.", reason="Requested."),
        ],
    )
    responses = [
        {"operations": [{"operation": "replace_text", "path": "first.py", "search_text": "ONE = False", "replacement_text": "ONE = True"}]},
        {"operations": [
            {"operation": "replace_text", "path": "first.py", "search_text": "ONE = False", "replacement_text": "ONE = True"},
            {"operation": "replace_text", "path": "second.py", "search_text": "TWO = False", "replacement_text": "TWO = True"},
        ]},
    ]
    prompts = []
    def fake_request(prompt, **_kwargs):
        prompts.append(prompt)
        return responses.pop(0)
    monkeypatch.setattr(patch_generation, "_request_structured_patch", fake_request)
    service = _PatchServiceStub(tmp_path)
    patch = patch_generation.generate_patch(service, task=_Task("Enable both flags"), analysis=None, plan=plan, ollama_service=SimpleNamespace(model="test-coder"), repository_root=tmp_path)
    assert {op.path for op in patch.operations} == {"first.py", "second.py"}
    assert len(prompts) == 2
    assert "required planned files are missing: second.py" in prompts[1]
    assert "REQUIRED PATHS" in prompts[0]


def test_repeatedly_malformed_patch_fails_after_one_repair(tmp_path, monkeypatch):
    service = _PatchServiceStub(tmp_path)
    responses = [
        {"operations": [{"operation": "nonsense", "path": "missing.txt"}]},
        {"operations": []},
    ]

    monkeypatch.setattr(
        patch_generation,
        "_request_structured_patch",
        lambda prompt, **_kwargs: responses.pop(0),
    )

    with pytest.raises(patch_generation.AIPatchGenerationError):
        patch_generation.generate_patch(
            service,
            task=_Task(instruction="create a file"),
            analysis=None,
            plan=_Plan("missing.txt"),
            ollama_service=SimpleNamespace(model="test-coder"),
            repository_root=tmp_path,
            cancellation_token=None,
        )

def test_absolute_path_inside_repository_is_coerced_and_allowed(tmp_path: Path) -> None:
    raw_path = str(tmp_path / "new.md")

    request = _to_patch_request(
        {
            "operations": [
                {
                    "operation": "create",
                    "path": raw_path,
                    "content": "# created",
                }
            ]
        },
        allowed_paths=frozenset({"new.md"}),
        root=tmp_path,
        hashes={},
        allow_file_creation=True,
    )

    assert [operation.path for operation in request.operations] == ["new.md"]


def test_absolute_path_outside_repository_is_still_refused(tmp_path: Path) -> None:
    outside = tmp_path.parent / ("outside-" + uuid4().hex + ".md")

    with pytest.raises(AIPatchGenerationError, match="unsupported patch operation or path"):
        _to_patch_request(
            {
                "operations": [
                    {
                        "operation": "create",
                        "path": str(outside),
                        "content": "# nope",
                    }
                ]
            },
            allowed_paths=frozenset({"new.md"}),
            root=tmp_path,
            hashes={},
            allow_file_creation=True,
        )


def test_posix_root_relative_path_is_coerced(tmp_path: Path) -> None:
    request = _to_patch_request(
        {
            "operations": [
                {
                    "operation": "create",
                    "path": "/new.md",
                    "content": "# created",
                }
            ]
        },
        allowed_paths=frozenset({"new.md"}),
        root=tmp_path,
        hashes={},
        allow_file_creation=True,
    )

    assert [operation.path for operation in request.operations] == ["new.md"]


def test_coerced_absolute_path_still_requires_approved_plan(tmp_path: Path) -> None:
    stray = tmp_path / "stray.md"

    with pytest.raises(AIPatchGenerationError, match="outside the approved plan"):
        _to_patch_request(
            {
                "operations": [
                    {
                        "operation": "create",
                        "path": str(stray),
                        "content": "# nope",
                    }
                ]
            },
            allowed_paths=frozenset({"allowed.py"}),
            root=tmp_path,
            hashes={},
            allow_file_creation=True,
        )




def test_write_file_alias_creates_missing_approved_file(tmp_path: Path) -> None:
    request = _to_patch_request(
        {
            "operations": [
                {
                    "operation": "write_file",
                    "path": "hello_lumina.py",
                    "content": "def greet(name):\n    return f\"Hello, {name}!\"\n",
                }
            ]
        },
        allowed_paths=frozenset({"hello_lumina.py"}),
        root=tmp_path,
        hashes={},
        allow_file_creation=True,
    )
    assert request.operations[0].operation == "create"
    assert request.operations[0].path == "hello_lumina.py"


def test_write_file_alias_replaces_existing_approved_file(tmp_path: Path) -> None:
    target = tmp_path / "existing.py"
    target.write_text("OLD = True\n", encoding="utf-8")
    request = _to_patch_request(
        {
            "operations": [
                {
                    "operation": "WRITE-FILE",
                    "path": "existing.py",
                    "content": "OLD = False\n",
                }
            ]
        },
        allowed_paths=frozenset({"existing.py"}),
        root=tmp_path,
        hashes={},
        allow_file_creation=True,
    )
    assert request.operations[0].operation == "replace_file"
    assert request.operations[0].expected_sha256 is not None


def test_unsupported_operation_error_reports_operation_and_approved_path(tmp_path: Path) -> None:
    with pytest.raises(AIPatchGenerationError) as exc_info:
        _to_patch_request(
            {"operations": [{"operation": "invent_magic", "path": "safe.py", "content": "x = 1\n"}]},
            allowed_paths=frozenset({"safe.py"}),
            root=tmp_path,
            hashes={},
            allow_file_creation=True,
        )
    message = str(exc_info.value)
    assert "invent_magic" in message
    assert "safe.py" in message
