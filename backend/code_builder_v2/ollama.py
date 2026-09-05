from __future__ import annotations

import json
from dataclasses import dataclass
from urllib import error, request as urlrequest

from .applier import ProposedFileChange
from .models import ChangePlan, TaskRequest
from .planner import PlannerUnavailable


class OllamaError(RuntimeError):
    pass


@dataclass(slots=True)
class OllamaClient:
    base_url: str = "http://127.0.0.1:11434"
    default_model: str = "qwen2.5-coder:7b"
    timeout_seconds: int = 180

    def generate_json(self, prompt: str, model: str | None = None) -> dict:
        payload = json.dumps(
            {
                "model": model or self.default_model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1},
            }
        ).encode("utf-8")
        req = urlrequest.Request(
            self.base_url.rstrip("/") + "/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise OllamaError(f"Ollama request failed: {exc}") from exc
        raw = body.get("response")
        if not isinstance(raw, str):
            raise OllamaError("Ollama response did not contain a JSON response string")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OllamaError("Ollama returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise OllamaError("Ollama JSON result must be an object")
        return data


@dataclass(slots=True)
class OllamaPlanner:
    client: OllamaClient

    def create_plan(self, request: TaskRequest) -> ChangePlan:
        prompt = f"""You are the planning engine of LUMINA Code Builder V2.
Return ONLY JSON matching this schema:
{{"summary":"...","changes":[{{"path":"relative/path","operation":"create|modify|delete","reason":"..."}}],"validation_commands":["..."]}}
Rules: every required file must be listed; use repository-relative paths only; do not invent unrelated files; include focused validation commands.
User request:\n{request.prompt}
"""
        try:
            data = self.client.generate_json(prompt, request.model)
            return ChangePlan.model_validate(data)
        except Exception as exc:
            if isinstance(exc, PlannerUnavailable):
                raise
            raise PlannerUnavailable(str(exc)) from exc


@dataclass(slots=True)
class OllamaChangeGenerator:
    client: OllamaClient

    def generate(
        self,
        request: TaskRequest,
        plan: ChangePlan,
        file_context: dict[str, str],
    ) -> list[ProposedFileChange]:
        plan_json = plan.model_dump_json()
        context_json = json.dumps(file_context, ensure_ascii=False)
        prompt = f"""You are the implementation engine of LUMINA Code Builder V2.
Implement EXACTLY the approved plan and return ONLY JSON:
{{"changes":[{{"path":"relative/path","operation":"create|modify|delete","content":"full file content or null for delete"}}]}}
Hard rules:
- Include every planned path exactly once and no unplanned paths.
- Preserve the planned operation for every path.
- For create/modify return the COMPLETE final file content, never a diff.
- For delete content must be null.
- Do not use markdown fences.
Approved plan: {plan_json}
Current file context: {context_json}
Original request: {request.prompt}
"""
        data = self.client.generate_json(prompt, request.model)
        raw_changes = data.get("changes")
        if not isinstance(raw_changes, list):
            raise OllamaError("Generated result is missing changes array")
        changes: list[ProposedFileChange] = []
        for item in raw_changes:
            if not isinstance(item, dict):
                raise OllamaError("Each generated change must be an object")
            changes.append(
                ProposedFileChange(
                    path=str(item.get("path", "")),
                    operation=str(item.get("operation", "")),
                    content=item.get("content"),
                )
            )
        return changes
