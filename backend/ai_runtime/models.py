from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from .schemas import MODEL_TYPES, utc_now


@dataclass
class RuntimeModel:
    name: str
    type: str
    provider: str
    version: str = "1.0.0"
    id: str = field(default_factory=lambda: uuid4().hex)
    installed: bool = False
    enabled: bool = True
    default_for: list[str] = field(default_factory=list)
    studio_selection: dict[str, bool] = field(default_factory=dict)
    path: str = ""
    size_bytes: int = 0
    checksum: str = ""
    status: str = "available"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class ModelManager:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(__file__).resolve().parents[2] / ".lumina" / "runtime"
        self.models_dir = self.root / "models"
        self.registry_file = self.root / "models.json"
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.models: dict[str, RuntimeModel] = {}
        self.download_queue: list[dict[str, Any]] = []
        self.installation_queue: list[dict[str, Any]] = []
        self._load()
        self._seed_catalog()

    def _load(self) -> None:
        try:
            raw = json.loads(self.registry_file.read_text(encoding="utf-8"))
            self.models = {item["id"]: RuntimeModel(**item) for item in raw.get("models", [])}
            self.download_queue = raw.get("download_queue", [])
            self.installation_queue = raw.get("installation_queue", [])
        except Exception:
            self.models = {}

    def _save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.registry_file.write_text(
            json.dumps(
                {
                    "models": [m.as_dict() for m in self.models.values()],
                    "download_queue": self.download_queue,
                    "installation_queue": self.installation_queue,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _seed_catalog(self) -> None:
        if self.models:
            return
        seeds = [
            ("Ollama Code LLM", "code", "local"),
            ("Ollama General LLM", "llm", "local"),
            ("Gemini Vision", "vision", "cloud"),
            ("OpenAI Image", "image_generation", "cloud"),
            ("ComfyUI Stable Diffusion", "image_editing", "local"),
            ("Luma Video", "video", "cloud"),
            ("Lumina Speech", "speech", "hybrid"),
            ("Lumina Voice Clone", "voice_cloning", "hybrid"),
            ("Lumina Music", "music", "hybrid"),
            ("Lumina Embeddings", "embedding", "local"),
            ("Lumina OCR", "ocr", "local"),
            ("Lumina Translate", "translation", "cloud"),
        ]
        for name, model_type, provider in seeds:
            self.register(
                name=name,
                type=model_type,
                provider=provider,
                installed=provider == "cloud",
                enabled=True,
            )

    def register(self, **data: Any) -> RuntimeModel:
        model_type = data.get("type")
        if model_type not in MODEL_TYPES:
            raise ValueError(f"Unsupported model type: {model_type}")
        model = RuntimeModel(**data)
        self.models[model.id] = model
        self._save()
        return model

    def list(self) -> dict[str, Any]:
        installed = [m.as_dict() for m in self.models.values() if m.installed]
        available = [m.as_dict() for m in self.models.values()]
        return {
            "installed_models": installed,
            "available_models": available,
            "download_queue": self.download_queue,
            "installation_queue": self.installation_queue,
            "model_types": list(MODEL_TYPES),
            "disk_usage": self.disk_usage(),
            "gpu_memory_usage": {"available": False},
            "cpu_usage": {"available": True, "usage_percent": None},
        }

    def disk_usage(self) -> dict[str, Any]:
        total = (
            sum(p.stat().st_size for p in self.models_dir.rglob("*") if p.is_file())
            if self.models_dir.exists()
            else 0
        )
        return {"model_storage_bytes": total, "path": str(self.models_dir)}

    def set_enabled(self, model_id: str, enabled: bool) -> RuntimeModel:
        model = self.models[model_id]
        model.enabled = enabled
        model.status = "enabled" if enabled else "disabled"
        model.updated_at = utc_now()
        self._save()
        return model

    def select_default(self, model_id: str, studio: str) -> RuntimeModel:
        for model in self.models.values():
            model.studio_selection[studio] = model.id == model_id
            if studio in model.default_for and model.id != model_id:
                model.default_for.remove(studio)
        model = self.models[model_id]
        if studio not in model.default_for:
            model.default_for.append(studio)
        model.updated_at = utc_now()
        self._save()
        return model

    def queue_download(self, model_id: str) -> dict[str, Any]:
        item = {
            "id": uuid4().hex,
            "model_id": model_id,
            "status": "queued",
            "progress": 0,
            "created_at": utc_now(),
        }
        self.download_queue.append(item)
        self._save()
        return item

    def pause(self, queue_id: str) -> dict[str, Any]:
        return self._queue_status(queue_id, "paused")

    def resume(self, queue_id: str) -> dict[str, Any]:
        return self._queue_status(queue_id, "queued")

    def cancel(self, queue_id: str) -> dict[str, Any]:
        return self._queue_status(queue_id, "cancelled")

    def _queue_status(self, queue_id: str, status: str) -> dict[str, Any]:
        for item in self.download_queue + self.installation_queue:
            if item["id"] == queue_id:
                item["status"] = status
                item["updated_at"] = utc_now()
                self._save()
                return item
        raise KeyError(queue_id)

    def verify(self, model_id: str) -> dict[str, Any]:
        model = self.models[model_id]
        path = Path(model.path) if model.path else self.models_dir / model.id
        exists = path.exists()
        checksum = ""
        if exists and path.is_file():
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        return {
            "model_id": model_id,
            "ok": exists or model.provider == "cloud",
            "checksum": checksum or model.checksum,
            "status": "verified" if exists or model.provider == "cloud" else "missing",
        }

    def repair(self, model_id: str) -> dict[str, Any]:
        model = self.models[model_id]
        if model.provider == "cloud":
            model.status = "available"
        elif not model.path:
            model.path = str(self.models_dir / model.id)
            model.status = "repair_queued"
            self.installation_queue.append(
                {
                    "id": uuid4().hex,
                    "model_id": model_id,
                    "status": "queued",
                    "operation": "repair",
                    "created_at": utc_now(),
                }
            )
        model.updated_at = utc_now()
        self._save()
        return {"model": model.as_dict(), "repair_started": True}

    def delete(self, model_id: str) -> dict[str, Any]:
        model = self.models[model_id]
        if model.path:
            target = Path(model.path)
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink()
        model.installed = False
        model.status = "deleted"
        model.updated_at = utc_now()
        self._save()
        return model.as_dict()

    def move_storage(self, path: str) -> dict[str, Any]:
        new_dir = Path(path).resolve()
        new_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir = new_dir
        self._save()
        return {"path": str(new_dir), "ok": True}

    def import_model(
        self,
        name: str,
        path: str,
        type: str,
        provider: str = "local",
    ) -> RuntimeModel:
        source = Path(path)
        size = source.stat().st_size if source.exists() and source.is_file() else 0
        return self.register(
            name=name,
            type=type,
            provider=provider,
            installed=True,
            path=str(source),
            size_bytes=size,
            status="installed",
        )

    def export_installed(self) -> dict[str, Any]:
        return {
            "models": [m.as_dict() for m in self.models.values() if m.installed],
            "exported_at": utc_now(),
        }

    def update_detection(self) -> dict[str, Any]:
        return {
            "updates": [
                {
                    "model_id": m.id,
                    "name": m.name,
                    "available": False,
                    "current_version": m.version,
                }
                for m in self.models.values()
            ],
            "checked_at": utc_now(),
        }
