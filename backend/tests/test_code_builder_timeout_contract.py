from __future__ import annotations

import asyncio

import pytest

from code_builder.task_service import TaskTimeoutError, _run_awaitable_sync


async def _raise_asyncio_timeout() -> None:
    raise asyncio.TimeoutError("simulated timeout")


def test_async_timeout_is_reported_as_code_builder_timeout() -> None:
    with pytest.raises(TaskTimeoutError) as captured:
        _run_awaitable_sync(
            _raise_asyncio_timeout(),
            timeout_seconds=2.5,
            operation_name="Planning",
        )

    assert captured.value.timeout_seconds == 2.5
    assert "Planning timed out" in str(captured.value)
