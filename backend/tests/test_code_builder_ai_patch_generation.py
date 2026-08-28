from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from code_builder.patch_generation_service import (
    AIPatchGenerationError,
    _to_patch_request,
    generate_patch,
    install_ai_patch_generation,
)
from code_builder.patch_service import PatchService


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
