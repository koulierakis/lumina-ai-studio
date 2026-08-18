from __future__ import annotations

import enum
import inspect
import threading
import time
import traceback
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import models as domain_models
from .backup_service import (
    BackupService,
)
from .build_service import (
    BuildCommandResult,
    BuildCommandSpec,
    BuildExecutionOptions,
    BuildSequenceResult,
    BuildService,
    BuildStatus,
    CancellationToken,
    create_default_validation_sequence,
)
from .ollama_service import OllamaService
from .patch_service import PatchService
from .patch_service import PatchRequestPayload
from .planning_service import PlanningService
from .repository_service import RepositoryService
from .security import (
    SecurityError,
)


DEFAULT_TASK_TIMEOUT_SECONDS: Final[float] = 3600.0
DEFAULT_ANALYSIS_TIMEOUT_SECONDS: Final[float] = 300.0
DEFAULT_PLANNING_TIMEOUT_SECONDS: Final[float] = 600.0
DEFAULT_PATCH_TIMEOUT_SECONDS: Final[float] = 900.0
DEFAULT_BUILD_TIMEOUT_SECONDS: Final[float] = 1800.0
DEFAULT_ROLLBACK_TIMEOUT_SECONDS: Final[float] = 300.0
DEFAULT_MAX_TASK_DESCRIPTION_LENGTH: Final[int] = 100_000
DEFAULT_MAX_CONTEXT_LENGTH: Final[int] = 500_000
DEFAULT_MAX_EVENT_COUNT: Final[int] = 2000
DEFAULT_MAX_ERROR_MESSAGE_LENGTH: Final[int] = 20_000

T = TypeVar("T")


class TaskServiceError(RuntimeError):
    """Base exception for Code Builder orchestration failures."""


class TaskConfigurationError(TaskServiceError):
    """Raised when the orchestrator or one of its dependencies is invalid."""


class TaskValidationError(TaskServiceError):
    """Raised when an incoming task fails validation."""


class TaskSecurityError(TaskValidationError):
    """Raised when a task violates a repository or security restriction."""


class TaskAnalysisError(TaskServiceError):
    """Raised when repository or task analysis cannot be completed."""


class TaskPlanningError(TaskServiceError):
    """Raised when a safe executable implementation plan cannot be produced."""


class TaskBackupError(TaskServiceError):
    """Raised when a required repository backup cannot be created."""


class TaskPatchError(TaskServiceError):
    """Raised when a patch cannot be generated, validated or applied."""


class TaskBuildError(TaskServiceError):
    """Raised when validation commands fail after patch application."""


class TaskRollbackError(TaskServiceError):
    """Raised when rollback fails after an unsuccessful task."""


class TaskCancellationError(TaskServiceError):
    """Raised when orchestration is cancelled."""

    def __init__(
        self,
        message: str = "Code Builder task was cancelled.",
        *,
        task_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.task_id = task_id


class TaskTimeoutError(TaskServiceError):
    """Raised when the overall task exceeds its allowed duration."""

    def __init__(
        self,
        message: str,
        *,
        timeout_seconds: float,
        task_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.timeout_seconds = timeout_seconds
        self.task_id = task_id


class TaskDependencyError(TaskServiceError):
    """Raised when a service does not expose a compatible required operation."""


class TaskResultMappingError(TaskServiceError):
    """Raised when internal results cannot be mapped to models.py."""


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    VALIDATING = "validating"
    ANALYZING = "analyzing"
    PLANNING = "planning"
    BACKING_UP = "backing_up"
    GENERATING_PATCH = "generating_patch"
    VALIDATING_PATCH = "validating_patch"
    APPLYING_PATCH = "applying_patch"
    BUILDING = "building"
    ROLLING_BACK = "rolling_back"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"
    DRY_RUN = "dry_run"


class TaskStage(str, enum.Enum):
    VALIDATION = "validation"
    ANALYSIS = "analysis"
    PLANNING = "planning"
    BACKUP = "backup"
    PATCH_GENERATION = "patch_generation"
    PATCH_VALIDATION = "patch_validation"
    PATCH_APPLICATION = "patch_application"
    BUILD = "build"
    ROLLBACK = "rollback"
    COMPLETION = "completion"


class TaskEventLevel(str, enum.Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class RollbackPolicy(str, enum.Enum):
    NEVER = "never"
    ON_PATCH_FAILURE = "on_patch_failure"
    ON_BUILD_FAILURE = "on_build_failure"
    ON_ANY_FAILURE = "on_any_failure"


class BackupPolicy(str, enum.Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    DISABLED = "disabled"


class BuildPolicy(str, enum.Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    DISABLED = "disabled"


class TaskRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_assignment=True,
        str_strip_whitespace=True,
    )

    task_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        min_length=1,
        max_length=128,
    )
    instruction: str = Field(
        min_length=1,
        max_length=DEFAULT_MAX_TASK_DESCRIPTION_LENGTH,
    )
    context: str | None = Field(
        default=None,
        max_length=DEFAULT_MAX_CONTEXT_LENGTH,
    )
    target_paths: tuple[str, ...] = Field(default_factory=tuple)
    excluded_paths: tuple[str, ...] = Field(default_factory=tuple)
    build_commands: tuple[BuildCommandSpec, ...] = Field(
        default_factory=tuple
    )
    task_timeout_seconds: float = Field(
        default=DEFAULT_TASK_TIMEOUT_SECONDS,
        gt=0.0,
        le=86_400.0,
    )
    dry_run: bool = False
    allow_file_creation: bool = True
    allow_file_deletion: bool = False
    require_clean_repository: bool = False
    stop_build_on_first_failure: bool = True
    backup_policy: BackupPolicy = BackupPolicy.REQUIRED
    build_policy: BuildPolicy = BuildPolicy.REQUIRED
    rollback_policy: RollbackPolicy = RollbackPolicy.ON_ANY_FAILURE
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, value: str) -> str:
        allowed = set(
            "abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "0123456789"
            "_.:-"
        )

        if not value or value[0] not in allowed:
            raise ValueError("task_id cannot be empty.")

        if any(character not in allowed for character in value):
            raise ValueError(
                "task_id may contain only letters, digits, underscores, "
                "periods, colons and hyphens."
            )

        return value

    @field_validator("instruction")
    @classmethod
    def validate_instruction(cls, value: str) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError("instruction cannot be empty.")

        if "\x00" in normalized:
            raise ValueError(
                "instruction contains a forbidden null character."
            )

        return normalized

    @field_validator("context")
    @classmethod
    def validate_context(cls, value: str | None) -> str | None:
        if value is None:
            return None

        if "\x00" in value:
            raise ValueError(
                "context contains a forbidden null character."
            )

        return value

    @field_validator("target_paths", "excluded_paths")
    @classmethod
    def validate_paths(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized: list[str] = []

        for raw_path in value:
            path_text = raw_path.strip()

            if not path_text:
                raise ValueError("Task paths cannot be empty.")

            if "\x00" in path_text:
                raise ValueError(
                    "Task path contains a forbidden null character."
                )

            normalized.append(path_text)

        return tuple(normalized)


class TaskServiceConfiguration(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_assignment=True,
    )

    repository_root: Path
    analysis_timeout_seconds: float = Field(
        default=DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
        gt=0.0,
        le=86_400.0,
    )
    planning_timeout_seconds: float = Field(
        default=DEFAULT_PLANNING_TIMEOUT_SECONDS,
        gt=0.0,
        le=86_400.0,
    )
    patch_timeout_seconds: float = Field(
        default=DEFAULT_PATCH_TIMEOUT_SECONDS,
        gt=0.0,
        le=86_400.0,
    )
    build_timeout_seconds: float = Field(
        default=DEFAULT_BUILD_TIMEOUT_SECONDS,
        gt=0.0,
        le=86_400.0,
    )
    rollback_timeout_seconds: float = Field(
        default=DEFAULT_ROLLBACK_TIMEOUT_SECONDS,
        gt=0.0,
        le=86_400.0,
    )
    max_event_count: int = Field(
        default=DEFAULT_MAX_EVENT_COUNT,
        ge=10,
        le=100_000,
    )
    use_default_build_sequence: bool = True
    default_backend_directory: str = "backend"
    default_frontend_directory: str = "frontend"
    include_ruff: bool = True
    include_mypy: bool = True
    include_frontend_tests: bool = True
    include_frontend_build: bool = True

    @field_validator("repository_root")
    @classmethod
    def validate_repository_root(cls, value: Path) -> Path:
        try:
            resolved = value.expanduser().resolve(strict=True)
        except FileNotFoundError as exc:
            raise ValueError(
                f"Repository root does not exist: {value}"
            ) from exc
        except OSError as exc:
            raise ValueError(
                f"Repository root cannot be resolved: {value}"
            ) from exc

        if not resolved.is_dir():
            raise ValueError(
                f"Repository root is not a directory: {resolved}"
            )

        return resolved


class TaskEvent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_assignment=True,
    )

    sequence: int = Field(ge=1)
    task_id: str
    timestamp_epoch: float
    stage: TaskStage
    status: TaskStatus
    level: TaskEventLevel
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class TaskExecutionResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )

    task_id: str
    status: TaskStatus
    instruction: str
    repository_root: str
    started_at_epoch: float
    finished_at_epoch: float
    duration_seconds: float = Field(ge=0.0)
    analysis: Any = None
    plan: Any = None
    backup: Any = None
    patch: Any = None
    patch_validation: Any = None
    patch_application: Any = None
    build_result: BuildSequenceResult | None = None
    rollback_result: Any = None
    changed_paths: tuple[str, ...] = Field(default_factory=tuple)
    events: tuple[TaskEvent, ...] = Field(default_factory=tuple)
    error_type: str | None = None
    error_message: str | None = None
    rollback_attempted: bool = False
    rollback_succeeded: bool = False
    dry_run: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.status in {
            TaskStatus.SUCCEEDED,
            TaskStatus.DRY_RUN,
        }


class TaskEventCallback(Protocol):
    def __call__(self, event: TaskEvent) -> None:
        """Receive one immutable orchestration event."""


@dataclass(slots=True)
class TaskCancellationToken:
    task_id: str
    _event: threading.Event = field(
        default_factory=threading.Event,
        init=False,
        repr=False,
    )
    _reason: str | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )
    build_token: CancellationToken = field(
        default_factory=CancellationToken,
        init=False,
        repr=False,
    )

    def cancel(self, reason: str | None = None) -> None:
        with self._lock:
            if reason and not self._reason:
                self._reason = reason

        self._event.set()
        self.build_token.cancel(reason)

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    @property
    def reason(self) -> str | None:
        with self._lock:
            return self._reason

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise TaskCancellationError(
                self.reason or "Code Builder task was cancelled.",
                task_id=self.task_id,
            )


@dataclass(slots=True)
class TaskExecutionContext:
    request: TaskRequest
    configuration: TaskServiceConfiguration
    cancellation_token: TaskCancellationToken
    started_at_epoch: float = field(default_factory=time.time)
    started_monotonic: float = field(default_factory=time.monotonic)
    status: TaskStatus = TaskStatus.PENDING
    analysis: Any = None
    plan: Any = None
    backup: Any = None
    patch: Any = None
    patch_validation: Any = None
    patch_application: Any = None
    build_result: BuildSequenceResult | None = None
    rollback_result: Any = None
    changed_paths: tuple[str, ...] = field(default_factory=tuple)
    rollback_attempted: bool = False
    rollback_succeeded: bool = False
    events: list[TaskEvent] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    error: BaseException | None = None

    def elapsed_seconds(self) -> float:
        return max(0.0, time.monotonic() - self.started_monotonic)

    def remaining_seconds(self) -> float:
        remaining = (
            self.request.task_timeout_seconds
            - self.elapsed_seconds()
        )
        return max(0.0, remaining)

    def raise_if_interrupted(self) -> None:
        self.cancellation_token.raise_if_cancelled()

        if self.elapsed_seconds() >= self.request.task_timeout_seconds:
            raise TaskTimeoutError(
                (
                    f"Task {self.request.task_id!r} exceeded its timeout "
                    f"of {self.request.task_timeout_seconds:.3f} seconds."
                ),
                timeout_seconds=self.request.task_timeout_seconds,
                task_id=self.request.task_id,
            )


class _EventRecorder:
    def __init__(
        self,
        *,
        task_id: str,
        max_events: int,
        callback: TaskEventCallback | None,
    ) -> None:
        self._task_id = task_id
        self._max_events = max_events
        self._callback = callback
        self._sequence = 0
        self._events: list[TaskEvent] = []
        self._lock = threading.RLock()

    def add(
        self,
        *,
        stage: TaskStage,
        status: TaskStatus,
        level: TaskEventLevel,
        message: str,
        details: Mapping[str, Any] | None = None,
    ) -> TaskEvent:
        with self._lock:
            self._sequence += 1

            event = TaskEvent(
                sequence=self._sequence,
                task_id=self._task_id,
                timestamp_epoch=time.time(),
                stage=stage,
                status=status,
                level=level,
                message=message,
                details=dict(details or {}),
            )

            self._events.append(event)

            if len(self._events) > self._max_events:
                overflow = len(self._events) - self._max_events
                del self._events[:overflow]

        if self._callback is not None:
            try:
                self._callback(event)
            except Exception:
                pass

        return event

    def snapshot(self) -> tuple[TaskEvent, ...]:
        with self._lock:
            return tuple(self._events)


def _safe_error_message(error: BaseException) -> str:
    message = str(error).strip()

    if not message:
        message = type(error).__name__

    if len(message) > DEFAULT_MAX_ERROR_MESSAGE_LENGTH:
        message = (
            message[:DEFAULT_MAX_ERROR_MESSAGE_LENGTH]
            + " [TRUNCATED]"
        )

    return message


def _safe_traceback(error: BaseException) -> str:
    rendered = "".join(
        traceback.format_exception(
            type(error),
            error,
            error.__traceback__,
        )
    )

    if len(rendered) > DEFAULT_MAX_ERROR_MESSAGE_LENGTH:
        return (
            rendered[:DEFAULT_MAX_ERROR_MESSAGE_LENGTH]
            + "\n[TRACEBACK TRUNCATED]"
        )

    return rendered


def _field_names(model_type: type[Any]) -> frozenset[str]:
    pydantic_fields = getattr(model_type, "model_fields", None)

    if isinstance(pydantic_fields, Mapping):
        return frozenset(pydantic_fields.keys())

    dataclass_fields = getattr(
        model_type,
        "__dataclass_fields__",
        None,
    )

    if isinstance(dataclass_fields, Mapping):
        return frozenset(dataclass_fields.keys())

    annotations = getattr(model_type, "__annotations__", None)

    if isinstance(annotations, Mapping):
        return frozenset(annotations.keys())

    return frozenset()


def _instantiate_compatible_model(
    model_type: type[T],
    payload: Mapping[str, Any],
) -> T:
    fields = _field_names(model_type)

    filtered_payload = (
        {
            key: value
            for key, value in payload.items()
            if key in fields
        }
        if fields
        else dict(payload)
    )

    model_validate = getattr(model_type, "model_validate", None)

    if callable(model_validate):
        return cast(T, model_validate(filtered_payload))

    try:
        return model_type(**filtered_payload)
    except TypeError:
        from_dict = getattr(model_type, "from_dict", None)

        if callable(from_dict):
            return cast(T, from_dict(filtered_payload))

        raise


def _find_domain_model(
    candidate_names: Sequence[str],
) -> type[Any] | None:
    for candidate_name in candidate_names:
        candidate = getattr(
            domain_models,
            candidate_name,
            None,
        )

        if isinstance(candidate, type):
            return candidate

    return None


def _extract_value(
    source: Any,
    candidate_names: Sequence[str],
    *,
    default: Any = None,
) -> Any:
    if source is None:
        return default

    if isinstance(source, Mapping):
        for candidate_name in candidate_names:
            if candidate_name in source:
                return source[candidate_name]

        return default

    for candidate_name in candidate_names:
        if hasattr(source, candidate_name):
            return getattr(source, candidate_name)

    return default


def _extract_boolean(
    source: Any,
    candidate_names: Sequence[str],
    *,
    default: bool = False,
) -> bool:
    value = _extract_value(
        source,
        candidate_names,
        default=default,
    )

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        normalized = value.strip().casefold()

        if normalized in {
            "true",
            "yes",
            "1",
            "success",
            "succeeded",
            "valid",
            "ok",
            "completed",
        }:
            return True

        if normalized in {
            "false",
            "no",
            "0",
            "failed",
            "invalid",
            "error",
        }:
            return False

    if isinstance(value, int):
        return value != 0

    return bool(value)


def _extract_paths(source: Any) -> tuple[str, ...]:
    value = _extract_value(
        source,
        (
            "changed_paths",
            "modified_paths",
            "affected_paths",
            "files",
            "file_paths",
            "paths",
            "operations",
            "results",
        ),
        default=(),
    )

    if value is None:
        return ()

    if isinstance(value, str):
        return (value,)

    if isinstance(value, Sequence):
        paths: list[str] = []

        for item in value:
            if isinstance(item, str):
                paths.append(item)
                continue

            nested_path = _extract_value(
                item,
                (
                    "path",
                    "file_path",
                    "relative_path",
                    "target_path",
                ),
            )

            if nested_path is not None:
                paths.append(str(nested_path))

        return tuple(dict.fromkeys(paths))

    return ()


def _extract_backup_id(source: Any) -> str | None:
    value = _extract_value(
        source,
        (
            "backup_id",
            "id",
            "snapshot_id",
        ),
    )

    if value is None:
        return None

    return str(value)


def _extract_plan_operation_paths(plan: Any) -> frozenset[str]:
    return frozenset(_extract_paths(plan))


def _build_patch_request_from_metadata(
    context: TaskExecutionContext,
) -> PatchRequestPayload | None:
    raw_operations = _extract_value(
        context.request.metadata,
        (
            "patch_operations",
            "execution_patch_operations",
            "approved_patch_operations",
        ),
    )

    if raw_operations is None:
        return None

    if not isinstance(raw_operations, Sequence) or isinstance(
        raw_operations,
        (str, bytes),
    ):
        raise TaskPatchError(
            "metadata.patch_operations must be a sequence."
        )

    payload = PatchRequestPayload.model_validate(
        {
            "operations": list(raw_operations),
            "dry_run": context.request.dry_run,
            "rollback_on_failure": True,
            "description": (
                "Approved GeneratedChangePlan execution for task "
                f"{context.request.task_id}."
            ),
        }
    )

    planned_paths = _extract_plan_operation_paths(context.plan)

    if planned_paths:
        operation_paths = frozenset(_extract_paths(payload))
        unexpected_paths = sorted(operation_paths - planned_paths)

        if unexpected_paths:
            raise TaskPatchError(
                "Patch operations include paths not present in the "
                "approved GeneratedChangePlan: "
                + ", ".join(unexpected_paths)
            )

    return payload


def _method_accepts_kwargs(
    method: Callable[..., Any],
) -> bool:
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return True

    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def _filter_method_kwargs(
    method: Callable[..., Any],
    values: Mapping[str, Any],
) -> dict[str, Any]:
    if _method_accepts_kwargs(method):
        return dict(values)

    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return dict(values)

    accepted_names = {
        name
        for name, parameter in signature.parameters.items()
        if name != "self"
        and parameter.kind
        in {
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }
    }

    return {
        key: value
        for key, value in values.items()
        if key in accepted_names
    }


def _call_compatible_method(
    service: Any,
    method_names: Sequence[str],
    *,
    keyword_variants: Sequence[Mapping[str, Any]],
    positional_variants: Sequence[Sequence[Any]] = (),
    operation_name: str,
) -> Any:
    compatible_method_found = False
    last_type_error: TypeError | None = None

    for method_name in method_names:
        method = getattr(service, method_name, None)

        if not callable(method):
            continue

        compatible_method_found = True

        for raw_kwargs in keyword_variants:
            kwargs = _filter_method_kwargs(
                method,
                raw_kwargs,
            )

            try:
                return method(**kwargs)
            except TypeError as exc:
                last_type_error = exc
                continue

        for arguments in positional_variants:
            try:
                return method(*arguments)
            except TypeError as exc:
                last_type_error = exc
                continue

    if not compatible_method_found:
        raise TaskDependencyError(
            f"Service {type(service).__name__} does not expose a "
            f"compatible method for {operation_name}."
        )

    raise TaskDependencyError(
        f"Could not call {operation_name} on "
        f"{type(service).__name__} with a compatible signature."
        + (
            f" Last signature error: {last_type_error}"
            if last_type_error is not None
            else ""
        )
    )


def _remaining_stage_timeout(
    context: TaskExecutionContext,
    configured_timeout: float,
) -> float:
    context.raise_if_interrupted()

    remaining = context.remaining_seconds()

    if remaining <= 0:
        raise TaskTimeoutError(
            (
                f"Task {context.request.task_id!r} has no remaining "
                "execution time."
            ),
            timeout_seconds=context.request.task_timeout_seconds,
            task_id=context.request.task_id,
        )

    return min(configured_timeout, remaining)


def _normalize_repository_path(
    repository_root: Path,
    path_text: str,
    *,
    must_exist: bool,
) -> Path:
    candidate = Path(path_text).expanduser()

    if not candidate.is_absolute():
        candidate = repository_root / candidate

    try:
        resolved = candidate.resolve(strict=must_exist)
    except FileNotFoundError as exc:
        raise TaskValidationError(
            f"Repository path does not exist: {path_text!r}."
        ) from exc
    except OSError as exc:
        raise TaskValidationError(
            f"Repository path cannot be resolved: {path_text!r}."
        ) from exc

    try:
        resolved.relative_to(repository_root)
    except ValueError as exc:
        raise TaskSecurityError(
            f"Task path escapes repository root: {path_text!r}."
        ) from exc

    return resolved


def _validate_task_paths(
    request: TaskRequest,
    *,
    repository_root: Path,
) -> None:
    for target_path in request.target_paths:
        _normalize_repository_path(
            repository_root,
            target_path,
            must_exist=not request.allow_file_creation,
        )

    for excluded_path in request.excluded_paths:
        _normalize_repository_path(
            repository_root,
            excluded_path,
            must_exist=False,
        )


def _validate_task_with_security_service(
    request: TaskRequest,
    *,
    repository_root: Path,
) -> None:
    from . import security

    candidate_hooks = (
        "validate_code_builder_task",
        "validate_task",
        "ensure_safe_task",
        "assert_safe_task",
        "validate_repository_operation",
    )

    for hook_name in candidate_hooks:
        hook = getattr(security, hook_name, None)

        if not callable(hook):
            continue

        keyword_variants = (
            {
                "task": request,
                "repository_root": repository_root,
            },
            {
                "request": request,
                "repository_root": repository_root,
            },
            {
                "instruction": request.instruction,
                "target_paths": request.target_paths,
                "excluded_paths": request.excluded_paths,
                "repository_root": repository_root,
                "allow_file_creation": request.allow_file_creation,
                "allow_file_deletion": request.allow_file_deletion,
            },
        )

        for raw_kwargs in keyword_variants:
            kwargs = _filter_method_kwargs(hook, raw_kwargs)

            try:
                result = hook(**kwargs)
            except TypeError:
                continue
            except SecurityError as exc:
                raise TaskSecurityError(str(exc)) from exc
            except Exception as exc:
                raise TaskSecurityError(
                    f"security.{hook_name} rejected task "
                    f"{request.task_id!r}: {exc}"
                ) from exc

            if result is False:
                raise TaskSecurityError(
                    f"security.{hook_name} rejected task "
                    f"{request.task_id!r}."
                )

            return


def _validate_repository_state(
    repository_service: RepositoryService,
    request: TaskRequest,
) -> Any:
    if not request.require_clean_repository:
        return None

    state = _call_compatible_method(
        repository_service,
        (
            "get_status",
            "status",
            "inspect_status",
            "get_repository_status",
            "snapshot_status",
        ),
        keyword_variants=(
            {},
            {"include_untracked": True},
        ),
        operation_name="repository status inspection",
    )

    is_clean = _extract_boolean(
        state,
        (
            "is_clean",
            "clean",
            "repository_clean",
        ),
        default=False,
    )

    if not is_clean:
        raise TaskValidationError(
            "Repository must be clean before this task can run."
        )

    return state


def _run_awaitable_sync(
    awaitable: Any,
    *,
    timeout_seconds: float,
    operation_name: str,
) -> Any:
    """Resolve an awaitable from the synchronous task pipeline safely."""

    import asyncio
    import inspect
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

    if not inspect.isawaitable(awaitable):
        return awaitable

    async def _runner() -> Any:
        task = asyncio.create_task(awaitable)

        done, pending = await asyncio.wait(
            {task},
            timeout=timeout_seconds,
        )

        if pending:
            task.cancel()
            try:
                await task
            except BaseException:
                pass
            raise TaskTimeoutError(
                f"{operation_name} timed out.",
                timeout_seconds=timeout_seconds,
            )

        return task.result()

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        try:
            return asyncio.run(_runner())
        except asyncio.TimeoutError as exc:
            raise TaskTimeoutError(
                f"{operation_name} timed out.",
                timeout_seconds=timeout_seconds,
            ) from exc

    def _run_in_thread() -> Any:
        return asyncio.run(_runner())

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_in_thread)
        try:
            return future.result(timeout=timeout_seconds + 5.0)
        except FutureTimeoutError as exc:
            future.cancel()
            raise TaskTimeoutError(
                f"{operation_name} timed out.",
                timeout_seconds=timeout_seconds,
            ) from exc


def _analyze_task(
    context: TaskExecutionContext,
    *,
    repository_service: RepositoryService,
    ollama_service: OllamaService,
) -> Any:
    """Build the canonical repository analysis consumed by PlanningService.

    PlanningService performs its own Ollama call. Returning free-form LLM text
    from this stage discards required repository metadata such as
    ``repository_root`` and ``files`` and therefore breaks planning.
    """

    timeout_seconds = _remaining_stage_timeout(
        context,
        context.configuration.analysis_timeout_seconds,
    )

    analysis = _call_compatible_method(
        repository_service,
        (
            "analyze_repository",
            "analyze_and_save",
            "get_or_create_index",
            "analyze",
            "build_context",
            "collect_context",
            "inspect_repository",
            "get_repository_context",
        ),
        keyword_variants=(
            {},
            {"force_reindex": False},
            {
                "instruction": context.request.instruction,
                "target_paths": context.request.target_paths,
                "excluded_paths": context.request.excluded_paths,
                "context": context.request.context,
                "timeout_seconds": timeout_seconds,
                "cancellation_token": context.cancellation_token,
            },
            {
                "task": context.request,
                "timeout_seconds": timeout_seconds,
                "cancellation_token": context.cancellation_token,
            },
        ),
        positional_variants=(),
        operation_name="repository analysis",
    )

    analysis = _run_awaitable_sync(
        analysis,
        timeout_seconds=timeout_seconds,
        operation_name="Repository analysis",
    )

    context.raise_if_interrupted()

    if analysis is None:
        raise TaskAnalysisError(
            "The repository analysis service returned no analysis."
        )

    repository_root = _extract_value(
        analysis,
        ("repository_root", "root"),
        default=None,
    )
    if repository_root is None:
        raise TaskAnalysisError(
            "Repository analysis is missing repository_root."
        )

    return analysis


def _create_plan(
    context: TaskExecutionContext,
    *,
    planning_service: PlanningService,
) -> Any:
    """Create and resolve the asynchronous PlanningService plan."""

    timeout_seconds = _remaining_stage_timeout(
        context,
        context.configuration.planning_timeout_seconds,
    )

    context.raise_if_interrupted()

    plan_method = getattr(planning_service, "plan", None)
    if not callable(plan_method):
        raise TaskDependencyError(
            "PlanningService does not expose a callable plan() method."
        )

    try:
        plan = plan_method(
            user_request=context.request.instruction,
            analysis=context.analysis,
            task_id=context.request.task_id,
            timeout_seconds=max(1.0, timeout_seconds - 1.0),
            return_normalized=False,
        )
    except TypeError as exc:
        raise TaskDependencyError(
            "Could not call PlanningService.plan() with user_request and "
            f"analysis: {_safe_error_message(exc)}"
        ) from exc

    plan = _run_awaitable_sync(
        plan,
        timeout_seconds=timeout_seconds,
        operation_name="Implementation planning",
    )

    context.raise_if_interrupted()

    if plan is None:
        raise TaskPlanningError(
            "The planning service returned no implementation plan."
        )

    plan_valid = _extract_boolean(
        plan,
        ("is_valid", "valid", "approved", "is_safe"),
        default=True,
    )
    if not plan_valid:
        reason = _extract_value(
            plan,
            (
                "error",
                "error_message",
                "reason",
                "validation_error",
            ),
            default="The implementation plan was rejected.",
        )
        raise TaskPlanningError(str(reason))

    return plan


def _create_backup(
    context: TaskExecutionContext,
    *,
    backup_service: BackupService,
) -> Any:
    if context.request.backup_policy is BackupPolicy.DISABLED:
        return None

    timeout_seconds = _remaining_stage_timeout(
        context,
        context.configuration.rollback_timeout_seconds,
    )

    planned_paths = _extract_paths(context.plan)
    paths_to_backup = (
        planned_paths
        or context.request.target_paths
        or (".",)
    )

    try:
        backup = _call_compatible_method(
            backup_service,
            (
                "create_backup",
                "backup",
                "create_snapshot",
                "snapshot",
                "backup_paths",
            ),
            keyword_variants=(
                {
                    "relative_paths": paths_to_backup,
                    "reason": (
                        "Before Code Builder task "
                        f"{context.request.task_id}"
                    ),
                    "metadata": context.request.metadata,
                },
                {
                    "task_id": context.request.task_id,
                    "paths": paths_to_backup,
                    "plan": context.plan,
                    "repository_root": (
                        context.configuration.repository_root
                    ),
                    "timeout_seconds": timeout_seconds,
                    "cancellation_token": (
                        context.cancellation_token
                    ),
                    "metadata": context.request.metadata,
                },
                {
                    "task": context.request,
                    "plan": context.plan,
                    "paths": paths_to_backup,
                },
                {
                    "backup_id": context.request.task_id,
                    "target_paths": paths_to_backup,
                },
            ),
            positional_variants=(
                (
                    context.request.task_id,
                    paths_to_backup,
                ),
                (paths_to_backup,),
            ),
            operation_name="repository backup",
        )
    except Exception:
        if context.request.backup_policy is BackupPolicy.OPTIONAL:
            return None
        raise

    if (
        backup is None
        and context.request.backup_policy is BackupPolicy.REQUIRED
    ):
        raise TaskBackupError(
            "The backup service did not return a backup reference."
        )

    backup_success = _extract_boolean(
        backup,
        (
            "success",
            "succeeded",
            "created",
            "is_valid",
        ),
        default=backup is not None,
    )

    if (
        not backup_success
        and context.request.backup_policy is BackupPolicy.REQUIRED
    ):
        reason = _extract_value(
            backup,
            (
                "error",
                "error_message",
                "reason",
            ),
            default="Repository backup failed.",
        )

        raise TaskBackupError(str(reason))

    return backup


def _generate_patch(
    context: TaskExecutionContext,
    *,
    patch_service: PatchService,
    ollama_service: OllamaService,
) -> Any:
    timeout_seconds = _remaining_stage_timeout(
        context,
        context.configuration.patch_timeout_seconds,
    )

    metadata_patch = _build_patch_request_from_metadata(context)
    if metadata_patch is not None:
        return metadata_patch

    patch = _call_compatible_method(
        patch_service,
        (
            "generate_patch",
            "create_patch",
            "build_patch",
            "prepare_patch",
        ),
        keyword_variants=(
            {
                "task": context.request,
                "analysis": context.analysis,
                "plan": context.plan,
                "ollama_service": ollama_service,
                "repository_root": (
                    context.configuration.repository_root
                ),
                "timeout_seconds": timeout_seconds,
                "cancellation_token": (
                    context.cancellation_token
                ),
            },
            {
                "instruction": context.request.instruction,
                "analysis": context.analysis,
                "plan": context.plan,
                "context": context.request.context,
                "target_paths": context.request.target_paths,
                "excluded_paths": context.request.excluded_paths,
                "allow_file_creation": (
                    context.request.allow_file_creation
                ),
                "allow_file_deletion": (
                    context.request.allow_file_deletion
                ),
                "model_service": ollama_service,
                "timeout_seconds": timeout_seconds,
            },
            {
                "request": context.request,
                "implementation_plan": context.plan,
                "analysis_result": context.analysis,
            },
        ),
        positional_variants=(
            (
                context.request,
                context.plan,
                context.analysis,
            ),
            (
                context.request.instruction,
                context.plan,
            ),
        ),
        operation_name="patch generation",
    )

    if patch is None:
        raise TaskPatchError(
            "The patch service returned no patch."
        )

    return patch


def _validate_patch(
    context: TaskExecutionContext,
    *,
    patch_service: PatchService,
) -> Any:
    timeout_seconds = _remaining_stage_timeout(
        context,
        context.configuration.patch_timeout_seconds,
    )

    if isinstance(context.patch, PatchRequestPayload):
        validation = patch_service.apply_patch(
            context.patch,
            dry_run=True,
        )

        if not validation.successful:
            raise TaskPatchError(
                validation.error or "Patch validation failed."
            )

        return validation

    validation = _call_compatible_method(
        patch_service,
        (
            "validate_patch",
            "check_patch",
            "verify_patch",
            "validate",
        ),
        keyword_variants=(
            {
                "patch": context.patch,
                "task": context.request,
                "plan": context.plan,
                "repository_root": (
                    context.configuration.repository_root
                ),
                "allow_file_creation": (
                    context.request.allow_file_creation
                ),
                "allow_file_deletion": (
                    context.request.allow_file_deletion
                ),
                "excluded_paths": context.request.excluded_paths,
                "timeout_seconds": timeout_seconds,
                "cancellation_token": (
                    context.cancellation_token
                ),
            },
            {
                "patch_result": context.patch,
                "request": context.request,
                "implementation_plan": context.plan,
            },
            {
                "patch": context.patch,
            },
        ),
        positional_variants=(
            (context.patch,),
            (
                context.patch,
                context.request,
            ),
        ),
        operation_name="patch validation",
    )

    if validation is None:
        raise TaskPatchError(
            "The patch validator returned no validation result."
        )

    is_valid = _extract_boolean(
        validation,
        (
            "is_valid",
            "valid",
            "success",
            "succeeded",
            "approved",
            "safe",
            "successful",
        ),
        default=False,
    )

    if not is_valid:
        reason = _extract_value(
            validation,
            (
                "error",
                "error_message",
                "reason",
                "message",
                "validation_error",
            ),
            default="Patch validation failed.",
        )

        raise TaskPatchError(str(reason))

    return validation


def _apply_patch(
    context: TaskExecutionContext,
    *,
    patch_service: PatchService,
) -> Any:
    if context.request.dry_run:
        return {
            "success": True,
            "dry_run": True,
            "changed_paths": _extract_paths(context.patch),
        }

    timeout_seconds = _remaining_stage_timeout(
        context,
        context.configuration.patch_timeout_seconds,
    )

    if isinstance(context.patch, PatchRequestPayload):
        application = patch_service.apply_patch(
            context.patch,
            dry_run=context.request.dry_run,
        )

        if not application.successful:
            raise TaskPatchError(
                application.error or "Patch application failed."
            )

        return application

    application = _call_compatible_method(
        patch_service,
        (
            "apply_patch",
            "apply",
            "execute_patch",
            "commit_patch",
        ),
        keyword_variants=(
            {
                "patch": context.patch,
                "validation": context.patch_validation,
                "task": context.request,
                "plan": context.plan,
                "repository_root": (
                    context.configuration.repository_root
                ),
                "timeout_seconds": timeout_seconds,
                "cancellation_token": (
                    context.cancellation_token
                ),
            },
            {
                "patch_result": context.patch,
                "validation_result": context.patch_validation,
                "request": context.request,
            },
            {
                "patch": context.patch,
            },
        ),
        positional_variants=(
            (context.patch,),
            (
                context.patch,
                context.patch_validation,
            ),
        ),
        operation_name="patch application",
    )

    if application is None:
        raise TaskPatchError(
            "The patch service returned no application result."
        )

    succeeded = _extract_boolean(
        application,
        (
            "success",
            "succeeded",
            "applied",
            "completed",
            "successful",
        ),
        default=False,
    )

    if not succeeded:
        reason = _extract_value(
            application,
            (
                "error",
                "error_message",
                "reason",
                "message",
            ),
            default="Patch application failed.",
        )

        raise TaskPatchError(str(reason))

    return application


def _resolve_build_commands(
    context: TaskExecutionContext,
) -> tuple[BuildCommandSpec, ...]:
    if context.request.build_commands:
        return context.request.build_commands

    plan_commands = _extract_value(
        context.plan,
        (
            "build_commands",
            "validation_commands",
            "commands",
            "checks",
        ),
    )

    if isinstance(plan_commands, Sequence) and not isinstance(
        plan_commands,
        (str, bytes),
    ):
        normalized_commands: list[BuildCommandSpec] = []

        for index, command in enumerate(plan_commands):
            if isinstance(command, BuildCommandSpec):
                normalized_commands.append(command)
                continue

            if isinstance(command, Mapping):
                try:
                    normalized_commands.append(
                        BuildCommandSpec.model_validate(command)
                    )
                except Exception as exc:
                    raise TaskBuildError(
                        f"Invalid build command at plan index "
                        f"{index}: {exc}"
                    ) from exc

        if normalized_commands:
            return tuple(normalized_commands)

    if not context.configuration.use_default_build_sequence:
        return ()

    return create_default_validation_sequence(
        backend_directory=(
            context.configuration.default_backend_directory
        ),
        frontend_directory=(
            context.configuration.default_frontend_directory
        ),
        include_mypy=context.configuration.include_mypy,
        include_ruff=context.configuration.include_ruff,
        include_frontend_tests=(
            context.configuration.include_frontend_tests
        ),
        include_frontend_build=(
            context.configuration.include_frontend_build
        ),
        timeout_seconds=min(
            context.configuration.build_timeout_seconds,
            context.remaining_seconds(),
        ),
    )


def _run_build(
    context: TaskExecutionContext,
    *,
    build_service: BuildService,
) -> BuildSequenceResult | None:
    if context.request.build_policy is BuildPolicy.DISABLED:
        return None

    commands = _resolve_build_commands(context)

    if not commands:
        if context.request.build_policy is BuildPolicy.REQUIRED:
            raise TaskBuildError(
                "No build or validation commands are available."
            )

        return None

    build_timeout = _remaining_stage_timeout(
        context,
        context.configuration.build_timeout_seconds,
    )

    bounded_commands: list[BuildCommandSpec] = []

    for command in commands:
        bounded_commands.append(
            command.model_copy(
                update={
                    "timeout_seconds": min(
                        command.timeout_seconds,
                        build_timeout,
                    )
                }
            )
        )

    options = BuildExecutionOptions(
        dry_run=context.request.dry_run,
        stop_on_first_failure=(
            context.request.stop_build_on_first_failure
        ),
    )

    result = build_service.execute_sequence(
        tuple(bounded_commands),
        options=options,
        cancellation_token=(
            context.cancellation_token.build_token
        ),
    )

    if result.status in {
        BuildStatus.FAILED,
        BuildStatus.ERROR,
        BuildStatus.TIMED_OUT,
        BuildStatus.CANCELLED,
    }:
        failed_commands = [
            command_result
            for command_result in result.commands
            if command_result.status
            in {
                BuildStatus.FAILED,
                BuildStatus.ERROR,
                BuildStatus.TIMED_OUT,
                BuildStatus.CANCELLED,
            }
        ]

        failure_summary = "; ".join(
            (
                f"{command.command_id}: "
                f"{command.error_message or command.status.value}"
            )
            for command in failed_commands
        )

        raise TaskBuildError(
            failure_summary
            or "Repository validation failed."
        )

    return result
def _should_attempt_rollback(
    context: TaskExecutionContext,
    *,
    failed_stage: TaskStage,
) -> bool:
    if context.request.dry_run:
        return False

    if context.backup is None:
        return False

    policy = context.request.rollback_policy

    if policy is RollbackPolicy.NEVER:
        return False

    if policy is RollbackPolicy.ON_ANY_FAILURE:
        return True

    if (
        policy is RollbackPolicy.ON_PATCH_FAILURE
        and failed_stage
        in {
            TaskStage.PATCH_GENERATION,
            TaskStage.PATCH_VALIDATION,
            TaskStage.PATCH_APPLICATION,
        }
    ):
        return True

    if (
        policy is RollbackPolicy.ON_BUILD_FAILURE
        and failed_stage is TaskStage.BUILD
    ):
        return True

    return False


def _rollback(
    context: TaskExecutionContext,
    *,
    backup_service: BackupService,
    patch_service: PatchService,
) -> Any:
    if context.backup is None:
        raise TaskRollbackError(
            "Rollback was requested, but no backup reference is available."
        )

    timeout_seconds = _remaining_stage_timeout(
        context,
        context.configuration.rollback_timeout_seconds,
    )

    context.rollback_attempted = True

    rollback_errors: list[BaseException] = []

    patch_rollback_methods = (
        "rollback_patch",
        "revert_patch",
        "undo_patch",
        "rollback",
        "revert",
    )

    patch_rollback_available = any(
        callable(getattr(patch_service, method_name, None))
        for method_name in patch_rollback_methods
    )

    if patch_rollback_available:
        try:
            patch_result = _call_compatible_method(
                patch_service,
                patch_rollback_methods,
                keyword_variants=(
                    {
                        "patch": context.patch,
                        "application_result": (
                            context.patch_application
                        ),
                        "backup": context.backup,
                        "task": context.request,
                        "repository_root": (
                            context.configuration.repository_root
                        ),
                        "timeout_seconds": timeout_seconds,
                        "cancellation_token": (
                            context.cancellation_token
                        ),
                    },
                    {
                        "patch_result": context.patch,
                        "apply_result": context.patch_application,
                        "backup_result": context.backup,
                    },
                    {
                        "backup": context.backup,
                    },
                ),
                positional_variants=(
                    (
                        context.patch,
                        context.patch_application,
                        context.backup,
                    ),
                    (
                        context.patch,
                        context.backup,
                    ),
                    (context.backup,),
                ),
                operation_name="patch rollback",
            )

            patch_rollback_success = _extract_boolean(
                patch_result,
                (
                    "success",
                    "succeeded",
                    "rolled_back",
                    "reverted",
                    "completed",
                ),
                default=patch_result is not None,
            )

            if patch_rollback_success:
                context.rollback_succeeded = True
                return patch_result

            rollback_errors.append(
                TaskRollbackError(
                    str(
                        _extract_value(
                            patch_result,
                            (
                                "error",
                                "error_message",
                                "reason",
                                "message",
                            ),
                            default=(
                                "Patch service reported an unsuccessful "
                                "rollback."
                            ),
                        )
                    )
                )
            )
        except (
            TaskCancellationError,
            TaskTimeoutError,
        ):
            raise
        except Exception as exc:
            rollback_errors.append(exc)

    try:
        backup_id = _extract_backup_id(context.backup)
        if backup_id is None:
            raise TaskRollbackError(
                "Rollback was requested, but the backup reference does not "
                "include a backup_id."
            )

        backup_result = _call_compatible_method(
            backup_service,
            (
                "restore_backup",
                "restore",
                "rollback",
                "restore_snapshot",
                "recover",
            ),
            keyword_variants=(
                {
                    "backup_id": backup_id,
                    "backup": context.backup,
                    "backup_reference": context.backup,
                    "task_id": context.request.task_id,
                    "repository_root": (
                        context.configuration.repository_root
                    ),
                    "changed_paths": context.changed_paths,
                    "timeout_seconds": timeout_seconds,
                    "cancellation_token": (
                        context.cancellation_token
                    ),
                },
                {
                    "backup_result": context.backup,
                    "task": context.request,
                },
                {
                    "snapshot": context.backup,
                },
            ),
            positional_variants=(
                (backup_id,),
                (
                    context.request.task_id,
                    backup_id,
                ),
            ),
            operation_name="backup restoration",
        )
    except (
        TaskCancellationError,
        TaskTimeoutError,
    ):
        raise
    except Exception as exc:
        rollback_errors.append(exc)
    else:
        backup_restore_success = _extract_boolean(
            backup_result,
            (
                "success",
                "succeeded",
                "restored",
                "rolled_back",
                "completed",
            ),
            default=backup_result is not None,
        )

        if backup_restore_success:
            context.rollback_succeeded = True
            return backup_result

        rollback_errors.append(
            TaskRollbackError(
                str(
                    _extract_value(
                        backup_result,
                        (
                            "error",
                            "error_message",
                            "reason",
                            "message",
                        ),
                        default=(
                            "Backup service reported an unsuccessful "
                            "restore operation."
                        ),
                    )
                )
            )
        )

    context.rollback_succeeded = False

    if rollback_errors:
        combined_error = "; ".join(
            _safe_error_message(error)
            for error in rollback_errors
        )

        raise TaskRollbackError(
            f"Rollback failed: {combined_error}"
        )

    raise TaskRollbackError(
        "Rollback failed because no compatible rollback operation "
        "completed successfully."
    )


def _determine_changed_paths(
    context: TaskExecutionContext,
) -> tuple[str, ...]:
    candidate_sources = (
        context.patch_application,
        context.patch_validation,
        context.patch,
        context.plan,
    )

    collected: list[str] = []

    for source in candidate_sources:
        for path_text in _extract_paths(source):
            if path_text not in collected:
                collected.append(path_text)

    normalized_paths: list[str] = []

    for path_text in collected:
        try:
            resolved = _normalize_repository_path(
                context.configuration.repository_root,
                path_text,
                must_exist=False,
            )
        except TaskServiceError:
            continue

        try:
            relative_path = resolved.relative_to(
                context.configuration.repository_root
            )
        except ValueError:
            continue

        normalized = relative_path.as_posix()

        if normalized not in normalized_paths:
            normalized_paths.append(normalized)

    return tuple(normalized_paths)


def _status_for_error(
    error: BaseException,
    *,
    rollback_attempted: bool,
    rollback_succeeded: bool,
) -> TaskStatus:
    if isinstance(error, TaskCancellationError):
        if rollback_attempted and rollback_succeeded:
            return TaskStatus.ROLLED_BACK
        return TaskStatus.CANCELLED

    if isinstance(error, TaskTimeoutError):
        if rollback_attempted and rollback_succeeded:
            return TaskStatus.ROLLED_BACK
        return TaskStatus.TIMED_OUT

    if rollback_attempted:
        if rollback_succeeded:
            return TaskStatus.ROLLED_BACK
        return TaskStatus.ROLLBACK_FAILED

    return TaskStatus.FAILED


def _stage_for_status(
    status: TaskStatus,
) -> TaskStage:
    stage_by_status = {
        TaskStatus.VALIDATING: TaskStage.VALIDATION,
        TaskStatus.ANALYZING: TaskStage.ANALYSIS,
        TaskStatus.PLANNING: TaskStage.PLANNING,
        TaskStatus.BACKING_UP: TaskStage.BACKUP,
        TaskStatus.GENERATING_PATCH: (
            TaskStage.PATCH_GENERATION
        ),
        TaskStatus.VALIDATING_PATCH: (
            TaskStage.PATCH_VALIDATION
        ),
        TaskStatus.APPLYING_PATCH: (
            TaskStage.PATCH_APPLICATION
        ),
        TaskStatus.BUILDING: TaskStage.BUILD,
        TaskStatus.ROLLING_BACK: TaskStage.ROLLBACK,
        TaskStatus.SUCCEEDED: TaskStage.COMPLETION,
        TaskStatus.FAILED: TaskStage.COMPLETION,
        TaskStatus.CANCELLED: TaskStage.COMPLETION,
        TaskStatus.TIMED_OUT: TaskStage.COMPLETION,
        TaskStatus.ROLLED_BACK: TaskStage.ROLLBACK,
        TaskStatus.ROLLBACK_FAILED: TaskStage.ROLLBACK,
        TaskStatus.DRY_RUN: TaskStage.COMPLETION,
        TaskStatus.PENDING: TaskStage.VALIDATION,
    }

    return stage_by_status[status]


def _result_metadata(
    context: TaskExecutionContext,
) -> dict[str, Any]:
    metadata = dict(context.request.metadata)
    metadata.update(context.metadata)

    metadata.update(
        {
            "target_paths": list(
                context.request.target_paths
            ),
            "excluded_paths": list(
                context.request.excluded_paths
            ),
            "backup_policy": (
                context.request.backup_policy.value
            ),
            "build_policy": (
                context.request.build_policy.value
            ),
            "rollback_policy": (
                context.request.rollback_policy.value
            ),
            "allow_file_creation": (
                context.request.allow_file_creation
            ),
            "allow_file_deletion": (
                context.request.allow_file_deletion
            ),
            "require_clean_repository": (
                context.request.require_clean_repository
            ),
            "task_timeout_seconds": (
                context.request.task_timeout_seconds
            ),
        }
    )

    return metadata


def _create_internal_result(
    context: TaskExecutionContext,
    *,
    events: tuple[TaskEvent, ...],
) -> TaskExecutionResult:
    finished_at_epoch = time.time()
    duration_seconds = context.elapsed_seconds()

    error_type: str | None = None
    error_message: str | None = None

    if context.error is not None:
        error_type = type(context.error).__name__
        error_message = _safe_error_message(context.error)

    return TaskExecutionResult(
        task_id=context.request.task_id,
        status=context.status,
        instruction=context.request.instruction,
        repository_root=str(
            context.configuration.repository_root
        ),
        started_at_epoch=context.started_at_epoch,
        finished_at_epoch=finished_at_epoch,
        duration_seconds=duration_seconds,
        analysis=context.analysis,
        plan=context.plan,
        backup=context.backup,
        patch=context.patch,
        patch_validation=context.patch_validation,
        patch_application=context.patch_application,
        build_result=context.build_result,
        rollback_result=context.rollback_result,
        changed_paths=context.changed_paths,
        events=events,
        error_type=error_type,
        error_message=error_message,
        rollback_attempted=context.rollback_attempted,
        rollback_succeeded=context.rollback_succeeded,
        dry_run=context.request.dry_run,
        metadata=_result_metadata(context),
    )


def _task_result_to_domain_model(
    result: TaskExecutionResult,
) -> Any:
    model_type = _find_domain_model(
        (
            "CodeBuilderTaskResult",
            "TaskExecutionResult",
            "CodeTaskResult",
            "TaskResult",
            "BuilderTaskResult",
            "OrchestrationResult",
        )
    )

    if model_type is None:
        return result

    if model_type is TaskExecutionResult:
        return result

    payload = result.model_dump(mode="python")

    payload.update(
        {
            "success": result.succeeded,
            "succeeded": result.succeeded,
            "result_status": result.status.value,
            "task_status": result.status.value,
            "repository_path": result.repository_root,
            "duration": result.duration_seconds,
            "events": [
                event.model_dump(mode="python")
                for event in result.events
            ],
            "build": (
                result.build_result.model_dump(
                    mode="python"
                )
                if result.build_result is not None
                else None
            ),
            "rollback": result.rollback_result,
            "modified_paths": list(
                result.changed_paths
            ),
        }
    )

    try:
        return _instantiate_compatible_model(
            model_type,
            payload,
        )
    except Exception as exc:
        raise TaskResultMappingError(
            f"Could not map task result to "
            f"{model_type.__name__}: {exc}"
        ) from exc


def _task_request_from_domain_model(
    task: Any,
) -> TaskRequest:
    if isinstance(task, TaskRequest):
        return task

    if isinstance(task, str):
        return TaskRequest(instruction=task)

    if isinstance(task, Mapping):
        direct_payload = dict(task)

        try:
            return TaskRequest.model_validate(
                direct_payload
            )
        except Exception:
            pass

    model_dump = getattr(task, "model_dump", None)

    if callable(model_dump):
        try:
            dumped = model_dump(mode="python")
        except TypeError:
            dumped = model_dump()

        if isinstance(dumped, Mapping):
            try:
                return TaskRequest.model_validate(
                    dumped
                )
            except Exception:
                pass

    instruction = _extract_value(
        task,
        (
            "instruction",
            "description",
            "task",
            "prompt",
            "request",
            "objective",
        ),
    )

    if not isinstance(instruction, str):
        raise TaskValidationError(
            "Could not extract a task instruction from the "
            "provided models.py object."
        )

    task_id = _extract_value(
        task,
        (
            "task_id",
            "id",
            "request_id",
            "job_id",
        ),
        default=uuid.uuid4().hex,
    )

    context_value = _extract_value(
        task,
        (
            "context",
            "user_context",
            "additional_context",
            "background",
        ),
    )

    target_paths = _extract_value(
        task,
        (
            "target_paths",
            "paths",
            "files",
            "affected_paths",
        ),
        default=(),
    )

    excluded_paths = _extract_value(
        task,
        (
            "excluded_paths",
            "ignore_paths",
            "ignored_paths",
            "exclude",
        ),
        default=(),
    )

    build_commands = _extract_value(
        task,
        (
            "build_commands",
            "validation_commands",
            "commands",
        ),
        default=(),
    )

    metadata = _extract_value(
        task,
        ("metadata",),
        default={},
    )

    normalized_targets = (
        (target_paths,)
        if isinstance(target_paths, str)
        else tuple(target_paths or ())
    )

    normalized_excluded = (
        (excluded_paths,)
        if isinstance(excluded_paths, str)
        else tuple(excluded_paths or ())
    )

    normalized_build_commands: list[BuildCommandSpec] = []

    if isinstance(
        build_commands,
        Sequence,
    ) and not isinstance(
        build_commands,
        (str, bytes),
    ):
        for index, command in enumerate(build_commands):
            if isinstance(command, BuildCommandSpec):
                normalized_build_commands.append(command)
                continue

            try:
                normalized_build_commands.append(
                    BuildCommandSpec.model_validate(
                        command
                    )
                )
            except Exception as exc:
                raise TaskValidationError(
                    f"Invalid build command at index "
                    f"{index}: {exc}"
                ) from exc

    request_payload = {
        "task_id": str(task_id),
        "instruction": instruction,
        "context": (
            str(context_value)
            if context_value is not None
            else None
        ),
        "target_paths": tuple(
            str(path)
            for path in normalized_targets
        ),
        "excluded_paths": tuple(
            str(path)
            for path in normalized_excluded
        ),
        "build_commands": tuple(
            normalized_build_commands
        ),
        "task_timeout_seconds": _extract_value(
            task,
            (
                "task_timeout_seconds",
                "timeout_seconds",
                "timeout",
            ),
            default=DEFAULT_TASK_TIMEOUT_SECONDS,
        ),
        "dry_run": _extract_boolean(
            task,
            ("dry_run",),
            default=False,
        ),
        "allow_file_creation": _extract_boolean(
            task,
            (
                "allow_file_creation",
                "can_create_files",
            ),
            default=True,
        ),
        "allow_file_deletion": _extract_boolean(
            task,
            (
                "allow_file_deletion",
                "can_delete_files",
            ),
            default=False,
        ),
        "require_clean_repository": _extract_boolean(
            task,
            (
                "require_clean_repository",
                "require_clean_repo",
            ),
            default=False,
        ),
        "stop_build_on_first_failure": _extract_boolean(
            task,
            (
                "stop_build_on_first_failure",
                "stop_on_first_failure",
            ),
            default=True,
        ),
        "backup_policy": _extract_value(
            task,
            ("backup_policy",),
            default=BackupPolicy.REQUIRED,
        ),
        "build_policy": _extract_value(
            task,
            ("build_policy",),
            default=BuildPolicy.REQUIRED,
        ),
        "rollback_policy": _extract_value(
            task,
            ("rollback_policy",),
            default=RollbackPolicy.ON_ANY_FAILURE,
        ),
        "metadata": (
            dict(metadata)
            if isinstance(metadata, Mapping)
            else {}
        ),
    }

    try:
        return TaskRequest.model_validate(
            request_payload
        )
    except Exception as exc:
        raise TaskValidationError(
            f"Invalid task request: {exc}"
        ) from exc


def _validate_service_dependencies(
    *,
    repository_service: RepositoryService,
    planning_service: PlanningService,
    backup_service: BackupService,
    patch_service: PatchService,
    build_service: BuildService,
    ollama_service: OllamaService,
) -> None:
    dependencies = {
        "repository_service": repository_service,
        "planning_service": planning_service,
        "backup_service": backup_service,
        "patch_service": patch_service,
        "build_service": build_service,
        "ollama_service": ollama_service,
    }

    missing = [
        name
        for name, service in dependencies.items()
        if service is None
    ]

    if missing:
        raise TaskConfigurationError(
            "Missing required task service dependencies: "
            + ", ".join(sorted(missing))
        )


class TaskService:
    """Production orchestration service for Code Builder tasks."""

    def __init__(
        self,
        *,
        repository_service: RepositoryService,
        planning_service: PlanningService,
        backup_service: BackupService,
        patch_service: PatchService,
        build_service: BuildService,
        ollama_service: OllamaService,
        configuration: TaskServiceConfiguration,
    ) -> None:
        _validate_service_dependencies(
            repository_service=repository_service,
            planning_service=planning_service,
            backup_service=backup_service,
            patch_service=patch_service,
            build_service=build_service,
            ollama_service=ollama_service,
        )

        self._repository_service = repository_service
        self._planning_service = planning_service
        self._backup_service = backup_service
        self._patch_service = patch_service
        self._build_service = build_service
        self._ollama_service = ollama_service
        self._configuration = configuration
        self._active_tasks: dict[
            str,
            TaskCancellationToken,
        ] = {}
        self._active_tasks_lock = threading.RLock()

    @property
    def configuration(
        self,
    ) -> TaskServiceConfiguration:
        return self._configuration

    @property
    def repository_service(
        self,
    ) -> RepositoryService:
        return self._repository_service

    @property
    def planning_service(
        self,
    ) -> PlanningService:
        return self._planning_service

    @property
    def backup_service(
        self,
    ) -> BackupService:
        return self._backup_service

    @property
    def patch_service(
        self,
    ) -> PatchService:
        return self._patch_service

    @property
    def build_service(
        self,
    ) -> BuildService:
        return self._build_service

    @property
    def ollama_service(
        self,
    ) -> OllamaService:
        return self._ollama_service

    def active_task_ids(self) -> tuple[str, ...]:
        with self._active_tasks_lock:
            return tuple(
                sorted(self._active_tasks.keys())
            )

    def is_task_active(
        self,
        task_id: str,
    ) -> bool:
        with self._active_tasks_lock:
            return task_id in self._active_tasks

    def get_cancellation_token(
        self,
        task_id: str,
    ) -> TaskCancellationToken | None:
        with self._active_tasks_lock:
            return self._active_tasks.get(task_id)

    def cancel_task(
        self,
        task_id: str,
        *,
        reason: str | None = None,
    ) -> bool:
        with self._active_tasks_lock:
            token = self._active_tasks.get(task_id)

        if token is None:
            return False

        token.cancel(reason)

        self._build_service.cancel_all(
            reason=(
                reason
                or f"Task {task_id!r} was cancelled."
            )
        )

        return True

    def cancel_all_tasks(
        self,
        *,
        reason: str | None = None,
    ) -> int:
        with self._active_tasks_lock:
            tokens = tuple(
                self._active_tasks.values()
            )

        for token in tokens:
            token.cancel(reason)

        self._build_service.cancel_all(
            reason=(
                reason
                or "All Code Builder tasks were cancelled."
            )
        )

        return len(tokens)

    def _register_task(
        self,
        token: TaskCancellationToken,
    ) -> None:
        with self._active_tasks_lock:
            if token.task_id in self._active_tasks:
                raise TaskValidationError(
                    f"Task {token.task_id!r} is already running."
                )

            self._active_tasks[token.task_id] = token

    def _release_task(
        self,
        task_id: str,
        token: TaskCancellationToken,
    ) -> None:
        with self._active_tasks_lock:
            current = self._active_tasks.get(task_id)

            if current is token:
                self._active_tasks.pop(task_id, None)
    def _record_event(
        self,
        context: TaskExecutionContext,
        recorder: _EventRecorder,
        *,
        stage: TaskStage,
        status: TaskStatus,
        level: TaskEventLevel,
        message: str,
        details: Mapping[str, Any] | None = None,
    ) -> TaskEvent:
        context.status = status

        event = recorder.add(
            stage=stage,
            status=status,
            level=level,
            message=message,
            details=details,
        )

        context.events = list(recorder.snapshot())
        return event

    def _validate_request(
        self,
        context: TaskExecutionContext,
    ) -> Any:
        context.raise_if_interrupted()

        repository_root = (
            context.configuration.repository_root
        )

        _validate_task_paths(
            context.request,
            repository_root=repository_root,
        )

        _validate_task_with_security_service(
            context.request,
            repository_root=repository_root,
        )

        repository_state = _validate_repository_state(
            self._repository_service,
            context.request,
        )

        context.raise_if_interrupted()
        return repository_state

    def _execute_analysis_stage(
        self,
        context: TaskExecutionContext,
        recorder: _EventRecorder,
    ) -> None:
        self._record_event(
            context,
            recorder,
            stage=TaskStage.ANALYSIS,
            status=TaskStatus.ANALYZING,
            level=TaskEventLevel.INFO,
            message="Repository and task analysis started.",
            details={
                "target_paths": list(
                    context.request.target_paths
                ),
                "excluded_paths": list(
                    context.request.excluded_paths
                ),
            },
        )

        try:
            context.analysis = _analyze_task(
                context,
                repository_service=(
                    self._repository_service
                ),
                ollama_service=self._ollama_service,
            )
        except (
            TaskCancellationError,
            TaskTimeoutError,
        ):
            raise
        except TaskServiceError:
            raise
        except Exception as exc:
            raise TaskAnalysisError(
                f"Task analysis failed: "
                f"{_safe_error_message(exc)}"
            ) from exc

        context.raise_if_interrupted()

        self._record_event(
            context,
            recorder,
            stage=TaskStage.ANALYSIS,
            status=TaskStatus.ANALYZING,
            level=TaskEventLevel.INFO,
            message="Repository and task analysis completed.",
            details={
                "analysis_type": type(
                    context.analysis
                ).__name__,
            },
        )

    def _execute_planning_stage(
        self,
        context: TaskExecutionContext,
        recorder: _EventRecorder,
    ) -> None:
        self._record_event(
            context,
            recorder,
            stage=TaskStage.PLANNING,
            status=TaskStatus.PLANNING,
            level=TaskEventLevel.INFO,
            message="Implementation planning started.",
        )

        approved_preparation_plan = _extract_value(
            context.request.metadata,
            ("approved_preparation_plan",),
        )

        if approved_preparation_plan is not None:
            context.plan = approved_preparation_plan
            context.raise_if_interrupted()
            planned_paths = _extract_paths(context.plan)
            self._record_event(
                context,
                recorder,
                stage=TaskStage.PLANNING,
                status=TaskStatus.PLANNING,
                level=TaskEventLevel.INFO,
                message="Approved prepared implementation plan reused.",
                details={
                    "plan_type": type(context.plan).__name__,
                    "planned_paths": list(planned_paths),
                    "approved_preparation_reused": True,
                },
            )
            return

        try:
            context.plan = _create_plan(
                context,
                planning_service=self._planning_service,
            )
        except (
            TaskCancellationError,
            TaskTimeoutError,
        ):
            raise
        except TaskServiceError:
            raise
        except Exception as exc:
            raise TaskPlanningError(
                f"Implementation planning failed: "
                f"{_safe_error_message(exc)}"
            ) from exc

        context.raise_if_interrupted()

        planned_paths = _extract_paths(
            context.plan
        )

        self._record_event(
            context,
            recorder,
            stage=TaskStage.PLANNING,
            status=TaskStatus.PLANNING,
            level=TaskEventLevel.INFO,
            message="Implementation planning completed.",
            details={
                "plan_type": type(
                    context.plan
                ).__name__,
                "planned_paths": list(planned_paths),
            },
        )

    def _execute_backup_stage(
        self,
        context: TaskExecutionContext,
        recorder: _EventRecorder,
    ) -> None:
        if (
            context.request.backup_policy
            is BackupPolicy.DISABLED
        ):
            self._record_event(
                context,
                recorder,
                stage=TaskStage.BACKUP,
                status=TaskStatus.BACKING_UP,
                level=TaskEventLevel.INFO,
                message=(
                    "Repository backup was skipped because "
                    "backup policy is disabled."
                ),
            )
            return

        self._record_event(
            context,
            recorder,
            stage=TaskStage.BACKUP,
            status=TaskStatus.BACKING_UP,
            level=TaskEventLevel.INFO,
            message="Repository backup started.",
            details={
                "backup_policy": (
                    context.request.backup_policy.value
                ),
            },
        )

        try:
            context.backup = _create_backup(
                context,
                backup_service=self._backup_service,
            )
        except (
            TaskCancellationError,
            TaskTimeoutError,
        ):
            raise
        except TaskServiceError:
            raise
        except Exception as exc:
            if (
                context.request.backup_policy
                is BackupPolicy.OPTIONAL
            ):
                context.backup = None

                self._record_event(
                    context,
                    recorder,
                    stage=TaskStage.BACKUP,
                    status=TaskStatus.BACKING_UP,
                    level=TaskEventLevel.WARNING,
                    message=(
                        "Optional repository backup failed; "
                        "task execution will continue."
                    ),
                    details={
                        "error_type": type(exc).__name__,
                        "error_message": (
                            _safe_error_message(exc)
                        ),
                    },
                )
                return

            raise TaskBackupError(
                f"Repository backup failed: "
                f"{_safe_error_message(exc)}"
            ) from exc

        context.raise_if_interrupted()

        self._record_event(
            context,
            recorder,
            stage=TaskStage.BACKUP,
            status=TaskStatus.BACKING_UP,
            level=TaskEventLevel.INFO,
            message=(
                "Repository backup completed."
                if context.backup is not None
                else "No repository backup was created."
            ),
            details={
                "backup_available": (
                    context.backup is not None
                ),
                "backup_type": (
                    type(context.backup).__name__
                    if context.backup is not None
                    else None
                ),
            },
        )

    def _execute_patch_generation_stage(
        self,
        context: TaskExecutionContext,
        recorder: _EventRecorder,
    ) -> None:
        self._record_event(
            context,
            recorder,
            stage=TaskStage.PATCH_GENERATION,
            status=TaskStatus.GENERATING_PATCH,
            level=TaskEventLevel.INFO,
            message="Patch generation started.",
        )

        try:
            context.patch = _generate_patch(
                context,
                patch_service=self._patch_service,
                ollama_service=self._ollama_service,
            )
        except (
            TaskCancellationError,
            TaskTimeoutError,
        ):
            raise
        except TaskServiceError:
            raise
        except Exception as exc:
            raise TaskPatchError(
                f"Patch generation failed: "
                f"{_safe_error_message(exc)}"
            ) from exc

        context.raise_if_interrupted()

        generated_paths = _extract_paths(
            context.patch
        )

        self._record_event(
            context,
            recorder,
            stage=TaskStage.PATCH_GENERATION,
            status=TaskStatus.GENERATING_PATCH,
            level=TaskEventLevel.INFO,
            message="Patch generation completed.",
            details={
                "patch_type": type(
                    context.patch
                ).__name__,
                "generated_paths": list(
                    generated_paths
                ),
            },
        )

    def _execute_patch_validation_stage(
        self,
        context: TaskExecutionContext,
        recorder: _EventRecorder,
    ) -> None:
        self._record_event(
            context,
            recorder,
            stage=TaskStage.PATCH_VALIDATION,
            status=TaskStatus.VALIDATING_PATCH,
            level=TaskEventLevel.INFO,
            message="Patch validation started.",
        )

        try:
            context.patch_validation = _validate_patch(
                context,
                patch_service=self._patch_service,
            )
        except (
            TaskCancellationError,
            TaskTimeoutError,
        ):
            raise
        except TaskServiceError:
            raise
        except Exception as exc:
            raise TaskPatchError(
                f"Patch validation failed: "
                f"{_safe_error_message(exc)}"
            ) from exc

        context.raise_if_interrupted()

        self._record_event(
            context,
            recorder,
            stage=TaskStage.PATCH_VALIDATION,
            status=TaskStatus.VALIDATING_PATCH,
            level=TaskEventLevel.INFO,
            message="Patch validation completed.",
            details={
                "validation_type": type(
                    context.patch_validation
                ).__name__,
            },
        )

    def _execute_patch_application_stage(
        self,
        context: TaskExecutionContext,
        recorder: _EventRecorder,
    ) -> None:
        self._record_event(
            context,
            recorder,
            stage=TaskStage.PATCH_APPLICATION,
            status=TaskStatus.APPLYING_PATCH,
            level=TaskEventLevel.INFO,
            message=(
                "Patch dry-run started."
                if context.request.dry_run
                else "Patch application started."
            ),
            details={
                "dry_run": context.request.dry_run,
            },
        )

        try:
            context.patch_application = _apply_patch(
                context,
                patch_service=self._patch_service,
            )
        except (
            TaskCancellationError,
            TaskTimeoutError,
        ):
            raise
        except TaskServiceError:
            raise
        except Exception as exc:
            raise TaskPatchError(
                f"Patch application failed: "
                f"{_safe_error_message(exc)}"
            ) from exc

        context.raise_if_interrupted()

        context.changed_paths = _determine_changed_paths(
            context
        )

        self._record_event(
            context,
            recorder,
            stage=TaskStage.PATCH_APPLICATION,
            status=TaskStatus.APPLYING_PATCH,
            level=TaskEventLevel.INFO,
            message=(
                "Patch dry-run completed."
                if context.request.dry_run
                else "Patch application completed."
            ),
            details={
                "changed_paths": list(
                    context.changed_paths
                ),
                "dry_run": context.request.dry_run,
            },
        )

    def _execute_build_stage(
        self,
        context: TaskExecutionContext,
        recorder: _EventRecorder,
    ) -> None:
        if (
            context.request.build_policy
            is BuildPolicy.DISABLED
        ):
            self._record_event(
                context,
                recorder,
                stage=TaskStage.BUILD,
                status=TaskStatus.BUILDING,
                level=TaskEventLevel.INFO,
                message=(
                    "Build validation was skipped because "
                    "build policy is disabled."
                ),
            )
            return

        self._record_event(
            context,
            recorder,
            stage=TaskStage.BUILD,
            status=TaskStatus.BUILDING,
            level=TaskEventLevel.INFO,
            message=(
                "Build dry-run started."
                if context.request.dry_run
                else "Build validation started."
            ),
            details={
                "build_policy": (
                    context.request.build_policy.value
                ),
                "dry_run": context.request.dry_run,
            },
        )

        try:
            context.build_result = _run_build(
                context,
                build_service=self._build_service,
            )
        except (
            TaskCancellationError,
            TaskTimeoutError,
        ):
            raise
        except TaskBuildError:
            raise
        except TaskServiceError:
            raise
        except Exception as exc:
            if (
                context.request.build_policy
                is BuildPolicy.OPTIONAL
            ):
                context.build_result = None

                self._record_event(
                    context,
                    recorder,
                    stage=TaskStage.BUILD,
                    status=TaskStatus.BUILDING,
                    level=TaskEventLevel.WARNING,
                    message=(
                        "Optional build validation failed; "
                        "task execution will continue."
                    ),
                    details={
                        "error_type": type(exc).__name__,
                        "error_message": (
                            _safe_error_message(exc)
                        ),
                    },
                )
                return

            raise TaskBuildError(
                f"Build validation failed: "
                f"{_safe_error_message(exc)}"
            ) from exc

        context.raise_if_interrupted()

        if context.build_result is None:
            self._record_event(
                context,
                recorder,
                stage=TaskStage.BUILD,
                status=TaskStatus.BUILDING,
                level=TaskEventLevel.WARNING,
                message=(
                    "No build result was produced."
                ),
            )
            return

        failed_commands = tuple(
            command
            for command in context.build_result.commands
            if command.status
            in {
                BuildStatus.FAILED,
                BuildStatus.ERROR,
                BuildStatus.TIMED_OUT,
                BuildStatus.CANCELLED,
            }
        )

        if failed_commands:
            failure_summary = "; ".join(
                (
                    f"{command.command_id}: "
                    f"{command.error_message} "
                    f"({command.status.value})"
                )
                for command in failed_commands
            )

            if (
                context.request.build_policy
                is BuildPolicy.OPTIONAL
            ):
                self._record_event(
                    context,
                    recorder,
                    stage=TaskStage.BUILD,
                    status=TaskStatus.BUILDING,
                    level=TaskEventLevel.WARNING,
                    message=(
                        "Optional build validation completed "
                        "with failures."
                    ),
                    details={
                        "failure_summary": (
                            failure_summary
                        ),
                        "failed_command_count": len(
                            failed_commands
                        ),
                    },
                )
                return

            raise TaskBuildError(
                failure_summary
                or "Build validation failed."
            )

        self._record_event(
            context,
            recorder,
            stage=TaskStage.BUILD,
            status=TaskStatus.BUILDING,
            level=TaskEventLevel.INFO,
            message=(
                "Build dry-run completed."
                if context.request.dry_run
                else "Build validation completed successfully."
            ),
            details={
                "build_status": (
                    context.build_result.status.value
                ),
                "command_count": len(
                    context.build_result.commands
                ),
                "duration_seconds": (
                    context.build_result.duration_seconds
                ),
            },
        )

    def _execute_rollback_stage(
        self,
        context: TaskExecutionContext,
        recorder: _EventRecorder,
        *,
        failed_stage: TaskStage,
        original_error: BaseException,
    ) -> None:
        if not _should_attempt_rollback(
            context,
            failed_stage=failed_stage,
        ):
            return

        self._record_event(
            context,
            recorder,
            stage=TaskStage.ROLLBACK,
            status=TaskStatus.ROLLING_BACK,
            level=TaskEventLevel.WARNING,
            message=(
                "Rollback started after task failure."
            ),
            details={
                "failed_stage": failed_stage.value,
                "original_error_type": (
                    type(original_error).__name__
                ),
                "original_error_message": (
                    _safe_error_message(original_error)
                ),
            },
        )

        try:
            context.rollback_result = _rollback(
                context,
                backup_service=self._backup_service,
                patch_service=self._patch_service,
            )
        except Exception as rollback_error:
            context.rollback_succeeded = False

            self._record_event(
                context,
                recorder,
                stage=TaskStage.ROLLBACK,
                status=TaskStatus.ROLLBACK_FAILED,
                level=TaskEventLevel.ERROR,
                message="Rollback failed.",
                details={
                    "rollback_error_type": (
                        type(rollback_error).__name__
                    ),
                    "rollback_error_message": (
                        _safe_error_message(
                            rollback_error
                        )
                    ),
                    "rollback_traceback": (
                        _safe_traceback(
                            rollback_error
                        )
                    ),
                },
            )

            raise TaskRollbackError(
                (
                    "Task failed and rollback also failed. "
                    f"Original error: "
                    f"{_safe_error_message(original_error)}. "
                    f"Rollback error: "
                    f"{_safe_error_message(rollback_error)}"
                )
            ) from rollback_error

        context.rollback_succeeded = True

        self._record_event(
            context,
            recorder,
            stage=TaskStage.ROLLBACK,
            status=TaskStatus.ROLLED_BACK,
            level=TaskEventLevel.WARNING,
            message="Rollback completed successfully.",
            details={
                "failed_stage": failed_stage.value,
                "rollback_result_type": (
                    type(
                        context.rollback_result
                    ).__name__
                    if context.rollback_result is not None
                    else None
                ),
            },
        )

    def _execute_pipeline(
        self,
        context: TaskExecutionContext,
        recorder: _EventRecorder,
    ) -> None:
        failed_stage = TaskStage.VALIDATION

        try:
            self._record_event(
                context,
                recorder,
                stage=TaskStage.VALIDATION,
                status=TaskStatus.VALIDATING,
                level=TaskEventLevel.INFO,
                message="Task validation started.",
                details={
                    "task_id": context.request.task_id,
                    "repository_root": str(
                        context.configuration.repository_root
                    ),
                    "dry_run": context.request.dry_run,
                },
            )

            repository_state = self._validate_request(
                context
            )

            if repository_state is not None:
                context.metadata[
                    "initial_repository_state"
                ] = repository_state

            self._record_event(
                context,
                recorder,
                stage=TaskStage.VALIDATION,
                status=TaskStatus.VALIDATING,
                level=TaskEventLevel.INFO,
                message="Task validation completed.",
            )

            failed_stage = TaskStage.ANALYSIS
            self._execute_analysis_stage(
                context,
                recorder,
            )

            failed_stage = TaskStage.PLANNING
            self._execute_planning_stage(
                context,
                recorder,
            )

            failed_stage = TaskStage.BACKUP
            self._execute_backup_stage(
                context,
                recorder,
            )

            failed_stage = TaskStage.PATCH_GENERATION
            self._execute_patch_generation_stage(
                context,
                recorder,
            )

            failed_stage = TaskStage.PATCH_VALIDATION
            self._execute_patch_validation_stage(
                context,
                recorder,
            )

            failed_stage = TaskStage.PATCH_APPLICATION
            self._execute_patch_application_stage(
                context,
                recorder,
            )

            failed_stage = TaskStage.BUILD
            self._execute_build_stage(
                context,
                recorder,
            )

            context.raise_if_interrupted()

            context.status = (
                TaskStatus.DRY_RUN
                if context.request.dry_run
                else TaskStatus.SUCCEEDED
            )

            self._record_event(
                context,
                recorder,
                stage=TaskStage.COMPLETION,
                status=context.status,
                level=TaskEventLevel.INFO,
                message=(
                    "Task dry-run completed successfully."
                    if context.request.dry_run
                    else "Task completed successfully."
                ),
                details={
                    "changed_paths": list(
                        context.changed_paths
                    ),
                    "duration_seconds": (
                        context.elapsed_seconds()
                    ),
                },
            )

        except BaseException as error:
            context.error = error

            rollback_error: BaseException | None = None

            try:
                self._execute_rollback_stage(
                    context,
                    recorder,
                    failed_stage=failed_stage,
                    original_error=error,
                )
            except BaseException as caught_rollback_error:
                rollback_error = caught_rollback_error
                context.error = caught_rollback_error

            final_error = (
                rollback_error
                if rollback_error is not None
                else error
            )

            context.status = _status_for_error(
                final_error,
                rollback_attempted=(
                    context.rollback_attempted
                ),
                rollback_succeeded=(
                    context.rollback_succeeded
                ),
            )

            completion_stage = _stage_for_status(
                context.status
            )

            self._record_event(
                context,
                recorder,
                stage=completion_stage,
                status=context.status,
                level=TaskEventLevel.ERROR,
                message=(
                    "Task execution failed."
                    if context.status
                    not in {
                        TaskStatus.CANCELLED,
                        TaskStatus.TIMED_OUT,
                        TaskStatus.ROLLED_BACK,
                    }
                    else {
                        TaskStatus.CANCELLED: (
                            "Task execution was cancelled."
                        ),
                        TaskStatus.TIMED_OUT: (
                            "Task execution timed out."
                        ),
                        TaskStatus.ROLLED_BACK: (
                            "Task failed and repository changes "
                            "were rolled back successfully."
                        ),
                    }[context.status]
                ),
                details={
                    "failed_stage": failed_stage.value,
                    "error_type": type(
                        final_error
                    ).__name__,
                    "error_message": (
                        _safe_error_message(
                            final_error
                        )
                    ),
                    "traceback": (
                        _safe_traceback(
                            final_error
                        )
                    ),
                    "rollback_attempted": (
                        context.rollback_attempted
                    ),
                    "rollback_succeeded": (
                        context.rollback_succeeded
                    ),
                },
            )

    def execute(
        self,
        task: TaskRequest | Any,
        *,
        event_callback: TaskEventCallback | None = None,
        cancellation_token: (
            TaskCancellationToken | None
        ) = None,
        return_domain_model: bool = True,
    ) -> Any:
        request = _task_request_from_domain_model(
            task
        )

        token = (
            cancellation_token
            or TaskCancellationToken(
                task_id=request.task_id
            )
        )

        if token.task_id != request.task_id:
            raise TaskValidationError(
                "Cancellation token task_id does not match "
                "the task request task_id."
            )

        context = TaskExecutionContext(
            request=request,
            configuration=self._configuration,
            cancellation_token=token,
        )

        recorder = _EventRecorder(
            task_id=request.task_id,
            max_events=(
                self._configuration.max_event_count
            ),
            callback=event_callback,
        )

        self._register_task(token)

        try:
            self._execute_pipeline(
                context,
                recorder,
            )
        finally:
            self._release_task(
                request.task_id,
                token,
            )

        context.events = list(
            recorder.snapshot()
        )

        result = _create_internal_result(
            context,
            events=tuple(context.events),
        )

        if not return_domain_model:
            return result

        return _task_result_to_domain_model(
            result
        )
    def execute_internal(
        self,
        task: TaskRequest | Any,
        *,
        event_callback: TaskEventCallback | None = None,
        cancellation_token: (
            TaskCancellationToken | None
        ) = None,
    ) -> TaskExecutionResult:
        result = self.execute(
            task,
            event_callback=event_callback,
            cancellation_token=cancellation_token,
            return_domain_model=False,
        )

        if not isinstance(
            result,
            TaskExecutionResult,
        ):
            raise TaskResultMappingError(
                "Internal task execution did not return "
                "TaskExecutionResult."
            )

        return result

    def execute_many(
        self,
        tasks: Sequence[TaskRequest | Any],
        *,
        event_callback: TaskEventCallback | None = None,
        stop_on_first_failure: bool = True,
        return_domain_models: bool = True,
    ) -> tuple[Any, ...]:
        results: list[Any] = []

        for task in tasks:
            result = self.execute(
                task,
                event_callback=event_callback,
                return_domain_model=return_domain_models,
            )

            results.append(result)

            if not stop_on_first_failure:
                continue

            succeeded = _extract_boolean(
                result,
                (
                    "success",
                    "succeeded",
                ),
                default=False,
            )

            status = _extract_value(
                result,
                (
                    "status",
                    "task_status",
                    "result_status",
                ),
            )

            normalized_status = (
                status.value
                if isinstance(status, enum.Enum)
                else str(status).strip().casefold()
                if status is not None
                else ""
            )

            if succeeded:
                continue

            if normalized_status in {
                TaskStatus.SUCCEEDED.value,
                TaskStatus.DRY_RUN.value,
            }:
                continue

            break

        return tuple(results)

    def validate_task(
        self,
        task: TaskRequest | Any,
    ) -> TaskRequest:
        request = _task_request_from_domain_model(
            task
        )

        token = TaskCancellationToken(
            task_id=request.task_id
        )

        context = TaskExecutionContext(
            request=request,
            configuration=self._configuration,
            cancellation_token=token,
        )

        self._validate_request(context)
        return request

    def create_cancellation_token(
        self,
        task_id: str | None = None,
    ) -> TaskCancellationToken:
        normalized_task_id = (
            task_id.strip()
            if isinstance(task_id, str)
            else uuid.uuid4().hex
        )

        if not normalized_task_id:
            raise TaskValidationError(
                "task_id cannot be empty."
            )

        return TaskCancellationToken(
            task_id=normalized_task_id
        )


def create_task_service(
    *,
    repository_root: str | Path,
    repository_service: RepositoryService,
    planning_service: PlanningService,
    backup_service: BackupService,
    patch_service: PatchService,
    build_service: BuildService,
    ollama_service: OllamaService,
    analysis_timeout_seconds: float = (
        DEFAULT_ANALYSIS_TIMEOUT_SECONDS
    ),
    planning_timeout_seconds: float = (
        DEFAULT_PLANNING_TIMEOUT_SECONDS
    ),
    patch_timeout_seconds: float = (
        DEFAULT_PATCH_TIMEOUT_SECONDS
    ),
    build_timeout_seconds: float = (
        DEFAULT_BUILD_TIMEOUT_SECONDS
    ),
    rollback_timeout_seconds: float = (
        DEFAULT_ROLLBACK_TIMEOUT_SECONDS
    ),
    max_event_count: int = DEFAULT_MAX_EVENT_COUNT,
    use_default_build_sequence: bool = True,
    default_backend_directory: str = "backend",
    default_frontend_directory: str = "frontend",
    include_ruff: bool = True,
    include_mypy: bool = True,
    include_frontend_tests: bool = True,
    include_frontend_build: bool = True,
) -> TaskService:
    configuration = TaskServiceConfiguration(
        repository_root=Path(repository_root),
        analysis_timeout_seconds=(
            analysis_timeout_seconds
        ),
        planning_timeout_seconds=(
            planning_timeout_seconds
        ),
        patch_timeout_seconds=(
            patch_timeout_seconds
        ),
        build_timeout_seconds=(
            build_timeout_seconds
        ),
        rollback_timeout_seconds=(
            rollback_timeout_seconds
        ),
        max_event_count=max_event_count,
        use_default_build_sequence=(
            use_default_build_sequence
        ),
        default_backend_directory=(
            default_backend_directory
        ),
        default_frontend_directory=(
            default_frontend_directory
        ),
        include_ruff=include_ruff,
        include_mypy=include_mypy,
        include_frontend_tests=(
            include_frontend_tests
        ),
        include_frontend_build=(
            include_frontend_build
        ),
    )

    return TaskService(
        repository_service=repository_service,
        planning_service=planning_service,
        backup_service=backup_service,
        patch_service=patch_service,
        build_service=build_service,
        ollama_service=ollama_service,
        configuration=configuration,
    )


def execute_code_builder_task(
    task: TaskRequest | Any,
    *,
    repository_service: RepositoryService,
    planning_service: PlanningService,
    backup_service: BackupService,
    patch_service: PatchService,
    build_service: BuildService,
    ollama_service: OllamaService,
    configuration: TaskServiceConfiguration,
    event_callback: TaskEventCallback | None = None,
    cancellation_token: (
        TaskCancellationToken | None
    ) = None,
    return_domain_model: bool = True,
) -> Any:
    service = TaskService(
        repository_service=repository_service,
        planning_service=planning_service,
        backup_service=backup_service,
        patch_service=patch_service,
        build_service=build_service,
        ollama_service=ollama_service,
        configuration=configuration,
    )

    return service.execute(
        task,
        event_callback=event_callback,
        cancellation_token=cancellation_token,
        return_domain_model=return_domain_model,
    )


def execute_code_builder_tasks(
    tasks: Sequence[TaskRequest | Any],
    *,
    repository_service: RepositoryService,
    planning_service: PlanningService,
    backup_service: BackupService,
    patch_service: PatchService,
    build_service: BuildService,
    ollama_service: OllamaService,
    configuration: TaskServiceConfiguration,
    event_callback: TaskEventCallback | None = None,
    stop_on_first_failure: bool = True,
    return_domain_models: bool = True,
) -> tuple[Any, ...]:
    service = TaskService(
        repository_service=repository_service,
        planning_service=planning_service,
        backup_service=backup_service,
        patch_service=patch_service,
        build_service=build_service,
        ollama_service=ollama_service,
        configuration=configuration,
    )

    return service.execute_many(
        tasks,
        event_callback=event_callback,
        stop_on_first_failure=(
            stop_on_first_failure
        ),
        return_domain_models=(
            return_domain_models
        ),
    )


def map_task_request(
    task: TaskRequest | Any,
) -> TaskRequest:
    return _task_request_from_domain_model(
        task
    )


def map_task_result(
    result: TaskExecutionResult,
) -> Any:
    return _task_result_to_domain_model(
        result
    )


def is_successful_task_result(
    result: Any,
) -> bool:
    if isinstance(
        result,
        TaskExecutionResult,
    ):
        return result.succeeded

    explicit_success = _extract_value(
        result,
        (
            "success",
            "succeeded",
        ),
        default=None,
    )

    if explicit_success is not None:
        return _extract_boolean(
            result,
            (
                "success",
                "succeeded",
            ),
            default=False,
        )

    status = _extract_value(
        result,
        (
            "status",
            "task_status",
            "result_status",
        ),
    )

    if isinstance(status, enum.Enum):
        normalized_status = str(
            status.value
        ).strip().casefold()
    elif status is not None:
        normalized_status = str(
            status
        ).strip().casefold()
    else:
        normalized_status = ""

    return normalized_status in {
        TaskStatus.SUCCEEDED.value,
        TaskStatus.DRY_RUN.value,
    }


def get_task_result_error(
    result: Any,
) -> str | None:
    if isinstance(
        result,
        TaskExecutionResult,
    ):
        return result.error_message

    error = _extract_value(
        result,
        (
            "error_message",
            "error",
            "message",
            "failure_reason",
        ),
    )

    if error is None:
        return None

    if isinstance(error, BaseException):
        return _safe_error_message(error)

    normalized = str(error).strip()
    return normalized or None


def get_task_result_changed_paths(
    result: Any,
) -> tuple[str, ...]:
    if isinstance(
        result,
        TaskExecutionResult,
    ):
        return result.changed_paths

    return _extract_paths(result)


def validate_task_service_configuration(
    configuration: TaskServiceConfiguration,
) -> TaskServiceConfiguration:
    if not isinstance(
        configuration,
        TaskServiceConfiguration,
    ):
        try:
            configuration = (
                TaskServiceConfiguration.model_validate(
                    configuration
                )
            )
        except Exception as exc:
            raise TaskConfigurationError(
                f"Invalid task service configuration: "
                f"{_safe_error_message(exc)}"
            ) from exc

    repository_root = (
        configuration.repository_root
    )

    if not repository_root.exists():
        raise TaskConfigurationError(
            f"Repository root does not exist: "
            f"{repository_root}"
        )

    if not repository_root.is_dir():
        raise TaskConfigurationError(
            f"Repository root is not a directory: "
            f"{repository_root}"
        )

    return configuration


def validate_task_service_dependencies(
    *,
    repository_service: RepositoryService,
    planning_service: PlanningService,
    backup_service: BackupService,
    patch_service: PatchService,
    build_service: BuildService,
    ollama_service: OllamaService,
) -> None:
    _validate_service_dependencies(
        repository_service=repository_service,
        planning_service=planning_service,
        backup_service=backup_service,
        patch_service=patch_service,
        build_service=build_service,
        ollama_service=ollama_service,
    )


__all__ = [
    "DEFAULT_TASK_TIMEOUT_SECONDS",
    "DEFAULT_ANALYSIS_TIMEOUT_SECONDS",
    "DEFAULT_PLANNING_TIMEOUT_SECONDS",
    "DEFAULT_PATCH_TIMEOUT_SECONDS",
    "DEFAULT_BUILD_TIMEOUT_SECONDS",
    "DEFAULT_ROLLBACK_TIMEOUT_SECONDS",
    "DEFAULT_MAX_TASK_DESCRIPTION_LENGTH",
    "DEFAULT_MAX_CONTEXT_LENGTH",
    "DEFAULT_MAX_EVENT_COUNT",
    "DEFAULT_MAX_ERROR_MESSAGE_LENGTH",
    "TaskServiceError",
    "TaskConfigurationError",
    "TaskValidationError",
    "TaskSecurityError",
    "TaskAnalysisError",
    "TaskPlanningError",
    "TaskBackupError",
    "TaskPatchError",
    "TaskBuildError",
    "TaskRollbackError",
    "TaskCancellationError",
    "TaskTimeoutError",
    "TaskDependencyError",
    "TaskResultMappingError",
    "TaskStatus",
    "TaskStage",
    "TaskEventLevel",
    "RollbackPolicy",
    "BackupPolicy",
    "BuildPolicy",
    "TaskRequest",
    "TaskServiceConfiguration",
    "TaskEvent",
    "TaskExecutionResult",
    "TaskEventCallback",
    "TaskCancellationToken",
    "TaskExecutionContext",
    "TaskService",
    "create_task_service",
    "execute_code_builder_task",
    "execute_code_builder_tasks",
    "map_task_request",
    "map_task_result",
    "is_successful_task_result",
    "get_task_result_error",
    "get_task_result_changed_paths",
    "validate_task_service_configuration",
    "validate_task_service_dependencies",
]
