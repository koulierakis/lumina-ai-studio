from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "backend" / "code_builder" / "router.py"


def main() -> None:
    text = ROUTER.read_text(encoding="utf-8")

    if "import json\n" not in text:
        text = text.replace("import enum\n", "import enum\nimport json\n", 1)

    import_anchor = '''    is_successful_task_result,\n)'''
    import_replacement = '''    is_successful_task_result,\n    _run_awaitable_sync,\n)'''
    if "    _run_awaitable_sync,\n" not in text:
        if import_anchor not in text:
            raise RuntimeError("Could not find TaskService import anchor")
        text = text.replace(import_anchor, import_replacement, 1)

    start = text.find("def _review_prepared_change(\n")
    end = text.find("\n\ndef _phase_from_result(\n", start)
    if start < 0 or end < 0:
        raise RuntimeError("Could not locate prepared-change review function")

    replacement = '''def _review_prepared_change(\n    *,\n    task_service: TaskService,\n    stored_task: StoredTask,\n    preparation_result: Any,\n) -> dict[str, Any]:\n    ollama_service = task_service.ollama_service\n    reviewer = getattr(\n        ollama_service,\n        "analyze_code_task",\n        None,\n    )\n\n    planning_service = getattr(task_service, "planning_service", None)\n    planning_configuration = getattr(planning_service, "configuration", None)\n    model = (\n        getattr(planning_configuration, "model", None)\n        or getattr(ollama_service, "model", None)\n    )\n\n    serialized_preparation = _serialize_value(preparation_result)\n    review_instruction = (\n        "Act as the independent LUMINA Code Builder reviewer. Review ONLY "\n        "the supplied prepared implementation plan, proposed patch/diff, "\n        "and patch validation. Do not generate replacement code and do not "\n        "modify files. Check scope alignment, correctness risks, unsafe or "\n        "destructive changes, missing tests, plan/patch mismatches, and "\n        "rollback concerns. Give a concise verdict using PASS, WARN, or "\n        "BLOCK as the first word, followed by concrete findings with file "\n        "paths when known."\n    )\n\n    timeout_seconds = min(\n        stored_task.request.task_timeout_seconds,\n        300.0,\n    )\n\n    try:\n        if callable(reviewer):\n            content = reviewer(\n                instruction=review_instruction,\n                repository_context=serialized_preparation,\n                user_context={\n                    "original_instruction": stored_task.request.instruction,\n                    "task_id": stored_task.request.task_id,\n                    "purpose": "pre_approval_review",\n                },\n                target_paths=stored_task.request.target_paths,\n                excluded_paths=stored_task.request.excluded_paths,\n                timeout_seconds=timeout_seconds,\n                cancellation_token=stored_task.cancellation_token,\n            )\n        else:\n            generator = getattr(ollama_service, "generate", None)\n            if not callable(generator) or not model:\n                return {\n                    "status": "unavailable",\n                    "model": str(model) if model else None,\n                    "summary": (\n                        "Independent AI review is unavailable because no "\n                        "compatible local model generation method is configured."\n                    ),\n                    "reviewed_at_epoch": time.time(),\n                }\n\n            review_payload = {\n                "original_instruction": stored_task.request.instruction,\n                "target_paths": list(stored_task.request.target_paths),\n                "excluded_paths": list(stored_task.request.excluded_paths),\n                "prepared_change": serialized_preparation,\n            }\n            prompt = json.dumps(\n                review_payload,\n                ensure_ascii=False,\n                default=str,\n            )\n            # Keep the review bounded even when the prepared diff is large.\n            prompt = prompt[:500_000]\n\n            options: dict[str, Any] = {\n                "temperature": 0.0,\n                "num_predict": 768,\n            }\n            context_window = getattr(\n                planning_configuration,\n                "context_window",\n                None,\n            )\n            if isinstance(context_window, int) and context_window > 0:\n                options["num_ctx"] = context_window\n\n            raw_response = _run_awaitable_sync(\n                generator(\n                    model=str(model),\n                    prompt=prompt,\n                    system_prompt=review_instruction,\n                    options=options,\n                    timeout_seconds=timeout_seconds,\n                    verify_model=False,\n                ),\n                timeout_seconds=timeout_seconds,\n                operation_name="Independent Code Builder review",\n            )\n            content = getattr(raw_response, "content", raw_response)\n\n    except Exception as exc:\n        logger.warning(\n            "Code Builder AI review failed for task %s: %s",\n            stored_task.request.task_id,\n            exc,\n        )\n        return {\n            "status": "unavailable",\n            "model": str(model) if model else None,\n            "summary": f"AI review failed: {exc}",\n            "reviewed_at_epoch": time.time(),\n        }\n\n    normalized = str(content).strip()\n    first_line = (\n        normalized.splitlines()[0].strip().upper()\n        if normalized\n        else ""\n    )\n    verdict = (\n        "block"\n        if first_line.startswith("BLOCK")\n        else "warn"\n        if first_line.startswith("WARN")\n        else "pass"\n        if first_line.startswith("PASS")\n        else "warn"\n    )\n    return {\n        "status": "completed",\n        "verdict": verdict,\n        "model": str(model) if model else None,\n        "summary": normalized,\n        "reviewed_at_epoch": time.time(),\n    }\n'''

    text = text[:start] + replacement + text[end:]
    ROUTER.write_text(text, encoding="utf-8")
    print("CODE BUILDER REVIEW ADAPTER APPLIED")


if __name__ == "__main__":
    main()
