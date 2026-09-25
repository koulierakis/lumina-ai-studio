"""Authenticated HTTP client that executes existing LUMINA capability endpoints.

The client is transport-injectable: production uses the live API over loopback,
while tests can route through an ASGI transport to the real FastAPI app. Every
request carries a valid owner token via ``auth.issue_token`` so the exact same
authorization path the browser uses is exercised.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Mapping

import httpx

from ai_runtime.capabilities.registry import CapabilityOperation

DEFAULT_TIMEOUT = httpx.Timeout(connect=15.0, read=180.0, write=60.0, pool=15.0)


def default_base_url() -> str:
    """Best-effort base URL for self-calls to the running LUMINA backend."""
    configured = os.environ.get("LUMINA_MIND_BASE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    port = os.environ.get("PORT") or os.environ.get("LUMINA_PORT") or "8000"
    return f"http://127.0.0.1:{port}"


def _mint_token(owner: str) -> str | None:
    try:
        from auth import issue_token

        return issue_token(owner)
    except Exception:
        return None


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[redacted]" if any(marker in str(key).lower() for marker in ("token", "secret", "authorization", "key")) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


class CapabilityExecutionError(RuntimeError):
    """Raised when a real capability endpoint rejects a request."""

    def __init__(self, status_code: int | None, message: str, response: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.response = response


class MindCapabilityClient:
    """Call the existing LUMINA HTTP surface as the owner."""

    def __init__(
        self,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        append_auth: bool = True,
    ) -> None:
        self.base_url = (base_url or default_base_url()).rstrip("/")
        self._transport = transport
        self._append_auth = append_auth

    def _headers(self, owner: str) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._append_auth:
            token = _mint_token(owner)
            if token:
                headers["Authorization"] = f"Bearer {token}"
        return headers

    async def request(
        self,
        operation: CapabilityOperation,
        owner: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = params or {}
        path = operation.route(**params)
        query: dict[str, str] = {}
        for key in operation.optional_params:
            value = params.get(key)
            if value is None:
                continue
            if isinstance(value, (list, tuple, dict)):
                value = json.dumps(value, ensure_ascii=False)
            query[key] = str(value)
        if operation.content == "query":
            for key in operation.optional_params:
                value = params.get(key)
                if value is not None and key not in query:
                    query[key] = str(value)

        content = None
        json_body = None
        if operation.content == "json":
            json_body = body if body is not None else {
                key: params[key] for key in operation.optional_params if key in params
            }
        elif operation.content == "form-result":
            content = {
                key: params[key] for key in operation.optional_params if key in params
            }
        elif operation.content == "query":
            for key in operation.optional_params:
                if key in params:
                    query[key] = str(params[key])

        kwargs: dict[str, Any] = {
            "method": operation.method.upper(),
            "url": path,
        }
        if query:
            kwargs["params"] = query
        if json_body is not None:
            kwargs["json"] = json_body
        if content:
            kwargs["data"] = content

        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._headers(owner),
            transport=self._transport,
            timeout=DEFAULT_TIMEOUT,
            trust_env=False,
        ) as client:
            response = await client.request(**kwargs)

        if response.status_code < 200 or response.status_code >= 300:
            detail: dict[str, Any] | None = None
            try:
                parsed = response.json()
                if isinstance(parsed, dict):
                    detail = _redact(parsed)
            except Exception:
                parsed = None
            raise CapabilityExecutionError(
                response.status_code,
                str(parsed.get("detail") if isinstance(parsed, dict) else response.text)[:300]
                or f"HTTP {response.status_code}",
                detail,
            )
        try:
            return response.json()
        except Exception:
            return {"status": response.status_code, "content": response.text[:500]}

    async def execute(self, operation: CapabilityOperation, owner: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute an operation, polling to a terminal state when it returns a job."""
        result = await self.request(operation, owner, params=params)
        if operation.job_fallback_path is None:
            return result
        job_id = str(
            (params.get("task_id") or result.get(operation.job_id_field) or "")
            if operation.id == "get_task"
            else result.get(operation.job_id_field) or ""
        )
        if not job_id:
            return result
        return await self.poll_job(
            operation,
            owner,
            job_id=job_id,
            attempts=self._poll_attempts(),
        )

    def _poll_attempts(self) -> int:
        raw = os.environ.get("LUMINA_MIND_POLL_ATTEMPTS", "24").strip()
        try:
            return max(1, min(int(raw), 300))
        except ValueError:
            return 24

    async def poll_job(
        self,
        operation: CapabilityOperation,
        owner: str,
        *,
        job_id: str,
        attempts: int = 24,
        interval: float = 2.5,
    ) -> dict[str, Any]:
        """Poll a job endpoint until terminal status or the attempt budget."""
        if not operation.job_fallback_path:
            return {"id": job_id, "status": "queued"}
        path = operation.job_fallback_path.replace("{id}", job_id)
        for index in range(attempts):
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers=self._headers(owner),
                transport=self._transport,
                timeout=DEFAULT_TIMEOUT,
                trust_env=False,
            ) as client:
                response = await client.get(path)
            if response.status_code < 200 or response.status_code >= 300:
                await asyncio.sleep(interval)
                continue
            job = response.json()
            status = str(job.get(operation.job_status_field) or "").lower()
            if status in operation.job_terminal:
                return job
            if index == attempts - 1:
                break
            await asyncio.sleep(interval)
        return {"id": job_id, "status": "pending", "polled": attempts}