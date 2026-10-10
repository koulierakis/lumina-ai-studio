"""Gold Builder coding-engine boundary for LUMINA Code Builder.

Gold Builder is a separate service (its own FastAPI app mounting ``/api/gb/*``).
LUMINA keeps the two repositories maintainable by talking to it over a small
HTTP boundary instead of copying its source tree in. Nothing here mutates a
repository: it only creates/inspects jobs and reads their activity, preview,
review and final report.

The engine is opt-in and reports itself unavailable when the service is not
reachable, so the native Code Builder remains the safe default.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterator

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8001"
DEFAULT_TIMEOUT = 5.0


def gold_builder_base_url() -> str:
    return (os.environ.get("GOLD_BUILDER_URL") or DEFAULT_BASE_URL).rstrip("/")


@dataclass(frozen=True, slots=True)
class GoldBuilderEngineStatus:
    name: str
    available: bool
    base_url: str
    safe_mode: bool = True
    detail: str = ""

    def public_status(self) -> dict[str, object]:
        return {
            "name": self.name,
            "available": self.available,
            "base_url": self.base_url,
            "safe_mode": self.safe_mode,
            "detail": self.detail,
        }


class GoldBuilderUnavailable(RuntimeError):
    """Raised when the Gold Builder service cannot be reached."""


class GoldBuilderEngine:
    name = "gold_builder"

    def __init__(self, base_url: str | None = None, *, client: httpx.Client | None = None, timeout: float = DEFAULT_TIMEOUT):
        self.base_url = (base_url or gold_builder_base_url()).rstrip("/")
        self._client = client
        self._timeout = timeout

    # ---- transport -------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}/api/gb{path}"
        try:
            if self._client is not None:
                response = self._client.request(method, url, **kwargs)
            else:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise GoldBuilderUnavailable(f"Gold Builder is not reachable at {self.base_url}: {exc}") from exc
        if response.status_code >= 400:
            raise GoldBuilderUnavailable(f"Gold Builder returned {response.status_code} for {path}")
        return response.json()

    # ---- health / status -------------------------------------------------
    def status(self) -> GoldBuilderEngineStatus:
        try:
            health = self._request("GET", "/health")
            return GoldBuilderEngineStatus(self.name, True, self.base_url, True, str(health.get("status") or "ok"))
        except Exception as exc:  # unreachable or unhealthy => not available
            return GoldBuilderEngineStatus(self.name, False, self.base_url, True, str(exc))

    # ---- catalogue -------------------------------------------------------
    def capabilities(self) -> dict[str, Any]:
        return self._request("GET", "/capabilities")

    def providers(self) -> dict[str, Any]:
        return self._request("GET", "/providers")

    # ---- job lifecycle ---------------------------------------------------
    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/jobs", json=payload)

    def create_existing_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/jobs/existing", json=payload)

    def start_job(self, job_id: str) -> dict[str, Any]:
        return self._request("POST", f"/jobs/{job_id}/start")

    def get_status(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/jobs/{job_id}")

    def review(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/jobs/{job_id}/review")

    def verify(self, job_id: str) -> dict[str, Any]:
        return self._request("POST", f"/jobs/{job_id}/verify")

    def preview(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/jobs/{job_id}/preview")

    def start_preview(self, job_id: str) -> dict[str, Any]:
        return self._request("POST", f"/jobs/{job_id}/preview/start")

    def cancel(self, job_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/jobs/{job_id}")

    def resume(self, job_id: str) -> dict[str, Any]:
        return self._request("POST", f"/jobs/{job_id}/guardian/resume")

    def final_report(self, job_id: str) -> dict[str, Any]:
        """Assemble the owner-facing Final Report from real job state."""
        job = self.get_status(job_id)
        report: dict[str, Any] = {
            "job_id": job_id,
            "status": job.get("status"),
            "phase": job.get("phase"),
            "provider": job.get("llm_provider") or job.get("provider"),
            "files": job.get("files") or job.get("changed_files"),
        }
        for key, path in (("review", f"/jobs/{job_id}/review"), ("screenshots", f"/jobs/{job_id}/screenshot")):
            try:
                report[key] = self._request("GET", path)
            except GoldBuilderUnavailable:
                report[key] = None
        return report

    def events(self, job_id: str) -> Iterator[str]:
        """Yield raw Server-Sent Event lines from the live job stream."""
        url = f"{self.base_url}/api/gb/jobs/{job_id}/stream"
        try:
            with httpx.Client(timeout=None) as client, client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise GoldBuilderUnavailable(f"Gold Builder stream returned {response.status_code}")
                for line in response.iter_lines():
                    if line:
                        yield line
        except httpx.HTTPError as exc:
            raise GoldBuilderUnavailable(f"Gold Builder stream failed: {exc}") from exc
