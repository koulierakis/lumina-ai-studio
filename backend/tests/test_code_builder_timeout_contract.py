from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from code_builder.task_service import TaskTimeoutError, _run_awaitable_sync


async def _raise_asyncio_timeout() -> None:
    raise asyncio.TimeoutError("simulated timeout")


async def _return_value() -> str:
    await asyncio.sleep(0)
    return "ok"


def test_async_timeout_is_reported_as_code_builder_timeout() -> None:
    with pytest.raises(TaskTimeoutError) as captured:
        _run_awaitable_sync(
            _raise_asyncio_timeout(),
            timeout_seconds=2.5,
            operation_name="Planning",
        )

    assert captured.value.timeout_seconds == 2.5
    assert "Planning timed out" in str(captured.value)


def test_planning_awaitable_runs_from_worker_thread_without_event_loop() -> None:
    def worker() -> str:
        return _run_awaitable_sync(
            _return_value(),
            timeout_seconds=2.5,
            operation_name="Implementation planning",
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(worker).result(timeout=5.0)

    assert result == "ok"


def test_planning_awaitable_runs_when_caller_already_has_event_loop() -> None:
    async def caller() -> str:
        return _run_awaitable_sync(
            _return_value(),
            timeout_seconds=2.5,
            operation_name="Implementation planning",
        )

    assert asyncio.run(caller()) == "ok"
