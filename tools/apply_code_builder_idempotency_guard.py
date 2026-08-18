from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "backend" / "code_builder" / "router.py"


def main() -> None:
    text = ROUTER.read_text(encoding="utf-8")
    marker = "idempotency_key_conflict"
    if marker in text:
        print("CODE BUILDER IDEMPOTENCY GUARD ALREADY APPLIED")
        return

    anchor = '''    is_existing_idempotent_task = (\n        created_task is not stored_task\n    )\n\n    if not is_existing_idempotent_task:'''
    replacement = '''    is_existing_idempotent_task = (\n        created_task is not stored_task\n    )\n\n    if is_existing_idempotent_task:\n        existing_payload = created_task.api_request.model_dump(mode="json")\n        incoming_payload = payload.model_dump(mode="json")\n        if existing_payload != incoming_payload:\n            raise HTTPException(\n                status_code=status.HTTP_409_CONFLICT,\n                detail={\n                    "error": "idempotency_key_conflict",\n                    "message": (\n                        "This Idempotency-Key is already bound to a different "\n                        "Code Builder request."\n                    ),\n                    "task_id": created_task.request.task_id,\n                },\n            )\n\n    if not is_existing_idempotent_task:'''

    if anchor not in text:
        raise RuntimeError("Could not find Code Builder idempotency anchor")
    text = text.replace(anchor, replacement, 1)
    ROUTER.write_text(text, encoding="utf-8")
    print("CODE BUILDER IDEMPOTENCY GUARD APPLIED")


if __name__ == "__main__":
    main()
