from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "backend" / "code_builder" / "router.py"


def main() -> None:
    text = ROUTER.read_text(encoding="utf-8")
    marker = "def _validate_review_allows_approval("

    if marker not in text:
        route_anchor = '''@router.post(\n    "/tasks/{task_id}/approve",'''
        helper = '''def _validate_review_allows_approval(\n    review_result: Any,\n    *,\n    task_id: str,\n) -> None:\n    serialized_review = _serialize_value(review_result)\n    if not isinstance(serialized_review, Mapping):\n        raise HTTPException(\n            status_code=status.HTTP_409_CONFLICT,\n            detail={\n                "error": "ai_review_unavailable",\n                "message": "Independent AI review must complete before approval.",\n                "task_id": task_id,\n            },\n        )\n\n    review_status = str(serialized_review.get("status") or "").strip().casefold()\n    verdict = str(serialized_review.get("verdict") or "").strip().casefold()\n\n    if review_status != "completed" or verdict not in {"pass", "warn", "block"}:\n        raise HTTPException(\n            status_code=status.HTTP_409_CONFLICT,\n            detail={\n                "error": "ai_review_unavailable",\n                "message": "Independent AI review must complete successfully before approval.",\n                "task_id": task_id,\n            },\n        )\n\n    if verdict == "block":\n        raise HTTPException(\n            status_code=status.HTTP_409_CONFLICT,\n            detail={\n                "error": "ai_review_blocked",\n                "message": "AI review blocked this prepared change. Revise the task before approval.",\n                "task_id": task_id,\n            },\n        )\n\n\n'''
        if route_anchor not in text:
            raise RuntimeError("Could not find approval route anchor")
        text = text.replace(route_anchor, helper + route_anchor, 1)

    old = '''        serialized_review = _serialize_value(stored_task.review_result)\n        if isinstance(serialized_review, Mapping):\n            verdict = str(serialized_review.get("verdict") or "").strip().casefold()\n            if verdict == "block":\n                raise HTTPException(\n                    status_code=status.HTTP_409_CONFLICT,\n                    detail={\n                        "error": "ai_review_blocked",\n                        "message": "AI review blocked this prepared change. Revise the task before approval.",\n                        "task_id": normalized_task_id,\n                    },\n                )\n'''
    call = '''        _validate_review_allows_approval(\n            stored_task.review_result,\n            task_id=normalized_task_id,\n        )\n'''

    if old in text:
        text = text.replace(old, call, 1)
    elif call not in text:
        raise RuntimeError("Could not find existing approval review guard")

    double_call = call + "\n" + call
    while double_call in text:
        text = text.replace(double_call, call + "\n", 1)

    ROUTER.write_text(text, encoding="utf-8")
    print("CODE BUILDER REVIEW GATE APPLIED")


if __name__ == "__main__":
    main()
