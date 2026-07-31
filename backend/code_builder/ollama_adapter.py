"""Synchronous compatibility adapter for LUMINA Code Builder.

This adapter lets the synchronous TaskService call the asynchronous-oriented
OllamaService safely without modifying ollama_service.py.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any, Final
from urllib.parse import urlparse


DEFAULT_MODEL: Final[str] = "qwen2.5-coder:7b"
DEFAULT_BASE_URL: Final[str] = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT_SECONDS: Final[float] = 300.0
MAX_ERROR_BODY_CHARACTERS: Final[int] = 4_000


class OllamaTaskAdapterError(RuntimeError):
    """Raised when Code Builder cannot obtain an analysis from Ollama."""


class OllamaTaskAdapter:
    """Expose synchronous analysis methods expected by TaskService.

    Unknown attributes are delegated to the wrapped OllamaService instance,
    preserving compatibility with services that need its existing methods.
    """

    def __init__(
        self,
        ollama_service: Any,
        *,
        model: str = DEFAULT_MODEL,
    ) -> None:
        if ollama_service is None:
            raise ValueError("ollama_service cannot be None.")

        normalized_model = str(model).strip()
        if not normalized_model:
            raise ValueError("model cannot be empty.")

        self._ollama_service = ollama_service
        self._model = normalized_model

    @property
    def wrapped_service(self) -> Any:
        """Return the original OllamaService instance."""

        return self._ollama_service

    @property
    def model(self) -> str:
        """Return the local Ollama model used for Code Builder analysis."""

        return self._model

    def __getattr__(self, name: str) -> Any:
        """Delegate all unknown attributes to the wrapped service."""

        return getattr(self._ollama_service, name)

    @staticmethod
    def _check_cancellation(cancellation_token: Any) -> None:
        if cancellation_token is None:
            return

        raise_if_cancelled = getattr(
            cancellation_token,
            "raise_if_cancelled",
            None,
        )
        if callable(raise_if_cancelled):
            raise_if_cancelled()
            return

        is_cancelled = getattr(
            cancellation_token,
            "is_cancelled",
            None,
        )
        if callable(is_cancelled) and is_cancelled():
            raise OllamaTaskAdapterError(
                "Code Builder analysis was cancelled."
            )

    @staticmethod
    def _serialize_value(value: Any) -> str:
        if value is None:
            return ""

        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            value = model_dump(mode="json")

        if isinstance(value, str):
            return value

        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _normalize_sequence(
        values: Sequence[Any] | None,
    ) -> tuple[str, ...]:
        if values is None:
            return ()

        if isinstance(values, (str, bytes, bytearray)):
            return (str(values),)

        return tuple(str(value) for value in values)

    def _resolve_base_url(self) -> str:
        configuration = getattr(
            self._ollama_service,
            "configuration",
            None,
        )
        configured_base_url = getattr(
            configuration,
            "base_url",
            None,
        )

        raw_base_url = (
            os.environ.get("OLLAMA_HOST")
            or configured_base_url
            or DEFAULT_BASE_URL
        )

        base_url = str(raw_base_url).strip().rstrip("/")
        if not base_url:
            base_url = DEFAULT_BASE_URL

        if "://" not in base_url:
            base_url = f"http://{base_url}"

        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"}:
            raise OllamaTaskAdapterError(
                f"Unsupported Ollama URL scheme: {parsed.scheme!r}."
            )

        if not parsed.hostname:
            raise OllamaTaskAdapterError(
                "The Ollama base URL does not contain a hostname."
            )

        return base_url

    @staticmethod
    def _resolve_timeout(timeout_seconds: Any) -> float:
        if timeout_seconds is None:
            return DEFAULT_TIMEOUT_SECONDS

        try:
            timeout = float(timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise OllamaTaskAdapterError(
                "timeout_seconds must be a positive number."
            ) from exc

        if timeout <= 0:
            raise OllamaTaskAdapterError(
                "timeout_seconds must be greater than zero."
            )

        return timeout

    def _build_prompt(
        self,
        *,
        instruction: str,
        repository_context: Any,
        user_context: Any,
        target_paths: Sequence[Any] | None,
        excluded_paths: Sequence[Any] | None,
    ) -> str:
        targets = self._normalize_sequence(target_paths)
        exclusions = self._normalize_sequence(excluded_paths)

        target_text = (
            "\n".join(f"- {path}" for path in targets)
            if targets
            else "- Entire allowed repository scope"
        )
        excluded_text = (
            "\n".join(f"- {path}" for path in exclusions)
            if exclusions
            else "- None"
        )

        return (
            "You are the local code-analysis engine for LUMINA Code Builder.\n"
            "Analyze the request and repository context carefully.\n"
            "Do not modify, create, rename, move, or delete any files.\n"
            "Do not claim that commands were executed.\n"
            "Return a practical technical analysis followed by a safe, "
            "ordered implementation plan.\n"
            "Clearly identify risks, assumptions, affected files, and "
            "validation steps.\n\n"
            f"USER INSTRUCTION:\n{instruction.strip()}\n\n"
            f"USER CONTEXT:\n"
            f"{self._serialize_value(user_context)}\n\n"
            f"TARGET PATHS:\n{target_text}\n\n"
            f"EXCLUDED PATHS:\n{excluded_text}\n\n"
            f"REPOSITORY CONTEXT:\n"
            f"{self._serialize_value(repository_context)}\n"
        )

    def _request_analysis(
        self,
        *,
        prompt: str,
        timeout_seconds: float,
        cancellation_token: Any,
    ) -> str:
        self._check_cancellation(cancellation_token)

        endpoint = f"{self._resolve_base_url()}/api/generate"
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": "5m",
        }

        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout_seconds,
            ) as response:
                response_body = response.read().decode(
                    "utf-8",
                    errors="replace",
                )
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode(
                "utf-8",
                errors="replace",
            )
            error_body = error_body[:MAX_ERROR_BODY_CHARACTERS]
            raise OllamaTaskAdapterError(
                f"Ollama returned HTTP {exc.code}: {error_body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise OllamaTaskAdapterError(
                "LUMINA could not connect to the local Ollama service at "
                f"{endpoint}. Start Ollama and try again."
            ) from exc
        except TimeoutError as exc:
            raise OllamaTaskAdapterError(
                "Ollama did not complete the analysis before the timeout."
            ) from exc
        except OSError as exc:
            raise OllamaTaskAdapterError(
                f"Ollama request failed: {exc}"
            ) from exc

        self._check_cancellation(cancellation_token)

        try:
            response_payload = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise OllamaTaskAdapterError(
                "Ollama returned an invalid JSON response."
            ) from exc

        if not isinstance(response_payload, Mapping):
            raise OllamaTaskAdapterError(
                "Ollama returned an unexpected response structure."
            )

        error_message = response_payload.get("error")
        if isinstance(error_message, str) and error_message.strip():
            raise OllamaTaskAdapterError(
                f"Ollama returned an error: {error_message.strip()}"
            )

        generated_text = response_payload.get("response")
        if not isinstance(generated_text, str):
            raise OllamaTaskAdapterError(
                "Ollama response did not contain generated text."
            )

        normalized_text = generated_text.strip()
        if not normalized_text:
            raise OllamaTaskAdapterError(
                "Ollama returned an empty analysis."
            )

        return normalized_text

    def analyze_code_task(
        self,
        instruction: str | None = None,
        repository_context: Any = None,
        user_context: Any = None,
        target_paths: Sequence[Any] | None = None,
        excluded_paths: Sequence[Any] | None = None,
        timeout_seconds: float | None = None,
        cancellation_token: Any = None,
        task: Any = None,
        prompt: str | None = None,
        context: Any = None,
        **_: Any,
    ) -> str:
        """Analyze one Code Builder task synchronously."""

        selected_instruction = instruction or prompt
        if not selected_instruction and task is not None:
            selected_instruction = getattr(
                task,
                "instruction",
                None,
            )

        if not isinstance(selected_instruction, str):
            selected_instruction = str(
                selected_instruction
                or "Analyze the supplied Code Builder task."
            )

        if repository_context is None:
            repository_context = context

        if user_context is None and task is not None:
            user_context = getattr(task, "context", None)

        if target_paths is None and task is not None:
            target_paths = getattr(task, "target_paths", None)

        if excluded_paths is None and task is not None:
            excluded_paths = getattr(task, "excluded_paths", None)

        timeout = self._resolve_timeout(timeout_seconds)
        analysis_prompt = self._build_prompt(
            instruction=selected_instruction,
            repository_context=repository_context,
            user_context=user_context,
            target_paths=target_paths,
            excluded_paths=excluded_paths,
        )

        return self._request_analysis(
            prompt=analysis_prompt,
            timeout_seconds=timeout,
            cancellation_token=cancellation_token,
        )

    def analyze_task(self, *args: Any, **kwargs: Any) -> str:
        return self.analyze_code_task(*args, **kwargs)

    def analyze(self, *args: Any, **kwargs: Any) -> str:
        return self.analyze_code_task(*args, **kwargs)

    def generate_analysis(self, *args: Any, **kwargs: Any) -> str:
        return self.analyze_code_task(*args, **kwargs)

    def complete(self, *args: Any, **kwargs: Any) -> str:
        return self.analyze_code_task(*args, **kwargs)


def create_ollama_task_adapter(
    ollama_service: Any,
    *,
    model: str = DEFAULT_MODEL,
) -> OllamaTaskAdapter:
    """Create the synchronous Code Builder compatibility adapter."""

    return OllamaTaskAdapter(
        ollama_service,
        model=model,
    )


__all__ = [
    "DEFAULT_MODEL",
    "OllamaTaskAdapter",
    "OllamaTaskAdapterError",
    "create_ollama_task_adapter",
]
