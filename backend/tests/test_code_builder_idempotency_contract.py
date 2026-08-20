from __future__ import annotations

import asyncio

import pytest
from fastapi import BackgroundTasks, HTTPException

from code_builder.router import TaskCreateRequest, TaskStore, create_code_builder_task
from code_builder.task_service import TaskCancellationToken


class MinimalTaskService:
    def create_cancellation_token(self, task_id: str) -> TaskCancellationToken:
        return TaskCancellationToken(task_id=task_id)


def _create(payload: TaskCreateRequest, store: TaskStore, key: str):
    return asyncio.run(
        create_code_builder_task(
            payload=payload,
            background_tasks=BackgroundTasks(),
            task_service=MinimalTaskService(),
            task_store=store,
            idempotency_key=key,
        )
    )


def test_same_idempotency_key_and_same_payload_returns_same_task() -> None:
    store = TaskStore()
    payload = TaskCreateRequest(instruction="same request")

    first = _create(payload, store, "same-key")
    second = _create(payload, store, "same-key")

    assert first.task.task_id == second.task.task_id
    assert store.count() == 1


def test_same_idempotency_key_cannot_be_reused_for_different_payload() -> None:
    store = TaskStore()
    _create(TaskCreateRequest(instruction="first request"), store, "conflict-key")

    with pytest.raises(HTTPException) as captured:
        _create(TaskCreateRequest(instruction="different request"), store, "conflict-key")

    assert captured.value.status_code == 409
    assert captured.value.detail["error"] == "idempotency_key_conflict"
    assert store.count() == 1
