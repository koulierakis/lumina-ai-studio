from pathlib import Path
import os
import pytest

from code_builder.openhands_change_capture_service import (
    OpenHandsChangeCaptureError,
    OpenHandsChangeCaptureService,
)


def test_change_capture_reports_created_modified_deleted(tmp_path: Path):
    service = OpenHandsChangeCaptureService()
    (tmp_path / "modified.py").write_text("before\n", encoding="utf-8")
    (tmp_path / "deleted.txt").write_text("remove me\n", encoding="utf-8")
    before = service.snapshot(tmp_path)

    (tmp_path / "modified.py").write_text("after\n", encoding="utf-8")
    (tmp_path / "deleted.txt").unlink()
    (tmp_path / "created.md").write_text("new\n", encoding="utf-8")
    after = service.snapshot(tmp_path)

    changes = {change.relative_path: change for change in service.compare(before, after)}
    assert changes["modified.py"].change_type == "modified"
    assert changes["modified.py"].before_text == "before\n"
    assert changes["modified.py"].after_text == "after\n"
    assert changes["deleted.txt"].change_type == "deleted"
    assert changes["created.md"].change_type == "created"


def test_change_capture_rejects_binary_change(tmp_path: Path):
    service = OpenHandsChangeCaptureService()
    target = tmp_path / "asset.bin"
    target.write_bytes(b"\x00\x01")
    before = service.snapshot(tmp_path)
    target.write_bytes(b"\x00\x02")
    after = service.snapshot(tmp_path)
    with pytest.raises(OpenHandsChangeCaptureError, match="binary or oversized"):
        service.compare(before, after)


def test_change_capture_rejects_agent_created_symlink(tmp_path: Path):
    service = OpenHandsChangeCaptureService()
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = tmp_path / "escape.txt"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are not available in this environment")
    with pytest.raises(OpenHandsChangeCaptureError, match="Symlink created"):
        service.snapshot(tmp_path)


def test_change_capture_rejects_secret_path_created_by_agent(tmp_path: Path):
    service = OpenHandsChangeCaptureService()
    (tmp_path / ".env.agent").write_text("TOKEN=secret", encoding="utf-8")
    with pytest.raises(OpenHandsChangeCaptureError, match="Forbidden path"):
        service.snapshot(tmp_path)
