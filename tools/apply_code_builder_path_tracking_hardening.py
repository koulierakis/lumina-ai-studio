from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK_SERVICE = ROOT / "backend" / "code_builder" / "task_service.py"


def main() -> None:
    text = TASK_SERVICE.read_text(encoding="utf-8")
    marker = '"destination_path",\n                    "new_path",'
    if marker in text:
        print("CODE BUILDER PATH TRACKING HARDENING ALREADY APPLIED")
        return

    old = '''            nested_path = _extract_value(\n                item,\n                (\n                    "path",\n                    "file_path",\n                    "relative_path",\n                    "target_path",\n                ),\n            )\n\n            if nested_path is not None:\n                paths.append(str(nested_path))'''
    new = '''            nested_path = _extract_value(\n                item,\n                (\n                    "path",\n                    "file_path",\n                    "relative_path",\n                    "target_path",\n                ),\n            )\n            destination_path = _extract_value(\n                item,\n                (\n                    "destination_path",\n                    "new_path",\n                    "destination",\n                ),\n            )\n\n            if nested_path is not None:\n                paths.append(str(nested_path))\n            if destination_path is not None:\n                paths.append(str(destination_path))'''

    if old not in text:
        raise RuntimeError("Could not find Code Builder path extraction anchor")
    text = text.replace(old, new, 1)
    TASK_SERVICE.write_text(text, encoding="utf-8")
    print("CODE BUILDER PATH TRACKING HARDENING APPLIED")


if __name__ == "__main__":
    main()
