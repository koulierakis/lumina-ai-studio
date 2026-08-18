from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "backend" / "code_builder" / "router.py"


def main() -> None:
    text = ROUTER.read_text(encoding="utf-8")
    marker = "def _lock_prepared_operations_to_validation("

    if marker not in text:
        anchor = "def _bind_prepared_patch_to_request(stored_task: StoredTask) -> TaskRequest:\n"
        helper = '''def _lock_prepared_operations_to_validation(\n    prepared: Mapping[str, Any],\n    raw_operations: Sequence[Any],\n) -> list[Any]:\n    validation = prepared.get("patch_validation")\n    validation_results = (\n        validation.get("results")\n        if isinstance(validation, Mapping)\n        else None\n    )\n    results = (\n        list(validation_results)\n        if isinstance(validation_results, Sequence)\n        and not isinstance(validation_results, (str, bytes, bytearray))\n        else []\n    )\n\n    by_operation_id: dict[str, Mapping[str, Any]] = {}\n    for result in results:\n        if not isinstance(result, Mapping):\n            continue\n        operation_id = result.get("operation_id")\n        if operation_id is not None:\n            by_operation_id[str(operation_id)] = result\n\n    locked: list[Any] = []\n    for index, raw_operation in enumerate(raw_operations):\n        if not isinstance(raw_operation, Mapping):\n            locked.append(raw_operation)\n            continue\n\n        operation = dict(raw_operation)\n        if operation.get("expected_sha256"):\n            locked.append(operation)\n            continue\n\n        validation_result: Mapping[str, Any] | None = None\n        operation_id = operation.get("operation_id")\n        if operation_id is not None:\n            validation_result = by_operation_id.get(str(operation_id))\n\n        if validation_result is None and index < len(results):\n            candidate = results[index]\n            if isinstance(candidate, Mapping):\n                operation_path = str(operation.get("path") or "")\n                result_path = str(candidate.get("path") or candidate.get("relative_path") or "")\n                if not operation_path or operation_path == result_path:\n                    validation_result = candidate\n\n        if validation_result is not None:\n            original_sha256 = validation_result.get("original_sha256")\n            if original_sha256:\n                operation["expected_sha256"] = str(original_sha256)\n\n        locked.append(operation)\n\n    return locked\n\n\n'''
        if anchor not in text:
            raise RuntimeError("Could not find prepared patch binding anchor")
        text = text.replace(anchor, helper + anchor, 1)

    old = '''    metadata["approved_patch_operations"] = list(raw_operations)\n    metadata["approved_preparation_plan"] = prepared.get("plan")'''
    new = '''    metadata["approved_patch_operations"] = _lock_prepared_operations_to_validation(\n        prepared,\n        raw_operations,\n    )\n    metadata["approved_preparation_plan"] = prepared.get("plan")'''
    if new not in text:
        if old not in text:
            raise RuntimeError("Could not find approved patch operation binding")
        text = text.replace(old, new, 1)

    ROUTER.write_text(text, encoding="utf-8")
    print("CODE BUILDER STALE-FILE GUARD APPLIED")


if __name__ == "__main__":
    main()
