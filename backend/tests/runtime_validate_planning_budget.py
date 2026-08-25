from __future__ import annotations

import argparse
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
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from code_builder.models import RepositoryConfiguration
from code_builder.ollama_service import (
    OllamaClientConfiguration,
    OllamaService,
)
from code_builder.planning_service import (
    GeneratedChangePlan,
    PlanningConfiguration,
    PlanningService,
)
from code_builder.repository_service import RepositoryService

PLANNING_TASK = (
    "Add a small backend Code Builder enhancement that improves planning "
    "runtime diagnostics without changing public API behavior. Update the "
    "planning service and focused tests only, preserving compact semantic "
    "context, relevance scoring, dependency expansion, deterministic ordering, "
    "and GeneratedChangePlan validation."
)

CONFIGURATIONS = [
    {
        "name": "Test A",
        "num_ctx": 16_384,
        "num_predict": 2_048,
        "maximum_context_input_tokens": 6_000,
    },
    {
        "name": "Test B",
        "num_ctx": 16_384,
        "num_predict": 4_096,
        "maximum_context_input_tokens": 6_000,
    },
    {
        "name": "Test C",
        "num_ctx": 8_192,
        "num_predict": 2_048,
        "maximum_context_input_tokens": 3_500,
    },
]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


async def _stream_ollama(
    *,
    base_url: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    request_start = _utc_now()
    started = time.monotonic()
    first_chunk_seconds: float | None = None
    first_content_seconds: float | None = None
    chunks = 0
    content_parts: list[str] = []
    final_payload: dict[str, Any] | None = None
    error_type: str | None = None

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
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                now = time.monotonic()
                chunks += 1
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
    except json.JSONDecodeError:
        error_type = "jsonl_decode_error"

    elapsed = time.monotonic() - started
    content = "".join(content_parts)
    prompt_eval_count = None
    prompt_eval_duration = None
    eval_count = None
    eval_duration = None
    total_duration = None
    done_reason = None

    if final_payload is not None:
        prompt_eval_count = final_payload.get("prompt_eval_count")
        prompt_eval_duration = final_payload.get("prompt_eval_duration")
        eval_count = final_payload.get("eval_count")
        eval_duration = final_payload.get("eval_duration")
        total_duration = final_payload.get("total_duration")
        done_reason = final_payload.get("done_reason")

    tokens_per_second = None
    if isinstance(eval_count, int) and isinstance(eval_duration, int):
        if eval_duration > 0:
            tokens_per_second = eval_count / (eval_duration / 1_000_000_000)

    parsed_json = None
    json_parse_status = "not_attempted"
    validation_status = "not_attempted"
    if content:
        try:
            parsed_json = json.loads(content)
            json_parse_status = "valid"
        except json.JSONDecodeError:
            json_parse_status = "invalid"
    if parsed_json is not None:
        try:
            GeneratedChangePlan.model_validate(parsed_json)
            validation_status = "valid"
        except ValidationError:
            validation_status = "invalid"

    return {
        "request_start_time": request_start,
        "first_response_chunk_time_seconds": first_chunk_seconds,
        "first_content_token_time_seconds": first_content_seconds,
        "prompt_eval_count": prompt_eval_count,
        "prompt_eval_duration_nanoseconds": prompt_eval_duration,
        "eval_count": eval_count,
        "eval_duration_nanoseconds": eval_duration,
        "tokens_per_second": tokens_per_second,
        "total_duration_nanoseconds": total_duration,
        "elapsed_seconds": elapsed,
        "done_reason": done_reason,
        "completion_status": (
            "completed" if final_payload is not None else "incomplete"
        ),
        "json_parse_status": json_parse_status,
        "generated_change_plan_validation_status": validation_status,
        "timeout_or_error_type": error_type,
        "stream_chunk_count": chunks,
        "response_characters": len(content),
    }


def _build_package(
    *,
    analysis: Any,
    config: dict[str, Any],
) -> dict[str, Any]:
    service = PlanningService(
        ollama_service=OllamaService(
            configuration=OllamaClientConfiguration()
        ),
        configuration=PlanningConfiguration(
            context_window=config["num_ctx"],
            maximum_output_tokens=config["num_predict"],
            maximum_context_input_tokens=(
                config["maximum_context_input_tokens"]
            ),
        ),
    )
    return service.build_prompt_package(
        user_request=PLANNING_TASK,
        analysis=analysis,
    )


async def _run_sanity(
    *,
    base_url: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    payload = {
        "model": "qwen2.5-coder:7b",
        "prompt": "Return exactly this JSON: {\"ok\": true}",
        "stream": True,
        "format": "json",
        "options": {
            "temperature": 0,
            "num_ctx": 2_048,
            "num_predict": 64,
        },
    }
    return await _stream_ollama(
        base_url=base_url,
        payload=payload,
        timeout_seconds=timeout_seconds,
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument(
        "--output",
        default="backend/tests/runtime_planning_budget_results.json",
    )
    args = parser.parse_args()

    client_config = OllamaClientConfiguration()
    repository_config = RepositoryConfiguration(
        repository_root=str(Path.cwd().parent),
    )
    analysis = RepositoryService(repository_config).analyze_repository()

    results: list[dict[str, Any]] = []
    for config in CONFIGURATIONS:
        package = _build_package(analysis=analysis, config=config)
        repository_context = json.dumps(
            package["context"],
            ensure_ascii=False,
            sort_keys=False,
            default=str,
        )
        prompt = package["user_prompt"]
        payload = {
            "model": package["model"],
            "prompt": prompt,
            "system": package["system_prompt"],
            "stream": True,
            "format": package["output_schema"],
            "options": package["options"],
        }

        measurement = await _stream_ollama(
            base_url=client_config.base_url,
            payload=payload,
            timeout_seconds=args.timeout,
        )
        results.append(
            {
                "configuration": config,
                "prompt_characters": (
                    len(package["system_prompt"]) + len(prompt)
                ),
                "estimated_input_tokens": _estimate_tokens(
                    package["system_prompt"] + prompt
                ),
                "selected_file_count": len(
                    package["context"].get("selected_files", [])
                ),
                "repository_context_characters": len(repository_context),
                "context_metadata": package["context"].get(
                    "context_metadata",
                    {},
                ),
                **measurement,
            }
        )

    if all(item["stream_chunk_count"] == 0 for item in results):
        sanity = await _run_sanity(
            base_url=client_config.base_url,
            timeout_seconds=args.timeout,
        )
    else:
        sanity = None

    output = {
        "measured_at": _utc_now(),
        "planning_task": PLANNING_TASK,
        "results": results,
        "sanity": sanity,
    }
    Path(args.output).write_text(
        json.dumps(output, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(json.dumps(output, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    asyncio.run(main())
