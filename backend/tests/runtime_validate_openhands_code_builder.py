"""Real OpenHands runtime validation for LUMINA Code Builder.

This is intentionally not a normal unit test. Run it manually on a machine where
OpenHands and its model/provider are configured. It uses a temporary repository
and must never modify the real LUMINA repository.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from code_builder.openhands_preparation_service import OpenHandsPreparationService


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="lumina-openhands-runtime-") as temp_dir:
        repo = Path(temp_dir)
        source = repo / "hello.py"
        source.write_text("def message():\n    return 'old'\n", encoding="utf-8")
        original = source.read_text(encoding="utf-8")

        instruction = (
            "In hello.py only, change message() so it returns 'new'. "
            "Do not create, delete, or modify any other file."
        )

        try:
            payload = OpenHandsPreparationService().prepare(
                task_id="runtime-openhands-validation",
                repository_root=repo,
                instruction=instruction,
            )
        except Exception as exc:
            report = {
                "ready": False,
                "stage": "openhands_runtime",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 1

        source_unchanged = source.read_text(encoding="utf-8") == original
        operations = payload.get("patch", {}).get("operations", [])
        changed_paths = payload.get("changed_paths", [])
        expected_path_only = changed_paths == ["hello.py"]
        has_patch = bool(operations)

        ready = bool(
            payload.get("success")
            and payload.get("source_repository_unchanged")
            and source_unchanged
            and expected_path_only
            and has_patch
        )

        report = {
            "ready": ready,
            "stage": "complete" if ready else "validation",
            "engine": payload.get("engine"),
            "source_repository_unchanged": source_unchanged,
            "changed_paths": changed_paths,
            "patch_operations": len(operations),
            "status": payload.get("status"),
        }
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
