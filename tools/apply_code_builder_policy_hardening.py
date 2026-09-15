from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK_SERVICE = ROOT / "backend" / "code_builder" / "task_service.py"


def main() -> None:
    text = TASK_SERVICE.read_text(encoding="utf-8")
    marker = "Metadata patch operations honor task create/delete/exclusion policy."
    if marker in text:
        print("CODE BUILDER PATCH POLICY HARDENING ALREADY APPLIED")
        return

    anchor = '''    planned_paths = _extract_plan_operation_paths(context.plan)\n\n    if planned_paths:\n        operation_paths = frozenset(_extract_paths(payload))'''
    replacement = '''    # Metadata patch operations honor task create/delete/exclusion policy.\n    create_operations = {"create", "add", "new", "create_file"}\n    delete_operations = {"delete", "remove", "delete_file"}\n    rename_operations = {"rename", "move", "rename_file"}\n\n    for operation in payload.operations:\n        operation_name = str(operation.operation).strip().casefold().replace("-", "_").replace(" ", "_")\n        if (\n            operation_name in create_operations\n            or bool(operation.create_if_missing)\n        ) and not context.request.allow_file_creation:\n            raise TaskPatchError(\n                "Patch requests file creation, but this task does not permit creating files."\n            )\n        if operation_name in delete_operations and not context.request.allow_file_deletion:\n            raise TaskPatchError(\n                "Patch requests file deletion, but this task does not permit deleting files."\n            )\n        if operation_name in rename_operations and (\n            not context.request.allow_file_creation\n            or not context.request.allow_file_deletion\n        ):\n            raise TaskPatchError(\n                "Patch requests a rename/move, which requires both file creation and deletion permission."\n            )\n\n    repository_root = context.configuration.repository_root\n    excluded_roots = tuple(\n        _normalize_repository_path(\n            repository_root,\n            excluded_path,\n            must_exist=False,\n        )\n        for excluded_path in context.request.excluded_paths\n    )\n    for operation in payload.operations:\n        candidate_paths = [operation.path]\n        if operation.destination_path:\n            candidate_paths.append(operation.destination_path)\n        for path_text in candidate_paths:\n            resolved = _normalize_repository_path(\n                repository_root,\n                path_text,\n                must_exist=False,\n            )\n            if any(\n                resolved == excluded_root or excluded_root in resolved.parents\n                for excluded_root in excluded_roots\n            ):\n                raise TaskPatchError(\n                    f"Patch targets an excluded path: {path_text}"\n                )\n\n    planned_paths = _extract_plan_operation_paths(context.plan)\n\n    if planned_paths:\n        operation_paths = frozenset(_extract_paths(payload))'''

    if anchor not in text:
        raise RuntimeError("Could not find metadata patch policy anchor")
    text = text.replace(anchor, replacement, 1)
    TASK_SERVICE.write_text(text, encoding="utf-8")
    print("CODE BUILDER PATCH POLICY HARDENING APPLIED")


if __name__ == "__main__":
    main()
