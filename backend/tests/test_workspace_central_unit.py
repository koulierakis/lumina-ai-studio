from __future__ import annotations

import asyncio
import time

import pytest
import server
from persistence import PersistenceCursor


@pytest.mark.anyio
async def test_workspace_overview_isolates_a_failed_subsystem(monkeypatch):
    async def broken_jobs(_owner):
        raise RuntimeError("offline")

    monkeypatch.setattr(server, "_central_jobs", broken_jobs)
    overview = await server.workspace_overview("owner@example.com")
    assert overview["jobs"] == []
    assert "jobs" in overview["panel_errors"]
    assert "readiness" in overview


def test_project_model_carries_central_metadata():
    project = server.Project(owner_email="owner@example.com", name="Launch", tags=["client"], status="active", export_media_ids=["media-1"])
    assert project.tags == ["client"]
    assert project.export_media_ids == ["media-1"]


@pytest.mark.anyio
async def test_recent_rows_keeps_event_loop_responsive():
    class SlowCollection:
        def find(self, query, projection):
            time.sleep(0.15)
            return PersistenceCursor([{"id": "one", "owner_email": query["owner_email"], "created_at": "2026-01-01"}])

    task = asyncio.create_task(server._recent_rows(SlowCollection(), "owner@example.com", "created_at", 1))
    await asyncio.sleep(0.01)
    assert not task.done()
    assert [row["id"] for row in await task] == ["one"]
