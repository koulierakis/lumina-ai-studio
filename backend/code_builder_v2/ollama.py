from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from .applier import ProposedFileChange
from .models import ChangePlan, TaskRequest
from .planner import PlannerUnavailable

log = logging.getLogger(__name__)


class OllamaError(RuntimeError):
    """Backward-compatible Code Builder V2 LLM error."""


class JSONRecoveryError(OllamaError):
    """Raised when JSON recovery attempts are exhausted."""


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


def _build_json_recovery_prompt(original_prompt: str, failed_response: str, attempt: int) -> str:
    """Build a concise recovery prompt for truncated/malformed JSON."""
    return f"""The previous response was truncated or malformed JSON. Complete the JSON object correctly.

Original request: {original_prompt}

Failed response (truncated): {failed_response[-3000:]}

Return ONLY the complete valid JSON object matching the original schema. No markdown, no explanation."""


def _build_schema_recovery_prompt(original_prompt: str, failed_response: str, schema_error: str, attempt: int) -> str:
    """Build a concise recovery prompt for schema-invalid JSON."""
    return f"""The previous response was valid JSON but violated the required Code Builder schema.

Schema error: {schema_error}

Required schema:
{{"changes":[
  {{"path":"relative/path","operation":"create|update|delete","content":"full file content or null for delete"}}
]}}

Hard rules:
- "changes" MUST be an array of objects, NOT strings or nested arrays
- Each change object MUST have: "path" (string), "operation" (string: create|update|delete), "content" (string or null)
- NO extra fields, NO missing fields, NO string items in changes array

Original request: {original_prompt}

Failed response (truncated): {failed_response[-3000:]}

Return ONLY the complete valid JSON object matching the schema above. No markdown, no explanation."""


def _validate_changes_schema(data: dict[str, Any], log: logging.Logger) -> tuple[bool, str]:
    """Validate that parsed JSON matches Code Builder changes schema.
    
    Returns: (is_valid, error_message)
    """
    if "changes" not in data:
        return False, "Missing 'changes' key"
    
    changes = data["changes"]
    if not isinstance(changes, list):
        return False, "'changes' must be an array"
    
    if not changes:
        return False, "'changes' array is empty"
    
    valid_operations = {"create", "update", "delete"}
    
    for idx, item in enumerate(changes):
        if not isinstance(item, dict):
            return False, f"changes[{idx}] must be an object, got {type(item).__name__}"
        
        if "path" not in item or not isinstance(item["path"], str) or not item["path"].strip():
            return False, f"changes[{idx}] missing or invalid 'path' (must be non-empty string)"
        
        if "operation" not in item or not isinstance(item["operation"], str) or item["operation"] not in valid_operations:
            return False, f"changes[{idx}] missing or invalid 'operation' (must be create|update|delete)"
        
        if "content" not in item:
            return False, f"changes[{idx}] missing 'content' field"
        
        if item["operation"] in {"create", "update"} and item["content"] is None:
            return False, f"changes[{idx}] 'content' must be string for create/update operations"
        
        if item["operation"] == "delete" and item["content"] is not None:
            return False, f"changes[{idx}] 'content' must be null for delete operations"
    
    return True, ""


@dataclass(slots=True)
class OllamaClient:
    """Cloud-first LLM client with local Ollama fallback.

    Routing policy:
    1. GROQ_API_KEY present -> Groq chat completions.
    2. HF_TOKEN present -> Hugging Face InferenceClient.
    3. Local Ollama server -> qwen2.5-coder:1.5b

    The Code Builder V2 prefers cloud providers for quality.
    """

    base_url: str = "http://127.0.0.1:11434"
    default_model: str = "qwen2.5-coder:1.5b"
    timeout_seconds: int = 600

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
        return os.getenv("LUMINA_GROQ_MODEL", "").strip() or "openai/gpt-oss-120b"

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

        max_retries = 2
        last_raw = ""
        
        for attempt in range(max_retries + 1):
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
                    max_tokens=8192,
                    response_format={"type": "json_object"},
                )
                raw = response.choices[0].message.content
            except Exception as exc:
                raise OllamaError(f"Groq code-model request failed: {exc}") from exc

            if not isinstance(raw, str) or not raw.strip():
                raise OllamaError("Groq returned an empty response.")
            
            last_raw = raw
            
            try:
                return _extract_json_object(raw)
            except OllamaError as exc:
                log.warning(
                    "Groq JSON parse failed (attempt %d/%d): %s",
                    attempt + 1, max_retries + 1, exc
                )
                if attempt < max_retries:
                    # Build recovery prompt with the failed response
                    prompt = _build_json_recovery_prompt(prompt, raw, attempt)
                    continue
                raise JSONRecoveryError(
                    f"Groq structured output validation failed after {max_retries + 1} attempts: {exc}"
                ) from exc

    def _generate_with_huggingface(self, prompt: str, requested_model: str | None) -> dict[str, Any]:
        token = (
            os.getenv("HF_TOKEN", "").strip()
            or os.getenv("HUGGINGFACEHUB_API_TOKEN", "").strip()
            or None
        )
        model = self._hf_model(requested_model)
        
        # Allow configuring HF provider to avoid incompatible ones (e.g., nscale)
        hf_provider = os.getenv("HF_INFERENCE_PROVIDER", "").strip() or None

        max_retries = 2
        last_raw = ""
        
        for attempt in range(max_retries + 1):
            try:
                from huggingface_hub import InferenceClient

                client = InferenceClient(
                    model=model,
                    token=token,
                    timeout=self.timeout_seconds,
                    provider=hf_provider,
                )
                # Use chat_completion for chat/instruct models - don't fall back to text_generation
                # as it may use incompatible providers/tasks
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
            except Exception as exc:
                # Check for specific unsupported task/provider errors
                error_msg = str(exc).lower()
                if "task" in error_msg and "not supported" in error_msg:
                    # This provider/model combo doesn't support the required task
                    # Skip to next provider immediately (don't retry)
                    raise OllamaError(
                        f"Hugging Face provider does not support required task for {model}: {exc}"
                    ) from exc
                raise OllamaError(
                    f"Hugging Face code-model request failed for {model}: {exc}"
                ) from exc

            if not isinstance(raw, str) or not raw.strip():
                raise OllamaError("Hugging Face returned an empty response.")
            
            last_raw = raw
            
            try:
                return _extract_json_object(raw)
            except OllamaError as exc:
                log.warning(
                    "Hugging Face JSON parse failed (attempt %d/%d): %s",
                    attempt + 1, max_retries + 1, exc
                )
                if attempt < max_retries:
                    prompt = _build_json_recovery_prompt(prompt, raw, attempt)
                    continue
                raise JSONRecoveryError(
                    f"Hugging Face structured output validation failed after {max_retries + 1} attempts: {exc}"
                ) from exc

    def _generate_with_local_ollama(self, prompt: str, requested_model: str | None) -> dict[str, Any]:
        """Generate using local Ollama server via HTTP API."""
        import urllib.request
        import urllib.error

        model = requested_model or self.default_model
        url = f"{self.base_url}/api/generate"
        
        max_retries = 2
        last_raw = ""
        
        for attempt in range(max_retries + 1):
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0.1,
                    "num_ctx": 8192,
                    "num_predict": 8192,
                }
            }
            
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
            except urllib.error.URLError as exc:
                raise OllamaError(f"Local Ollama request failed: {exc}") from exc
            except Exception as exc:
                raise OllamaError(f"Local Ollama request failed: {exc}") from exc

            if not isinstance(raw, str) or not raw.strip():
                raise OllamaError("Local Ollama returned an empty response.")
            
            last_raw = raw
            
            # Ollama returns {"response": "..."} when format=json
            try:
                parsed = json.loads(raw)
                if "response" in parsed:
                    raw = parsed["response"]
            except json.JSONDecodeError:
                pass
                
            try:
                return _extract_json_object(raw)
            except OllamaError as exc:
                log.warning(
                    "Local Ollama JSON parse failed (attempt %d/%d): %s",
                    attempt + 1, max_retries + 1, exc
                )
                if attempt < max_retries:
                    prompt = _build_json_recovery_prompt(prompt, raw, attempt)
                    continue
                raise JSONRecoveryError(
                    f"Local Ollama structured output validation failed after {max_retries + 1} attempts: {exc}"
                ) from exc

    def generate_json(self, prompt: str, model: str | None = None) -> dict[str, Any]:
        """Generate JSON with automatic provider fallback on failure.

        Provider priority for production: Groq -> HuggingFace
        Local Ollama is ONLY included when explicitly configured via OLLAMA_BASE_URL
        pointing to a non-localhost endpoint (for production Ollama) or when
        LUMINA_USE_LOCAL_OLLAMA=true (for local development).
        """
        providers = []
        
        if os.getenv("GROQ_API_KEY", "").strip():
            providers.append(("groq", self._generate_with_groq))
        if os.getenv("HF_TOKEN", "").strip() or os.getenv("HUGGINGFACEHUB_API_TOKEN", "").strip():
            providers.append(("huggingface", self._generate_with_huggingface))
        
        # Local Ollama ONLY when explicitly configured for production (non-localhost URL)
        # or explicitly enabled for local development
        ollama_base_url = os.getenv("OLLAMA_BASE_URL", "").strip()
        use_local_ollama = os.getenv("LUMINA_USE_LOCAL_OLLAMA", "").strip().lower() in {"1", "true", "yes", "on"}
        
        if ollama_base_url and not ollama_base_url.startswith(("http://127.0.0.1", "http://localhost", "http://::1")):
            # Explicitly configured production Ollama endpoint
            self.base_url = ollama_base_url
            providers.append(("ollama", self._generate_with_local_ollama))
        elif use_local_ollama:
            # Local development with Ollama
            providers.append(("ollama", self._generate_with_local_ollama))
        
        if not providers:
            raise OllamaError(
                "No model providers configured. Set GROQ_API_KEY, HF_TOKEN, "
                "or configure OLLAMA_BASE_URL for production Ollama / "
                "LUMINA_USE_LOCAL_OLLAMA=true for local development."
            )
        
        last_error: Exception | None = None
        
        for provider_name, provider_fn in providers:
            try:
                log.info("Attempting JSON generation with provider: %s", provider_name)
                result = provider_fn(prompt, model)
                log.info("JSON generation succeeded with provider: %s", provider_name)
                return result
            except JSONRecoveryError as exc:
                log.warning(
                    "Provider %s JSON recovery exhausted, falling back: %s",
                    provider_name, exc
                )
                last_error = exc
                continue
            except OllamaError as exc:
                log.warning(
                    "Provider %s failed, falling back: %s",
                    provider_name, exc
                )
                last_error = exc
                continue
            except Exception as exc:
                log.warning(
                    "Provider %s unexpected error, falling back: %s",
                    provider_name, exc
                )
                last_error = exc
                continue
        
        raise OllamaError(f"All providers failed. Last error: {last_error}")


@dataclass(slots=True)
class OllamaPlanner:
    client: OllamaClient

    def create_plan(self, request: TaskRequest) -> ChangePlan:
        prompt = f"""You are the planning engine of LUMINA Code Builder V2.
Return ONLY JSON matching this schema:
{{"summary":"...","changes":[{{"path":"relative/path","operation":"create|modify|delete","reason":"..."}}],"validation_commands":["..."]}}
Rules: every required file must be listed; use repository-relative paths only; do not invent unrelated files; include focused validation commands.
For static HTML/CSS/JS files (no build step, no package.json), use ONLY simple file existence checks like ["ls index.html", "test -f index.html"] or empty array [].
Do NOT include commands that start servers, run tests, or require dependencies (npm, python -m http.server, playwright, etc.).
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
        max_schema_retries = 2
        current_prompt = prompt
        
        for attempt in range(max_schema_retries + 1):
            data = self.client.generate_json(current_prompt, request.model)
            
            # Validate schema
            is_valid, schema_error = _validate_changes_schema(data, log)
            if is_valid:
                raw_changes = data.get("changes", [])
                changes: list[ProposedFileChange] = []
                for item in raw_changes:
                    changes.append(
                        ProposedFileChange(
                            path=str(item.get("path", "")),
                            operation=str(item.get("operation", "")),
                            content=item.get("content"),
                        )
                    )
                return changes
            
            # Schema validation failed - try recovery
            log.warning(
                "Schema validation failed (attempt %d/%d): %s",
                attempt + 1, max_schema_retries + 1, schema_error
            )
            
            if attempt < max_schema_retries:
                current_prompt = _build_schema_recovery_prompt(prompt, json.dumps(data), schema_error, attempt)
                continue
            
            # Schema retries exhausted - raise to trigger provider fallback
            raise JSONRecoveryError(
                f"Schema validation failed after {max_schema_retries + 1} attempts: {schema_error}"
            )
