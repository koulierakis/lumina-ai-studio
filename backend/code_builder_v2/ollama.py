from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from .applier import ProposedFileChange
from .models import ChangePlan, TaskRequest
from .planner import PlannerUnavailable


class OllamaError(RuntimeError):
    """Backward-compatible Code Builder V2 LLM error."""


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
        if text.lower().startswith("json"):
            text = text[4:].lstrip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise OllamaError("Cloud code model did not return a JSON object.")
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise OllamaError("Cloud code model returned invalid JSON.") from exc

    if not isinstance(data, dict):
        raise OllamaError("Cloud code model JSON result must be an object.")
    return data


@dataclass(slots=True)
class OllamaClient:
    """Cloud-first LLM client retained under the legacy class name for compatibility.

    Routing policy:
    1. GROQ_API_KEY present -> Groq chat completions.
    2. Otherwise -> Hugging Face InferenceClient.

    The Code Builder V2 no longer calls a local Ollama server.
    """

    base_url: str = "http://127.0.0.1:11434"  # legacy compatibility only; never contacted
    default_model: str = "qwen2.5-coder:7b"  # legacy local model setting; cloud routing ignores Ollama-style names
    timeout_seconds: int = 180

    @staticmethod
    def _is_cloud_model_name(model: str | None) -> bool:
        if not model:
            return False
        value = model.strip()
        if not value or ":" in value:
            return False
        return "/" in value or value.startswith(("llama-", "mixtral-", "qwen-", "openai/"))

    def _groq_model(self, requested: str | None) -> str:
        configured = os.getenv("GROQ_CODE_MODEL", "").strip()
        if configured:
            return configured
        if requested and self._is_cloud_model_name(requested) and "/" not in requested:
            return requested
        return "llama-3.3-70b-versatile"

    def _hf_model(self, requested: str | None) -> str:
        configured = os.getenv("HF_CODE_MODEL", "").strip()
        if configured:
            return configured
        if requested and self._is_cloud_model_name(requested) and "/" in requested:
            return requested
        return "Qwen/Qwen2.5-Coder-32B-Instruct"

    def _generate_with_groq(self, prompt: str, requested_model: str | None) -> dict[str, Any]:
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not api_key:
            raise OllamaError("GROQ_API_KEY is not configured.")

        try:
            from groq import Groq

            client = Groq(api_key=api_key, timeout=self.timeout_seconds)
            response = client.chat.completions.create(
                model=self._groq_model(requested_model),
                messages=[
                    {
                        "role": "system",
                        "content": "You are the LUMINA Code Builder V2 engine. Return only a valid JSON object with no markdown fences.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
        except Exception as exc:
            raise OllamaError(f"Groq code-model request failed: {exc}") from exc

        if not isinstance(raw, str) or not raw.strip():
            raise OllamaError("Groq returned an empty response.")
        return _extract_json_object(raw)

    def _generate_with_huggingface(self, prompt: str, requested_model: str | None) -> dict[str, Any]:
        token = (
            os.getenv("HF_TOKEN", "").strip()
            or os.getenv("HUGGINGFACEHUB_API_TOKEN", "").strip()
            or None
        )
        model = self._hf_model(requested_model)

        try:
            from huggingface_hub import InferenceClient

            client = InferenceClient(
                model=model,
                token=token,
                timeout=self.timeout_seconds,
            )
            try:
                response = client.chat_completion(
                    messages=[
                        {
                            "role": "system",
                            "content": "You are the LUMINA Code Builder V2 engine. Return only a valid JSON object with no markdown fences.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=8192,
                    temperature=0.1,
                )
                raw = response.choices[0].message.content
            except Exception:
                raw = client.text_generation(
                    prompt,
                    max_new_tokens=8192,
                    temperature=0.1,
                    return_full_text=False,
                )
        except Exception as exc:
            raise OllamaError(
                f"Hugging Face code-model request failed for {model}: {exc}"
            ) from exc

        if not isinstance(raw, str) or not raw.strip():
            raise OllamaError("Hugging Face returned an empty response.")
        return _extract_json_object(raw)

    def generate_json(self, prompt: str, model: str | None = None) -> dict[str, Any]:
        if os.getenv("GROQ_API_KEY", "").strip():
            return self._generate_with_groq(prompt, model)
        return self._generate_with_huggingface(prompt, model)


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
