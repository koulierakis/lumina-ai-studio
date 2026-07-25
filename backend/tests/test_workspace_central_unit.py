from __future__ import annotations

import pytest
import server


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
