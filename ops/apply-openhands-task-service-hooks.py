from __future__ import annotations

from pathlib import Path


PATH = Path("backend/code_builder/task_service.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0:
        # Idempotent success when the new block is already present.
        if new in text:
            print(f"{label}: already applied")
            return text
        raise RuntimeError(f"{label}: expected anchor was not found")
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    print(f"{label}: applying")
    return text.replace(old, new, 1)


def main() -> None:
    text = PATH.read_text(encoding="utf-8")

    analyze_old = '''    timeout_seconds = _remaining_stage_timeout(\n        context,\n        context.configuration.analysis_timeout_seconds,\n    )\n'''
    analyze_new = '''    from . import task_service_engine_hooks as engine_hooks\n\n    if engine_hooks.should_bypass_native_analysis(context):\n        return engine_hooks.build_minimal_analysis(context)\n\n    timeout_seconds = _remaining_stage_timeout(\n        context,\n        context.configuration.analysis_timeout_seconds,\n    )\n'''
    text = replace_once(text, analyze_old, analyze_new, "analysis hook")

    plan_old = '''    timeout_seconds = _remaining_stage_timeout(\n        context,\n        context.configuration.planning_timeout_seconds,\n    )\n\n    context.raise_if_interrupted()\n'''
    plan_new = '''    from . import task_service_engine_hooks as engine_hooks\n\n    engine_plan = engine_hooks.prepare_or_reuse_plan(context)\n    if engine_plan is not None:\n        return engine_plan\n\n    timeout_seconds = _remaining_stage_timeout(\n        context,\n        context.configuration.planning_timeout_seconds,\n    )\n\n    context.raise_if_interrupted()\n'''
    text = replace_once(text, plan_old, plan_new, "planning hook")

    patch_old = '''    timeout_seconds = _remaining_stage_timeout(\n        context,\n        context.configuration.patch_timeout_seconds,\n    )\n\n    metadata_patch = _build_patch_request_from_metadata(context)\n'''
    patch_new = '''    from . import task_service_engine_hooks as engine_hooks\n\n    engine_patch = engine_hooks.prepared_patch_for_context(context)\n    if engine_patch is not None:\n        return engine_patch\n\n    timeout_seconds = _remaining_stage_timeout(\n        context,\n        context.configuration.patch_timeout_seconds,\n    )\n\n    metadata_patch = _build_patch_request_from_metadata(context)\n'''
    text = replace_once(text, patch_old, patch_new, "patch hook")

    PATH.write_text(text, encoding="utf-8")
    print("TaskService OpenHands wiring migration completed safely.")


if __name__ == "__main__":
    main()
