from __future__ import annotations

from pathlib import Path

import pytest

from code_builder.patch_generation_service import (
    AIPatchGenerationError,
    _to_patch_request,
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
