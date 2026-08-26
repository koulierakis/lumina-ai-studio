from __future__ import annotations

from code_builder.task_service import _extract_paths


def test_rename_operation_tracks_source_and_destination() -> None:
    paths = _extract_paths(
        {
            "operations": [
                {
                    "operation": "rename",
                    "path": "backend/old_name.py",
                    "destination_path": "backend/new_name.py",
                }
            ]
        }
    )

    assert paths == ("backend/old_name.py", "backend/new_name.py")


def test_result_tracking_keeps_destination_path() -> None:
    paths = _extract_paths(
        {
            "results": [
                {
                    "path": "frontend/src/old.js",
                    "destination_path": "frontend/src/new.js",
                }
            ]
        }
    )

    assert paths == ("frontend/src/old.js", "frontend/src/new.js")
