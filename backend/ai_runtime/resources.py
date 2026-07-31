from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any


class ResourceManager:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(__file__).resolve().parents[2]

    def snapshot(self, running_jobs: int = 0, queued_jobs: int = 0) -> dict[str, Any]:
        disk = shutil.disk_usage(self.root)
        load = running_jobs + queued_jobs
        return {
            "cpu": {"available": True, "cores": os.cpu_count() or 1, "usage_percent": None},
            "ram": {"available": True, "usage_percent": None, "used_bytes": None, "total_bytes": None},
            "gpu": {"available": False, "devices": [], "usage_percent": None},
            "gpu_vram": {"available": False, "used_bytes": None, "total_bytes": None},
            "disk": {"free_bytes": disk.free, "used_bytes": disk.used, "total_bytes": disk.total, "used_percent": round((disk.used / disk.total) * 100, 2) if disk.total else 0},
            "runtime_load": load,
            "running_jobs": running_jobs,
            "queued_jobs": queued_jobs,
            "estimated_queue_time_seconds": queued_jobs * 15,
        }

    def allocate(self, task_type: str) -> dict[str, Any]:
        weights = {"video": 4, "image_generation": 3, "image_editing": 3, "speech": 2, "llm": 2, "ocr": 1}
        return {"task_type": task_type, "weight": weights.get(task_type, 1), "gpu_preferred": task_type in {"video", "image_generation", "image_editing"}}
