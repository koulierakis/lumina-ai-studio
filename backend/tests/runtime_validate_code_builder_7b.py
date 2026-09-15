from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from code_builder.models import RepositoryConfiguration
from code_builder.ollama_service import OllamaClientConfiguration, OllamaService
from code_builder.planning_service import (
    GeneratedChangePlan,
    PlanningConfiguration,
    PlanningService,
)
from code_builder.repository_service import RepositoryService
from code_builder.task_service import TaskRequest

TASK_INSTRUCTION = (
    "Add a small backend health-check test without changing public APIs."
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _extract_balanced_json(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    start = stripped.find("{")
    if start < 0:
        return stripped

    in_string = False
    escaped = False
    depth = 0
    for index, character in enumerate(stripped[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return stripped[start:index + 1]
    return stripped


def _validation_details(error: ValidationError) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for item in error.errors():
        location = item.get("loc", ())
        if isinstance(location, tuple):
            path = ".".join(str(part) for part in location)
        else:
            path = str(location)
        value = item.get("input", None)
        details.append(
            {
                "path": path or "<root>",
                "expected": item.get("type"),
                "message": item.get("msg"),
                "actual_type": type(value).__name__,
            }
        )
    return details


async def _stream_generate(
    *,
    base_url: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    started = time.monotonic()
    first_chunk_seconds: float | None = None
    first_content_seconds: float | None = None
    content_parts: list[str] = []
    final_payload: dict[str, Any] | None = None
    stream_chunk_count = 0
    error_type: str | None = None
    error_detail: str | None = None

    timeout = httpx.Timeout(
        connect=5.0,
        read=timeout_seconds,
        write=30.0,
        pool=10.0,
    )

    try:
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
        ) as client, client.stream(
            "POST",
            "/api/generate",
            json=payload,
        ) as response:
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                error_type = type(exc).__name__
                error_detail = (await response.aread()).decode(
                    "utf-8",
                    errors="replace",
                )[:2_000]
                raise
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                now = time.monotonic()
                stream_chunk_count += 1
                if first_chunk_seconds is None:
                    first_chunk_seconds = now - started
                event = json.loads(line)
                text = event.get("response")
                if isinstance(text, str) and text:
                    content_parts.append(text)
                    if first_content_seconds is None:
                        first_content_seconds = now - started
                if event.get("done") is True:
                    final_payload = event
                    break
    except httpx.TimeoutException:
        error_type = "timeout"
    except httpx.HTTPError as exc:
        error_type = type(exc).__name__
        if error_detail is None:
            error_detail = str(exc)
    except json.JSONDecodeError:
        error_type = "jsonl_decode_error"

    elapsed = time.monotonic() - started
    content = "".join(content_parts)

    prompt_eval_count = None
    prompt_eval_duration = None
    eval_count = None
    eval_duration = None
    total_duration = None
    load_duration = None
    done_reason = None
    if final_payload is not None:
        prompt_eval_count = final_payload.get("prompt_eval_count")
        prompt_eval_duration = final_payload.get("prompt_eval_duration")
        eval_count = final_payload.get("eval_count")
        eval_duration = final_payload.get("eval_duration")
        total_duration = final_payload.get("total_duration")
        load_duration = final_payload.get("load_duration")
        done_reason = final_payload.get("done_reason")

    tokens_per_second = None
    if isinstance(eval_count, int) and isinstance(eval_duration, int):
        if eval_duration > 0:
            tokens_per_second = eval_count / (eval_duration / 1_000_000_000)

    return {
        "elapsed_seconds": elapsed,
        "first_response_chunk_time_seconds": first_chunk_seconds,
        "first_content_token_time_seconds": first_content_seconds,
        "output": content,
        "output_characters": len(content),
        "prompt_eval_count": prompt_eval_count,
        "prompt_eval_duration_nanoseconds": prompt_eval_duration,
        "eval_count": eval_count,
        "eval_duration_nanoseconds": eval_duration,
        "total_duration_nanoseconds": total_duration,
        "load_duration_nanoseconds": load_duration,
        "tokens_per_second": tokens_per_second,
        "done_reason": done_reason,
        "completion_status": (
            "completed" if final_payload is not None else "incomplete"
        ),
        "timeout_or_error_type": error_type,
        "timeout_or_error_detail": error_detail,
        "stream_chunk_count": stream_chunk_count,
    }


async def main() -> None:
    started_total = time.monotonic()
    client_configuration = OllamaClientConfiguration()
    task = TaskRequest(
        instruction=TASK_INSTRUCTION,
        dry_run=True,
        backup_policy="disabled",
        build_policy="disabled",
    )

    analysis_started = time.monotonic()
    analysis = RepositoryService(
        RepositoryConfiguration(repository_root=str(REPOSITORY_ROOT))
    ).analyze_repository()
    analysis_duration = time.monotonic() - analysis_started

    service = PlanningService(
        ollama_service=OllamaService(),
        configuration=PlanningConfiguration(
            model="qwen2.5-coder:7b",
            context_window=4_096,
            maximum_output_tokens=2_048,
            temperature=0.1,
            top_p=0.9,
            maximum_context_input_tokens=2_500,
            input_token_safety_margin=0,
        ),
    )

    context_started = time.monotonic()
    package = service.build_prompt_package(
        user_request=task.instruction,
        analysis=analysis,
    )
    context_generation_duration = time.monotonic() - context_started

    prompt_text = package["system_prompt"] + package["user_prompt"]
    base_payload = {
        "model": package["model"],
        "prompt": package["user_prompt"],
        "system": package["system_prompt"],
        "stream": True,
        "format": "json",
        "options": package["options"],
    }

    repair_attempt_count = 0
    validation_errors: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    parsed_data: Any = None
    validated_plan: GeneratedChangePlan | None = None
    final_json_status = "not_attempted"
    final_validation_status = "not_attempted"

    for attempt_index in range(2):
        payload = dict(base_payload)
        if attempt_index > 0:
            repair_attempt_count += 1
            repair_instruction = service._build_repair_instruction(  # noqa: SLF001
                error=ValidationError.from_exception_data(
                    GeneratedChangePlan.__name__,
                    [
                        {
                            "type": "value_error",
                            "loc": (item["path"],),
                            "msg": item["message"] or "validation failed",
                            "input": item["actual_type"],
                            "ctx": {"error": ValueError(item["message"] or "validation failed")},
                        }
                        for item in validation_errors[:20]
                    ],
                )
            )
            payload["prompt"] = (
                f"{package['user_prompt'].rstrip()}\n\n"
                "PLAN REPAIR REQUIREMENTS\n"
                "========================\n"
                f"{repair_instruction}"
            )

        planning_started = time.monotonic()
        measurement = await _stream_generate(
            base_url=client_configuration.base_url,
            payload=payload,
            timeout_seconds=600.0,
        )
        planning_duration = time.monotonic() - planning_started
        attempt_record = {
            "attempt": attempt_index + 1,
            "planning_duration_seconds": planning_duration,
            **{key: value for key, value in measurement.items() if key != "output"},
        }

        extracted = _extract_balanced_json(measurement["output"])
        try:
            parsed_data = json.loads(extracted)
            final_json_status = "valid"
            attempt_record["json_parse_status"] = "valid"
        except json.JSONDecodeError as exc:
            final_json_status = "invalid"
            final_validation_status = "not_attempted"
            validation_errors = [
                {
                    "path": "<json>",
                    "expected": "valid_json_object",
                    "message": str(exc),
                    "actual_type": "str",
                }
            ]
            attempt_record["json_parse_status"] = "invalid"
            attempt_record["schema_validation_status"] = "not_attempted"
            attempt_record["validation_errors"] = validation_errors
            attempts.append(attempt_record)
            continue

        try:
            validated_plan = GeneratedChangePlan.model_validate(parsed_data)
            final_validation_status = "valid"
            validation_errors = []
            attempt_record["schema_validation_status"] = "valid"
            attempts.append(attempt_record)
            break
        except ValidationError as exc:
            final_validation_status = "invalid"
            validation_errors = _validation_details(exc)
            attempt_record["schema_validation_status"] = "invalid"
            attempt_record["validation_errors"] = validation_errors
            attempts.append(attempt_record)

    final_status = "awaiting_approval" if validated_plan else "failed"
    last_attempt = attempts[-1] if attempts else {}
    output = {
        "measured_at": _utc_now(),
        "task_instruction": task.instruction,
        "task_id": task.task_id,
        "configuration": {
            "model": "qwen2.5-coder:7b",
            "num_ctx": 4_096,
            "num_predict": 2_048,
            "temperature": 0.1,
            "top_p": 0.9,
        },
        "analysis_duration_seconds": analysis_duration,
        "context_generation_duration_seconds": context_generation_duration,
        "planning_duration_seconds": last_attempt.get(
            "planning_duration_seconds"
        ),
        "total_task_duration_seconds": time.monotonic() - started_total,
        "prompt_characters": len(prompt_text),
        "estimated_input_tokens": _estimate_tokens(prompt_text),
        "selected_file_count": len(package["context"].get("selected_files", [])),
        "output_characters": last_attempt.get("output_characters"),
        "generated_output_token_count": last_attempt.get("eval_count"),
        "ollama_prompt_eval_count": last_attempt.get("prompt_eval_count"),
        "prompt_eval_duration_nanoseconds": last_attempt.get(
            "prompt_eval_duration_nanoseconds"
        ),
        "eval_count": last_attempt.get("eval_count"),
        "eval_duration_nanoseconds": last_attempt.get(
            "eval_duration_nanoseconds"
        ),
        "tokens_per_second": last_attempt.get("tokens_per_second"),
        "done_reason": last_attempt.get("done_reason"),
        "json_parsing_result": final_json_status,
        "schema_validation_result": final_validation_status,
        "repair_attempt_count": repair_attempt_count,
        "final_task_status": final_status,
        "attempts": attempts,
        "validated_plan_title": validated_plan.title if validated_plan else None,
    }
    output_path = BACKEND_ROOT / "tests" / "runtime_code_builder_7b_results.json"
    output_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(json.dumps(output, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    asyncio.run(main())
