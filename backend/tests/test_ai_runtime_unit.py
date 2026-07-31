import asyncio
import json

from ai_runtime.manager import RuntimeManager
from ai_runtime.schemas import RuntimeJob, RuntimeJobStatus
from providers.base import ErrorKind, ProviderError


def test_runtime_job_lifecycle_completes():
    manager = RuntimeManager()

    async def executor(job, progress):
        await progress(job, RuntimeJobStatus.RUNNING, 80, "unit executor")
        return {"ok": True}

    job = RuntimeJob(studio="unit", task_type="llm", payload={"prompt": "test"}, owner_email="owner@example.com")
    completed = asyncio.run(manager.submit(job, executor, run_background=False))
    assert completed.status == RuntimeJobStatus.COMPLETED
    assert completed.progress == 100
    assert completed.result == {"ok": True}
    assert completed.provider in {"local", "cloud", "hybrid"}


def test_runtime_model_manager_capabilities_cover_required_types():
    manager = RuntimeManager()
    models = manager.models.list()["available_models"]
    assert {item["type"] for item in models} >= {"llm", "image_generation", "image_editing", "video", "speech", "voice_cloning", "music", "embedding", "ocr", "vision", "code", "translation"}
    assert manager.health()["providers"]["ok"] is True


def test_runtime_plugin_installation_registers_provider():
    manager = RuntimeManager()
    result = manager.plugins.install({"name": "unit-plugin", "kind": "hybrid", "capabilities": ["llm"], "priority": 1})
    assert result["status"] == "installed"
    assert any(provider["name"] == "unit-plugin" for provider in manager.providers.list())


def test_runtime_provider_429_failure_serializes_without_circular_reference(tmp_path):
    manager = RuntimeManager()
    manager.jobs_path = tmp_path / "jobs.json"

    async def executor(job, progress):
        circular = {"job": job}
        job.result = circular
        job.metadata["provider_error"] = {
            "provider": "gemini",
            "model": "gemini-3.1-flash-image",
            "error_code": "RESOURCE_EXHAUSTED",
            "http_status": 429,
            "message": "Gemini image generation quota is exhausted.",
            "retryable": True,
        }
        raise ProviderError(
            "gemini",
            "Gemini image generation quota is exhausted.",
            kind=ErrorKind.QUOTA,
            retryable=True,
            status_code=429,
            safe_message="Gemini image generation quota is exhausted. Select another provider or enable quota and retry.",
        )

    job = RuntimeJob(studio="photo", task_type="image_generation", payload={"prompt": "test"}, owner_email="owner@example.com")
    completed = asyncio.run(manager.submit(job, executor, run_background=False))
    assert completed.status == RuntimeJobStatus.FAILED
    assert "Gemini image generation quota is exhausted" in completed.error
    parsed = json.loads(manager.jobs_path.read_text(encoding="utf-8"))
    assert parsed[0]["metadata"]["provider_error"]["http_status"] == 429
    assert isinstance(parsed[0]["result"]["job"], str)
    assert "RuntimeJob" in parsed[0]["result"]["job"]
