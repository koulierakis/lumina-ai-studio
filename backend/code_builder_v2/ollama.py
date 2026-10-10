from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from .applier import ProposedFileChange
from .models import ChangePlan, GenerationProgress, TaskRequest
from .planner import PlannerUnavailable
from .security import normalize_relative_path
from .transaction import TransactionValidationError, _normalise_operation

log = logging.getLogger(__name__)


def _reconcile_changes(
    plan: ChangePlan, proposed: list[ProposedFileChange]
) -> tuple[list[ProposedFileChange], set[str], set[str]]:
    """Force generated changes to match the approved plan exactly.

    Returns ``(reconciled, missing, dropped)`` where:
      * ``reconciled`` contains one change per produced planned path, in plan
        order, with the operation coerced to the approved operation;
      * ``missing`` is the set of planned paths the model failed to produce;
      * ``dropped`` is the set of unplanned paths the model tried to add.

    This never writes an unplanned file and never silently skips a planned one
    — it hands ``missing`` back to the caller so the deviation is handled
    explicitly (bounded re-generation, then a loud failure), while the strict
    validator in transaction.py stays the single source of truth.
    """
    planned_ops: dict[str, str] = {}
    order: list[str] = []
    for item in plan.changes:
        p = normalize_relative_path(item.path)
        if p not in planned_ops:
            order.append(p)
        planned_ops[p] = _normalise_operation(item.operation)

    produced: dict[str, ProposedFileChange] = {}
    dropped: set[str] = set()
    for ch in proposed:
        try:
            p = normalize_relative_path(ch.path)
        except Exception:
            dropped.add(ch.path)
            continue
        if p not in planned_ops:
            dropped.add(ch.path)
            continue
        produced[p] = ch  # last write wins (dedupe)

    reconciled: list[ProposedFileChange] = []
    for p in order:
        ch = produced.get(p)
        if ch is None:
            continue
        op = planned_ops[p]
        if _normalise_operation(ch.operation) != op:
            ch = ProposedFileChange(path=ch.path, operation=op, content=ch.content)
        reconciled.append(ch)

    missing = {p for p in order if p not in produced}
    return reconciled, missing, dropped



class OllamaError(RuntimeError):
    """Backward-compatible Code Builder V2 LLM error."""


class JSONRecoveryError(OllamaError):
    """Raised when JSON recovery attempts are exhausted."""


class RateLimitError(OllamaError):
    """Raised when provider rate limit (429) is hit."""

    def __init__(self, message: str, retry_after: int | None = None, provider: str | None = None, model: str | None = None):
        super().__init__(message)
        self.retry_after = retry_after
        self.provider = provider
        self.model = model


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
        model = self._groq_model(requested_model)
        use_json_mode = True

        for attempt in range(max_retries + 1):
            try:
                from groq import APIError as GroqAPIError
                from groq import Groq
                from groq import RateLimitError as GroqRateLimitError

                client = Groq(api_key=api_key, timeout=self.timeout_seconds)
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are the LUMINA Code Builder V2 engine. Return only a valid JSON object with no markdown fences.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=8192,
                    **({"response_format": {"type": "json_object"}} if use_json_mode else {}),
                )
                raw = response.choices[0].message.content
            except GroqRateLimitError as exc:
                retry_after = getattr(exc, 'retry_after', None)
                if retry_after is None:
                    headers = getattr(getattr(exc, 'response', None), 'headers', {}) or {}
                    retry_after = headers.get('retry-after')
                try:
                    retry_after = max(0, min(30, int(float(retry_after)))) if retry_after is not None else None
                except (TypeError, ValueError, OverflowError):
                    retry_after = None
                log.warning(
                    "Groq rate limit hit (attempt %d/%d), provider=groq, model=%s, retry_after=%s",
                    attempt + 1, max_retries + 1, model, retry_after
                )
                if attempt < max_retries:
                    wait_time = retry_after if retry_after is not None else min(30, 2 ** attempt * 5)
                    log.info("Waiting %ds before retry", wait_time)
                    time.sleep(wait_time)
                    continue
                raise RateLimitError(
                    f"Groq rate limit exceeded after {max_retries + 1} attempts",
                    retry_after=retry_after,
                    provider="groq",
                    model=model
                ) from exc
            except GroqAPIError as exc:
                # Groq can reject otherwise useful code as json_validate_failed
                # before returning the response. Retry once without provider-side
                # JSON mode, then parse/validate the returned JSON locally.
                status_code = getattr(exc, "status_code", None)
                if status_code == 400 and use_json_mode and attempt < max_retries:
                    body = getattr(exc, "body", None)
                    detail = str(body or exc).lower()
                    if "json_validate_failed" in detail:
                        log.warning("Groq JSON mode rejected generated content; retrying with local JSON validation")
                        use_json_mode = False
                        continue
                log.warning(
                    "Groq API error (attempt %d/%d), provider=groq, model=%s, status=%s",
                    attempt + 1, max_retries + 1, model, getattr(exc, 'status_code', 'unknown')
                )
                if attempt < max_retries and getattr(exc, 'status_code', 500) >= 500:
                    wait_time = 2 ** attempt * 5
                    log.info("Waiting %ds before retry", wait_time)
                    time.sleep(wait_time)
                    continue
                raise OllamaError(f"Groq code-model request failed: {exc}") from exc
            except Exception as exc:
                raise OllamaError(f"Groq code-model request failed: {exc}") from exc

            if not isinstance(raw, str) or not raw.strip():
                raise OllamaError("Groq returned an empty response.")


            try:
                return _extract_json_object(raw)
            except OllamaError as exc:
                log.warning(
                    "Groq JSON parse failed (attempt %d/%d): %s",
                    attempt + 1, max_retries + 1, exc
                )
                if attempt < max_retries:
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

        for attempt in range(max_retries + 1):
            try:
                from huggingface_hub import InferenceClient
                from huggingface_hub.errors import HfHubHTTPError, HFValidationError

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
            except HfHubHTTPError as exc:
                status = getattr(exc, 'response', None)
                status_code = getattr(status, 'status_code', None) if status else None
                log.warning(
                    "HF HTTP error (attempt %d/%d), provider=huggingface, model=%s, status=%s",
                    attempt + 1, max_retries + 1, model, status_code
                )
                if status_code == 429:
                    retry_after = None
                    if status and hasattr(status, 'headers'):
                        retry_after = status.headers.get('retry-after')
                    if attempt < max_retries:
                        wait_time = int(retry_after) if retry_after else (2 ** attempt * 5)
                        log.info("Waiting %ds before retry", wait_time)
                        time.sleep(wait_time)
                        continue
                    raise RateLimitError(
                        f"HF rate limit exceeded after {max_retries + 1} attempts",
                        retry_after=int(retry_after) if retry_after else None,
                        provider="huggingface",
                        model=model
                    ) from exc
                elif status_code and status_code >= 500:
                    if attempt < max_retries:
                        wait_time = 2 ** attempt * 5
                        log.info("Waiting %ds before retry", wait_time)
                        time.sleep(wait_time)
                        continue
                raise OllamaError(
                    f"Hugging Face code-model request failed for {model}: {exc}"
                ) from exc
            except HFValidationError as exc:
                # Check for specific unsupported task/provider errors
                error_msg = str(exc).lower()
                if "task" in error_msg and "not supported" in error_msg:
                    # This provider/model combo doesn't support the required task
                    # Skip to next provider immediately (don't retry)
                    raise OllamaError(
                        f"Hugging Face provider does not support required task for {model}: {exc}"
                    ) from exc
                raise OllamaError(
                    f"Hugging Face validation error for {model}: {exc}"
                ) from exc
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
        import urllib.error
        import urllib.request

        model = requested_model or self.default_model
        url = f"{self.base_url}/api/generate"

        max_retries = 2

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

    def generate_json(self, prompt: str, model: str | None = None, progress: GenerationProgress | None = None) -> dict[str, Any]:
        """Generate JSON with automatic provider fallback on failure.

        Provider priority for production: Groq -> HuggingFace
        Local Ollama is ONLY included when explicitly configured via OLLAMA_BASE_URL
        pointing to a non-localhost endpoint (for production Ollama) or when
        LUMINA_USE_LOCAL_OLLAMA=true (for local development).

        If progress is provided, skip providers that have been rate-limited.
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
            # Skip rate-limited providers if progress tracking is enabled
            if progress and progress.is_provider_rate_limited(provider_name):
                log.info("Skipping rate-limited provider: %s", provider_name)
                continue

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
            except RateLimitError as exc:
                log.warning(
                    "Provider %s rate limited, falling back: %s",
                    provider_name, exc
                )
                # Track rate-limited provider for future calls
                if progress:
                    progress.add_rate_limited_provider(provider_name)
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
Rules: every required file must be listed, INCLUDING dependency manifests (for example requirements.txt or package.json), configuration files, and any data files the application reads or writes at runtime (for example a JSON data store), so the generated project installs, runs and passes validation without adding files later; use repository-relative paths only; do not invent unrelated files.
validation_commands must contain only executable commands with an installed program as the first word (for example, "python -m pytest -q"). Never put manual instructions such as "Open index.html in a browser" in validation_commands. For a browser-only check with no executable command, return an empty list; browser verification is handled separately.
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
        progress: GenerationProgress | None = None,
    ) -> list[ProposedFileChange]:
        plan_json = plan.model_dump_json()
        context_json = json.dumps(file_context, ensure_ascii=False)

        # Determine if incremental generation is needed
        # Use incremental for 3+ files or when explicitly requested
        use_incremental = len(plan.changes) >= 3

        if use_incremental:
            changes = self._generate_incremental(request, plan, file_context, plan_json, context_json, progress)
        else:
            # Fast path: single provider call for small applications
            changes = self._generate_fast_path(request, plan, file_context, plan_json, context_json, progress)

        # Reconcile the model output against the APPROVED plan so the Builder
        # creates exactly the approved files: drop unplanned additions, coerce
        # operations, and backfill any planned file the model omitted with one
        # bounded focused pass. Never a silent deviation.
        return self._reconcile_with_plan(request, plan, file_context, changes, progress)

    def _reconcile_with_plan(
        self,
        request: TaskRequest,
        plan: ChangePlan,
        file_context: dict[str, str],
        changes: list[ProposedFileChange],
        progress: GenerationProgress | None = None,
    ) -> list[ProposedFileChange]:
        reconciled, missing, dropped = _reconcile_changes(plan, changes)
        if dropped:
            log.warning(
                "Discarding %d unplanned file(s) not in the approved plan: %s",
                len(dropped), sorted(dropped),
            )
        if missing:
            log.warning(
                "Model omitted %d planned file(s); running one bounded focused pass: %s",
                len(missing), sorted(missing),
            )
            subset_plan = plan.model_copy(update={
                "changes": [
                    c for c in plan.changes
                    if normalize_relative_path(c.path) in missing
                ]
            })
            subset_context = {
                k: v for k, v in file_context.items()
                if normalize_relative_path(k) in missing
            }
            extra = self._generate_fast_path(
                request, subset_plan, subset_context,
                subset_plan.model_dump_json(),
                json.dumps(subset_context, ensure_ascii=False),
                progress,
            )
            reconciled, missing, dropped2 = _reconcile_changes(plan, reconciled + extra)
            if dropped2:
                log.warning(
                    "Focused pass produced unplanned file(s), discarded: %s",
                    sorted(dropped2),
                )
        if missing:
            # Fail loud: the approved plan was not implemented. The caller/UI
            # can then re-plan or approve changes — but we never ship a
            # transaction that silently diverges from the plan.
            raise TransactionValidationError(
                "generation did not produce the approved files: "
                + ", ".join(sorted(missing))
                + "; the plan was not implemented faithfully"
            )
        return reconciled

    def _generate_fast_path(
        self,
        request: TaskRequest,
        plan: ChangePlan,
        file_context: dict[str, str],
        plan_json: str,
        context_json: str,
        progress: GenerationProgress | None = None,
    ) -> list[ProposedFileChange]:
        """Original fast path: generate all files in one provider call."""
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
            data = self.client.generate_json(current_prompt, request.model, progress)

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

    def _generate_incremental(
        self,
        request: TaskRequest,
        plan: ChangePlan,
        file_context: dict[str, str],
        plan_json: str,
        context_json: str,
        progress: GenerationProgress | None = None,
    ) -> list[ProposedFileChange]:
        """Generate files incrementally - batch files per provider call."""
        # Get batch size from request or use default (1 file per call)
        batch_size = getattr(request, 'batch_size', 1) or 1

        # Initialize or resume progress
        if progress is None:
            progress = GenerationProgress(total_files=len(plan.changes), batch_size=batch_size)
        else:
            progress.total_files = len(plan.changes)
            progress.batch_size = batch_size

        log.info("Using incremental generation for %d files (batch_size=%d, resume_index=%d)",
                 len(plan.changes), batch_size, progress.current_file_index)

        # Sort changes for deterministic order: creates first, then modifies, then deletes
        sorted_changes = sorted(plan.changes, key=lambda c: (c.operation != "create", c.operation != "modify", c.path))

        all_changes: list[ProposedFileChange] = []

        # Add already completed files from progress
        for path, change_data in progress.completed_files.items():
            all_changes.append(ProposedFileChange(
                path=change_data["path"],
                operation=change_data["operation"],
                content=change_data["content"],
            ))

        while not progress.is_complete():
            # Get next batch of files to generate
            batch = progress.get_next_batch(sorted_changes)
            if not batch:
                break

            log.info("Generating batch of %d files (%d/%d)", len(batch), progress.current_file_index + 1, len(sorted_changes))

            # Build prompt for this batch
            batch_context = {}
            batch_plan = {"changes": []}

            for planned_change in batch:
                file_path = planned_change.path
                operation = planned_change.operation

                if file_path in file_context and operation in {"modify", "delete"}:
                    batch_context[file_path] = file_context[file_path]

                batch_plan["changes"].append({
                    "path": file_path,
                    "operation": operation,
                    "reason": planned_change.reason
                })

            # Include previously generated files as context for dependency awareness
            for completed in progress.get_completed_changes():
                path = completed.get("path", "")
                if path and path not in batch_context:
                    batch_context[path] = completed.get("content", "") or ""

            batch_context_json = json.dumps(batch_context, ensure_ascii=False)
            batch_plan_json = json.dumps(batch_plan, ensure_ascii=False)

            file_prompt = f"""You are the implementation engine of LUMINA Code Builder V2.
Generate ONLY the specified files and return ONLY JSON:
{{"changes":[{{"path":"relative/path","operation":"create|modify|delete","content":"full file content or null for delete"}}]}}
Hard rules:
- Return exactly one change object per specified path.
- For create/modify return the COMPLETE final file content, never a diff.
- For delete content must be null.
- Do not use markdown fences.
- Consider the context of previously generated files.
Approved plan (this batch only): {batch_plan_json}
Current file context: {batch_context_json}
Original request: {request.prompt}
"""
            max_schema_retries = 2
            current_prompt = file_prompt
            batch_success = False

            for attempt in range(max_schema_retries + 1):
                try:
                    data = self.client.generate_json(current_prompt, request.model, progress)

                    # Validate schema for batch
                    is_valid, schema_error = _validate_changes_schema(data, log)
                    if is_valid:
                        raw_changes = data.get("changes", [])
                        if raw_changes:
                            batch_changes = []
                            for item in raw_changes:
                                change = ProposedFileChange(
                                    path=str(item.get("path", "")),
                                    operation=str(item.get("operation", "")),
                                    content=item.get("content"),
                                )
                                batch_changes.append(change)

                            # Verify we got the expected files
                            expected_paths = {pc.path for pc in batch}
                            actual_paths = {c.path for c in batch_changes}
                            if not expected_paths.issubset(actual_paths):
                                missing = expected_paths - actual_paths
                                log.warning("Provider missing expected files: %s", missing)

                            progress.mark_batch_completed(batch_changes)
                            all_changes.extend(batch_changes)
                            batch_success = True
                            break
                        else:
                            raise OllamaError("No changes returned for batch generation")

                    # Schema validation failed - try recovery
                    log.warning(
                        "Schema validation failed for batch (attempt %d/%d): %s",
                        attempt + 1, max_schema_retries + 1, schema_error
                    )

                    if attempt < max_schema_retries:
                        current_prompt = _build_schema_recovery_prompt(file_prompt, json.dumps(data), schema_error, attempt)
                        continue

                    # Schema retries exhausted for this batch
                    progress.mark_failed(batch[0].path if batch else "unknown")
                    raise JSONRecoveryError(
                        f"Schema validation failed for batch after {max_schema_retries + 1} attempts: {schema_error}"
                    )

                except RateLimitError as rle:
                    # Track rate-limited provider and re-raise for provider fallback
                    progress.add_rate_limited_provider(rle.provider or "unknown")
                    progress.mark_failed(batch[0].path if batch else "unknown")
                    raise
                except (JSONRecoveryError, OllamaError):
                    # Re-raise to trigger provider fallback
                    progress.mark_failed(batch[0].path if batch else "unknown")
                    raise

            if not batch_success:
                break

            # Small delay between batches to be respectful to rate limits
            if not progress.is_complete():
                time.sleep(0.5)

        if progress.failed_file:
            raise JSONRecoveryError(f"Failed to generate file: {progress.failed_file}")

        log.info("Incremental generation completed: %d files generated", len(all_changes))
        return all_changes
