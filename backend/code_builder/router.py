from __future__ import annotations

import asyncio
import enum
import logging
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Final, Protocol, cast

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from . import models as domain_models
from .backup_service import BackupService
from .build_service import (
    BuildCommandSpec,
    BuildService,
)
from .ollama_service import OllamaService
from .patch_service import PatchService
from .planning_service import PlanningService
from .repository_service import RepositoryService
from .task_service import (
    BackupPolicy,
    BuildPolicy,
    RollbackPolicy,
    TaskCancellationError,
    TaskCancellationToken,
    TaskExecutionResult,
    TaskRequest,
    TaskResultMappingError,
    TaskService,
    TaskServiceConfiguration,
    TaskServiceError,
    TaskStatus,
    TaskTimeoutError,
    TaskValidationError,
    create_task_service,
    get_task_result_changed_paths,
    get_task_result_error,
    is_successful_task_result,
)


logger = logging.getLogger(__name__)


ROUTER_PREFIX: Final[str] = "/api/code-builder"
ROUTER_TAG: Final[str] = "Code Builder"

DEFAULT_TASK_LIST_LIMIT: Final[int] = 50
MAX_TASK_LIST_LIMIT: Final[int] = 200
DEFAULT_REPOSITORY_DEPTH: Final[int] = 8
MAX_REPOSITORY_DEPTH: Final[int] = 30
DEFAULT_MAX_REPOSITORY_ITEMS: Final[int] = 10_000
MAX_REPOSITORY_ITEMS: Final[int] = 100_000
DEFAULT_MAX_STORED_EVENTS: Final[int] = 2_000
DEFAULT_TASK_RETENTION_SECONDS: Final[float] = 86_400.0
DEFAULT_APPROVAL_TIMEOUT_SECONDS: Final[float] = 86_400.0
MAX_IDEMPOTENCY_KEY_LENGTH: Final[int] = 256
MAX_APPROVAL_COMMENT_LENGTH: Final[int] = 20_000
MAX_ROLLBACK_REASON_LENGTH: Final[int] = 20_000


class CodeBuilderRouterError(RuntimeError):
    """Base exception for Code Builder router failures."""


class CodeBuilderDependencyError(CodeBuilderRouterError):
    """Raised when a required router dependency is unavailable."""


class CodeBuilderTaskNotFoundError(CodeBuilderRouterError):
    """Raised when a Code Builder task cannot be found."""


class CodeBuilderTaskConflictError(CodeBuilderRouterError):
    """Raised when a task operation conflicts with its current state."""


class CodeBuilderApprovalError(CodeBuilderRouterError):
    """Raised when a task cannot be approved."""


class CodeBuilderRollbackError(CodeBuilderRouterError):
    """Raised when a manual rollback cannot be completed."""


class CodeBuilderRepositoryError(CodeBuilderRouterError):
    """Raised when repository inspection fails."""


class CodeBuilderTaskPhase(str, enum.Enum):
    QUEUED = "queued"
    ANALYZING = "analyzing"
    PLANNING = "planning"
    VALIDATING = "validating"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    APPLYING = "applying"
    VERIFYING = "verifying"
    # Backward-compatible aggregate retained for stored/legacy clients.
    EXECUTING = "executing"
    ROLLING_BACK = "rolling_back"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"


class ApprovalDecision(str, enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"


class RepositoryNodeType(str, enum.Enum):
    FILE = "file"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    OTHER = "other"


class TaskCreateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    instruction: str = Field(
        min_length=1,
        max_length=100_000,
    )
    context: str | None = Field(
        default=None,
        max_length=500_000,
    )
    target_paths: tuple[str, ...] = Field(default_factory=tuple)
    excluded_paths: tuple[str, ...] = Field(default_factory=tuple)
    build_commands: tuple[BuildCommandSpec, ...] = Field(
        default_factory=tuple
    )
    task_timeout_seconds: float = Field(
        default=3_600.0,
        gt=0.0,
        le=86_400.0,
    )
    dry_run: bool = False
    require_approval: bool = True
    auto_start_after_approval: bool = True
    allow_file_creation: bool = True
    allow_file_deletion: bool = False
    require_clean_repository: bool = False
    stop_build_on_first_failure: bool = True
    backup_policy: BackupPolicy = BackupPolicy.REQUIRED
    build_policy: BuildPolicy = BuildPolicy.REQUIRED
    rollback_policy: RollbackPolicy = RollbackPolicy.ON_ANY_FAILURE
    metadata: dict[str, Any] = Field(default_factory=dict)

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
                raise ValueError("Repository paths cannot be empty.")

            if "\x00" in path_text:
                raise ValueError(
                    "Repository path contains a null character."
                )

            normalized.append(path_text)

        return tuple(dict.fromkeys(normalized))


class TaskApprovalRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    decision: ApprovalDecision = ApprovalDecision.APPROVE
    comment: str | None = Field(
        default=None,
        max_length=MAX_APPROVAL_COMMENT_LENGTH,
    )
    start_immediately: bool = True

    @field_validator("comment")
    @classmethod
    def validate_comment(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        if "\x00" in value:
            raise ValueError(
                "comment contains a forbidden null character."
            )

        normalized = value.strip()
        return normalized or None


class TaskRollbackRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    reason: str | None = Field(
        default=None,
        max_length=MAX_ROLLBACK_REASON_LENGTH,
    )
    force: bool = False

    @field_validator("reason")
    @classmethod
    def validate_reason(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        if "\x00" in value:
            raise ValueError(
                "reason contains a forbidden null character."
            )

        normalized = value.strip()
        return normalized or None


class TaskCancelRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    reason: str | None = Field(
        default=None,
        max_length=MAX_ROLLBACK_REASON_LENGTH,
    )


class TaskEventResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        from_attributes=True,
    )

    sequence: int | None = None
    timestamp_epoch: float | None = None
    stage: str | None = None
    status: str | None = None
    level: str | None = None
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class TaskSummaryResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        from_attributes=True,
    )

    task_id: str
    phase: CodeBuilderTaskPhase
    instruction: str
    created_at_epoch: float
    updated_at_epoch: float
    started_at_epoch: float | None = None
    finished_at_epoch: float | None = None
    require_approval: bool
    approved: bool
    dry_run: bool
    successful: bool | None = None
    task_status: str | None = None
    changed_paths: tuple[str, ...] = Field(default_factory=tuple)
    error_message: str | None = None


class TaskDetailResponse(TaskSummaryResponse):
    request: dict[str, Any]
    result: dict[str, Any] | None = None
    preparation_result: dict[str, Any] | None = None
    review_result: dict[str, Any] | None = None
    events: tuple[TaskEventResponse, ...] = Field(default_factory=tuple)
    approval_comment: str | None = None
    approved_at_epoch: float | None = None
    rollback_requested: bool = False
    rollback_result: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: tuple[TaskSummaryResponse, ...]
    total: int
    limit: int
    offset: int


class TaskCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: TaskDetailResponse
    accepted: bool = True


class TaskApprovalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: TaskDetailResponse
    approved: bool
    execution_started: bool


class TaskRollbackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: TaskDetailResponse
    rollback_started: bool
    rollback_completed: bool


class RepositoryNodeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    path: str
    node_type: RepositoryNodeType
    size_bytes: int | None = None
    modified_at_epoch: float | None = None
    children: tuple["RepositoryNodeResponse", ...] = Field(
        default_factory=tuple
    )


class RepositoryStructureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository_root: str
    generated_at_epoch: float
    max_depth: int
    item_count: int
    truncated: bool
    root: RepositoryNodeResponse


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: str
    message: str
    task_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    active_tasks: int
    stored_tasks: int
    repository_root: str
    timestamp_epoch: float


class TaskServiceProvider(Protocol):
    def __call__(self) -> TaskService:
        """Return the configured TaskService instance."""


class RepositoryServiceProvider(Protocol):
    def __call__(self) -> RepositoryService:
        """Return the configured RepositoryService instance."""


class BackupServiceProvider(Protocol):
    def __call__(self) -> BackupService:
        """Return the configured BackupService instance."""


@dataclass(slots=True)
class StoredTask:
    request: TaskRequest
    api_request: TaskCreateRequest
    phase: CodeBuilderTaskPhase
    created_at_epoch: float
    updated_at_epoch: float
    require_approval: bool
    auto_start_after_approval: bool
    cancellation_token: TaskCancellationToken
    result: Any = None
    preparation_result: Any = None
    review_result: Any = None
    started_at_epoch: float | None = None
    finished_at_epoch: float | None = None
    approved_at_epoch: float | None = None
    approval_comment: str | None = None
    rollback_requested: bool = False
    rollback_result: Any = None
    events: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    execution_lock: threading.RLock = field(
        default_factory=threading.RLock,
        repr=False,
    )

    def touch(self) -> None:
        self.updated_at_epoch = time.time()


class TaskStore:
    def __init__(
        self,
        *,
        max_stored_events: int = DEFAULT_MAX_STORED_EVENTS,
        retention_seconds: float = DEFAULT_TASK_RETENTION_SECONDS,
    ) -> None:
        if max_stored_events <= 0:
            raise ValueError(
                "max_stored_events must be greater than zero."
            )

        if retention_seconds <= 0:
            raise ValueError(
                "retention_seconds must be greater than zero."
            )

        self._max_stored_events = max_stored_events
        self._retention_seconds = retention_seconds
        self._tasks: dict[str, StoredTask] = {}
        self._idempotency_keys: dict[str, str] = {}
        self._lock = threading.RLock()

    def create(
        self,
        stored_task: StoredTask,
        *,
        idempotency_key: str | None = None,
    ) -> StoredTask:
        with self._lock:
            self._purge_expired_locked()

            existing = self._tasks.get(
                stored_task.request.task_id
            )

            if existing is not None:
                raise CodeBuilderTaskConflictError(
                    f"Task {stored_task.request.task_id!r} already exists."
                )

            if idempotency_key:
                existing_task_id = self._idempotency_keys.get(
                    idempotency_key
                )

                if existing_task_id:
                    existing_task = self._tasks.get(
                        existing_task_id
                    )

                    if existing_task is not None:
                        return existing_task

                self._idempotency_keys[
                    idempotency_key
                ] = stored_task.request.task_id

            self._tasks[
                stored_task.request.task_id
            ] = stored_task

            return stored_task

    def get(self, task_id: str) -> StoredTask:
        with self._lock:
            self._purge_expired_locked()

            stored_task = self._tasks.get(task_id)

            if stored_task is None:
                raise CodeBuilderTaskNotFoundError(
                    f"Task {task_id!r} was not found."
                )

            return stored_task

    def list(
        self,
        *,
        offset: int,
        limit: int,
        phases: set[CodeBuilderTaskPhase] | None = None,
    ) -> tuple[tuple[StoredTask, ...], int]:
        with self._lock:
            self._purge_expired_locked()

            tasks = sorted(
                self._tasks.values(),
                key=lambda item: item.created_at_epoch,
                reverse=True,
            )

            if phases:
                tasks = [
                    task
                    for task in tasks
                    if task.phase in phases
                ]

            total = len(tasks)
            page = tuple(tasks[offset : offset + limit])

            return page, total

    def append_event(
        self,
        task_id: str,
        event: Any,
    ) -> None:
        with self._lock:
            task = self._tasks.get(task_id)

            if task is None:
                return

            serialized = _serialize_value(event)

            if isinstance(serialized, Mapping):
                task.events.append(dict(serialized))
            else:
                task.events.append(
                    {
                        "message": str(serialized),
                    }
                )

            if len(task.events) > self._max_stored_events:
                overflow = (
                    len(task.events)
                    - self._max_stored_events
                )
                del task.events[:overflow]

            task.touch()

    def remove(self, task_id: str) -> bool:
        with self._lock:
            removed = self._tasks.pop(
                task_id,
                None,
            )

            if removed is None:
                return False

            stale_keys = [
                key
                for key, mapped_task_id
                in self._idempotency_keys.items()
                if mapped_task_id == task_id
            ]

            for key in stale_keys:
                self._idempotency_keys.pop(
                    key,
                    None,
                )

            return True

    def count(self) -> int:
        with self._lock:
            self._purge_expired_locked()
            return len(self._tasks)

    def _purge_expired_locked(self) -> None:
        now = time.time()

        removable_phases = {
            CodeBuilderTaskPhase.COMPLETED,
            CodeBuilderTaskPhase.FAILED,
            CodeBuilderTaskPhase.CANCELLED,
            CodeBuilderTaskPhase.TIMED_OUT,
            CodeBuilderTaskPhase.ROLLED_BACK,
            CodeBuilderTaskPhase.ROLLBACK_FAILED,
        }

        expired_task_ids = [
            task_id
            for task_id, task in self._tasks.items()
            if task.phase in removable_phases
            and (
                now - task.updated_at_epoch
                >= self._retention_seconds
            )
        ]

        for task_id in expired_task_ids:
            self.remove(task_id)


class CodeBuilderRouterDependencies:
    def __init__(
        self,
        *,
        task_service: TaskService,
        repository_service: RepositoryService,
        backup_service: BackupService,
        task_store: TaskStore | None = None,
    ) -> None:
        if task_service is None:
            raise CodeBuilderDependencyError(
                "task_service is required."
            )

        if repository_service is None:
            raise CodeBuilderDependencyError(
                "repository_service is required."
            )

        if backup_service is None:
            raise CodeBuilderDependencyError(
                "backup_service is required."
            )

        self.task_service = task_service
        self.repository_service = repository_service
        self.backup_service = backup_service
        self.task_store = task_store or TaskStore()


_router_dependencies: CodeBuilderRouterDependencies | None = None
_router_dependencies_lock = threading.RLock()


def configure_code_builder_router(
    *,
    task_service: TaskService,
    repository_service: RepositoryService,
    backup_service: BackupService,
    task_store: TaskStore | None = None,
) -> CodeBuilderRouterDependencies:
    global _router_dependencies

    dependencies = CodeBuilderRouterDependencies(
        task_service=task_service,
        repository_service=repository_service,
        backup_service=backup_service,
        task_store=task_store,
    )

    with _router_dependencies_lock:
        _router_dependencies = dependencies

    return dependencies


def get_router_dependencies() -> CodeBuilderRouterDependencies:
    with _router_dependencies_lock:
        dependencies = _router_dependencies

    if dependencies is None:
        raise CodeBuilderDependencyError(
            "Code Builder router has not been configured. "
            "Call configure_code_builder_router during application startup."
        )

    return dependencies


def get_task_service(
    dependencies: Annotated[
        CodeBuilderRouterDependencies,
        Depends(get_router_dependencies),
    ],
) -> TaskService:
    return dependencies.task_service


def get_repository_service(
    dependencies: Annotated[
        CodeBuilderRouterDependencies,
        Depends(get_router_dependencies),
    ],
) -> RepositoryService:
    return dependencies.repository_service


def get_backup_service(
    dependencies: Annotated[
        CodeBuilderRouterDependencies,
        Depends(get_router_dependencies),
    ],
) -> BackupService:
    return dependencies.backup_service


def get_task_store(
    dependencies: Annotated[
        CodeBuilderRouterDependencies,
        Depends(get_router_dependencies),
    ],
) -> TaskStore:
    return dependencies.task_store


def _serialize_value(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(
        value,
        (
            str,
            int,
            float,
            bool,
        ),
    ):
        return value

    if isinstance(value, enum.Enum):
        return value.value

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, BaseModel):
        return value.model_dump(
            mode="json",
        )

    model_dump = getattr(
        value,
        "model_dump",
        None,
    )

    if callable(model_dump):
        try:
            return model_dump(mode="json")
        except TypeError:
            return model_dump()

    if isinstance(value, Mapping):
        return {
            str(key): _serialize_value(item)
            for key, item in value.items()
        }

    if isinstance(value, Sequence) and not isinstance(
        value,
        (
            str,
            bytes,
            bytearray,
        ),
    ):
        return [
            _serialize_value(item)
            for item in value
        ]

    if hasattr(value, "__dict__"):
        return {
            str(key): _serialize_value(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }

    return str(value)


def _normalize_idempotency_key(
    value: str | None,
) -> str | None:
    if value is None:
        return None

    normalized = value.strip()

    if not normalized:
        return None

    if len(normalized) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_idempotency_key",
                "message": (
                    "Idempotency-Key exceeds the maximum "
                    f"length of {MAX_IDEMPOTENCY_KEY_LENGTH}."
                ),
            },
        )

    if "\x00" in normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_idempotency_key",
                "message": (
                    "Idempotency-Key contains a forbidden "
                    "null character."
                ),
            },
        )

    return normalized


def _task_request_from_api(
    payload: TaskCreateRequest,
    *,
    task_id: str,
) -> TaskRequest:
    return TaskRequest(
        task_id=task_id,
        instruction=payload.instruction,
        context=payload.context,
        target_paths=payload.target_paths,
        excluded_paths=payload.excluded_paths,
        build_commands=payload.build_commands,
        task_timeout_seconds=(
            payload.task_timeout_seconds
        ),
        dry_run=payload.dry_run,
        allow_file_creation=(
            payload.allow_file_creation
        ),
        allow_file_deletion=(
            payload.allow_file_deletion
        ),
        require_clean_repository=(
            payload.require_clean_repository
        ),
        stop_build_on_first_failure=(
            payload.stop_build_on_first_failure
        ),
        backup_policy=payload.backup_policy,
        build_policy=payload.build_policy,
        rollback_policy=payload.rollback_policy,
        metadata=dict(payload.metadata),
    )


def _build_preparation_request(stored_task: StoredTask) -> TaskRequest:
    metadata = dict(stored_task.request.metadata)
    metadata["code_builder_preparation"] = True
    return stored_task.request.model_copy(
        update={
            "dry_run": True,
            "backup_policy": BackupPolicy.DISABLED,
            "build_policy": BuildPolicy.DISABLED,
            "rollback_policy": RollbackPolicy.NEVER,
            "metadata": metadata,
        }
    )


def _lock_prepared_operations_to_validation(
    prepared: Mapping[str, Any],
    raw_operations: Sequence[Any],
) -> list[Any]:
    validation = prepared.get("patch_validation")
    validation_results = (
        validation.get("results")
        if isinstance(validation, Mapping)
        else None
    )
    results = (
        list(validation_results)
        if isinstance(validation_results, Sequence)
        and not isinstance(validation_results, (str, bytes, bytearray))
        else []
    )

    by_operation_id: dict[str, Mapping[str, Any]] = {}
    for result in results:
        if not isinstance(result, Mapping):
            continue
        operation_id = result.get("operation_id")
        if operation_id is not None:
            by_operation_id[str(operation_id)] = result

    locked: list[Any] = []
    for index, raw_operation in enumerate(raw_operations):
        if not isinstance(raw_operation, Mapping):
            locked.append(raw_operation)
            continue

        operation = dict(raw_operation)
        if operation.get("expected_sha256"):
            locked.append(operation)
            continue

        validation_result: Mapping[str, Any] | None = None
        operation_id = operation.get("operation_id")
        if operation_id is not None:
            validation_result = by_operation_id.get(str(operation_id))

        if validation_result is None and index < len(results):
            candidate = results[index]
            if isinstance(candidate, Mapping):
                operation_path = str(operation.get("path") or "")
                result_path = str(candidate.get("path") or candidate.get("relative_path") or "")
                if not operation_path or operation_path == result_path:
                    validation_result = candidate

        if validation_result is not None:
            original_sha256 = validation_result.get("original_sha256")
            if original_sha256:
                operation["expected_sha256"] = str(original_sha256)

        locked.append(operation)

    return locked


def _bind_prepared_patch_to_request(stored_task: StoredTask) -> TaskRequest:
    prepared = _serialize_value(stored_task.preparation_result)
    if not isinstance(prepared, Mapping):
        raise CodeBuilderApprovalError(
            "Task does not have a completed preparation result."
        )

    raw_patch = prepared.get("patch")
    if not isinstance(raw_patch, Mapping):
        raise CodeBuilderApprovalError(
            "Task preparation did not produce an approvable patch."
        )

    raw_operations = raw_patch.get("operations")
    if not isinstance(raw_operations, Sequence) or isinstance(
        raw_operations, (str, bytes, bytearray)
    ) or not raw_operations:
        raise CodeBuilderApprovalError(
            "Task preparation did not produce patch operations."
        )

    metadata = dict(stored_task.request.metadata)
    metadata.pop("patch_operations", None)
    metadata.pop("execution_patch_operations", None)
    metadata["approved_patch_operations"] = _lock_prepared_operations_to_validation(
        prepared,
        raw_operations,
    )
    metadata["approved_preparation_plan"] = prepared.get("plan")
    metadata["approved_preparation_task_id"] = stored_task.request.task_id
    return stored_task.request.model_copy(update={"metadata": metadata})


def _review_prepared_change(
    *,
    task_service: TaskService,
    stored_task: StoredTask,
    preparation_result: Any,
) -> dict[str, Any]:
    reviewer = getattr(
        task_service.ollama_service,
        "analyze_code_task",
        None,
    )
    model = getattr(
        task_service.ollama_service,
        "model",
        None,
    )

    if not callable(reviewer):
        return {
            "status": "unavailable",
            "model": str(model) if model else None,
            "summary": (
                "AI review is unavailable because the configured Code "
                "Builder Ollama adapter does not expose a synchronous "
                "review-compatible analysis method."
            ),
            "reviewed_at_epoch": time.time(),
        }

    serialized_preparation = _serialize_value(preparation_result)
    review_instruction = (
        "Act as the independent LUMINA Code Builder reviewer. Review ONLY "
        "the supplied prepared implementation plan, proposed patch/diff, "
        "and patch validation. Do not generate replacement code and do not "
        "modify files. Check scope alignment, correctness risks, unsafe or "
        "destructive changes, missing tests, plan/patch mismatches, and "
        "rollback concerns. Give a concise verdict using PASS, WARN, or "
        "BLOCK, followed by concrete findings with file paths when known."
    )

    try:
        content = reviewer(
            instruction=review_instruction,
            repository_context=serialized_preparation,
            user_context={
                "original_instruction": stored_task.request.instruction,
                "task_id": stored_task.request.task_id,
                "purpose": "pre_approval_review",
            },
            target_paths=stored_task.request.target_paths,
            excluded_paths=stored_task.request.excluded_paths,
            timeout_seconds=min(
                stored_task.request.task_timeout_seconds,
                300.0,
            ),
            cancellation_token=stored_task.cancellation_token,
        )
    except Exception as exc:
        logger.warning(
            "Code Builder AI review failed for task %s: %s",
            stored_task.request.task_id,
            exc,
        )
        return {
            "status": "unavailable",
            "model": str(model) if model else None,
            "summary": f"AI review failed: {exc}",
            "reviewed_at_epoch": time.time(),
        }

    normalized = str(content).strip()
    first_line = (
        normalized.splitlines()[0].strip().upper()
        if normalized
        else ""
    )
    verdict = (
        "block"
        if first_line.startswith("BLOCK")
        else "warn"
        if first_line.startswith("WARN")
        else "pass"
        if first_line.startswith("PASS")
        else "warn"
    )
    return {
        "status": "completed",
        "verdict": verdict,
        "model": str(model) if model else None,
        "summary": normalized,
        "reviewed_at_epoch": time.time(),
    }


def _phase_from_result(
    result: Any,
) -> CodeBuilderTaskPhase:
    status_value: Any = None

    if isinstance(result, TaskExecutionResult):
        status_value = result.status
    elif isinstance(result, Mapping):
        status_value = (
            result.get("status")
            or result.get("task_status")
            or result.get("result_status")
        )
    else:
        for attribute_name in (
            "status",
            "task_status",
            "result_status",
        ):
            if hasattr(result, attribute_name):
                status_value = getattr(
                    result,
                    attribute_name,
                )
                break

    if isinstance(status_value, enum.Enum):
        normalized = str(
            status_value.value
        ).strip().casefold()
    elif status_value is None:
        normalized = ""
    else:
        normalized = str(
            status_value
        ).strip().casefold()

    mapping = {
        TaskStatus.SUCCEEDED.value: (
            CodeBuilderTaskPhase.COMPLETED
        ),
        TaskStatus.DRY_RUN.value: (
            CodeBuilderTaskPhase.COMPLETED
        ),
        TaskStatus.FAILED.value: (
            CodeBuilderTaskPhase.FAILED
        ),
        TaskStatus.CANCELLED.value: (
            CodeBuilderTaskPhase.CANCELLED
        ),
        TaskStatus.TIMED_OUT.value: (
            CodeBuilderTaskPhase.TIMED_OUT
        ),
        TaskStatus.ROLLED_BACK.value: (
            CodeBuilderTaskPhase.ROLLED_BACK
        ),
        TaskStatus.ROLLBACK_FAILED.value: (
            CodeBuilderTaskPhase.ROLLBACK_FAILED
        ),
    }

    return mapping.get(
        normalized,
        CodeBuilderTaskPhase.FAILED,
    )


def _task_summary_response(
    stored_task: StoredTask,
) -> TaskSummaryResponse:
    result = stored_task.result

    successful: bool | None = None
    task_status: str | None = None
    changed_paths: tuple[str, ...] = ()
    error_message: str | None = None

    if result is not None:
        successful = is_successful_task_result(
            result
        )
        changed_paths = (
            get_task_result_changed_paths(
                result
            )
        )
        error_message = get_task_result_error(
            result
        )

        serialized_result = _serialize_value(
            result
        )

        if isinstance(
            serialized_result,
            Mapping,
        ):
            raw_status = (
                serialized_result.get("status")
                or serialized_result.get(
                    "task_status"
                )
                or serialized_result.get(
                    "result_status"
                )
            )

            if raw_status is not None:
                task_status = str(raw_status)

    return TaskSummaryResponse(
        task_id=stored_task.request.task_id,
        phase=stored_task.phase,
        instruction=stored_task.request.instruction,
        created_at_epoch=(
            stored_task.created_at_epoch
        ),
        updated_at_epoch=(
            stored_task.updated_at_epoch
        ),
        started_at_epoch=(
            stored_task.started_at_epoch
        ),
        finished_at_epoch=(
            stored_task.finished_at_epoch
        ),
        require_approval=(
            stored_task.require_approval
        ),
        approved=(
            stored_task.approved_at_epoch
            is not None
        ),
        dry_run=stored_task.request.dry_run,
        successful=successful,
        task_status=task_status,
        changed_paths=changed_paths,
        error_message=error_message,
    )


def _task_detail_response(
    stored_task: StoredTask,
) -> TaskDetailResponse:
    summary = _task_summary_response(
        stored_task
    )

    events = tuple(
        TaskEventResponse.model_validate(
            event
        )
        for event in stored_task.events
    )

    serialized_result = _serialize_value(
        stored_task.result
    )
    serialized_preparation = _serialize_value(
        stored_task.preparation_result
    )
    serialized_review = _serialize_value(
        stored_task.review_result
    )

    serialized_rollback = _serialize_value(
        stored_task.rollback_result
    )

    return TaskDetailResponse(
        **summary.model_dump(),
        request=stored_task.api_request.model_dump(
            mode="json"
        ),
        result=(
            dict(serialized_result)
            if isinstance(
                serialized_result,
                Mapping,
            )
            else (
                {
                    "value": serialized_result,
                }
                if serialized_result is not None
                else None
            )
        ),
        preparation_result=(
            dict(serialized_preparation)
            if isinstance(serialized_preparation, Mapping)
            else None
        ),
        review_result=(
            dict(serialized_review)
            if isinstance(serialized_review, Mapping)
            else None
        ),
        events=events,
        approval_comment=(
            stored_task.approval_comment
        ),
        approved_at_epoch=(
            stored_task.approved_at_epoch
        ),
        rollback_requested=(
            stored_task.rollback_requested
        ),
        rollback_result=(
            dict(serialized_rollback)
            if isinstance(
                serialized_rollback,
                Mapping,
            )
            else (
                {
                    "value": serialized_rollback,
                }
                if serialized_rollback is not None
                else None
            )
        ),
        metadata=dict(
            stored_task.metadata
        ),
    )


def _raise_task_not_found(
    task_id: str,
) -> None:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "error": "task_not_found",
            "message": (
                f"Code Builder task {task_id!r} "
                "was not found."
            ),
            "task_id": task_id,
        },
    )


def _get_task_or_404(
    task_store: TaskStore,
    task_id: str,
) -> StoredTask:
    try:
        return task_store.get(task_id)
    except CodeBuilderTaskNotFoundError:
        _raise_task_not_found(task_id)

    raise AssertionError(
        "Unreachable task lookup branch."
    )


def _validate_task_id(task_id: str) -> str:
    normalized = task_id.strip()

    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_task_id",
                "message": "task_id cannot be empty.",
            },
        )

    allowed = set(
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789"
        "_.:-"
    )

    if any(
        character not in allowed
        for character in normalized
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_task_id",
                "message": (
                    "task_id contains unsupported characters."
                ),
            },
        )

    return normalized


def _phase_allows_approval(
    phase: CodeBuilderTaskPhase,
) -> bool:
    return phase in {
        CodeBuilderTaskPhase.AWAITING_APPROVAL,
        CodeBuilderTaskPhase.QUEUED,
    }


def _phase_allows_cancellation(
    phase: CodeBuilderTaskPhase,
) -> bool:
    return phase in {
        CodeBuilderTaskPhase.QUEUED,
        CodeBuilderTaskPhase.ANALYZING,
        CodeBuilderTaskPhase.PLANNING,
        CodeBuilderTaskPhase.VALIDATING,
        CodeBuilderTaskPhase.AWAITING_APPROVAL,
        CodeBuilderTaskPhase.APPROVED,
        CodeBuilderTaskPhase.APPLYING,
        CodeBuilderTaskPhase.VERIFYING,
        CodeBuilderTaskPhase.EXECUTING,
    }


def _phase_allows_rollback(
    phase: CodeBuilderTaskPhase,
) -> bool:
    return phase in {
        CodeBuilderTaskPhase.COMPLETED,
        CodeBuilderTaskPhase.FAILED,
        CodeBuilderTaskPhase.CANCELLED,
        CodeBuilderTaskPhase.TIMED_OUT,
        CodeBuilderTaskPhase.ROLLBACK_FAILED,
    }


def _repository_root_from_task_service(
    task_service: TaskService,
) -> Path:
    configuration = getattr(
        task_service,
        "configuration",
        None,
    )

    repository_root = getattr(
        configuration,
        "repository_root",
        None,
    )

    if repository_root is None:
        raise CodeBuilderDependencyError(
            "TaskService configuration does not expose "
            "repository_root."
        )

    return Path(repository_root).resolve()


router = APIRouter(
    prefix=ROUTER_PREFIX,
    tags=[ROUTER_TAG],
    responses={
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponse,
            "description": "Internal Code Builder error.",
        },
    },
)
def _update_phase_from_event(
    stored_task: StoredTask,
    event: Any,
) -> None:
    serialized = _serialize_value(event)

    if not isinstance(serialized, Mapping):
        return

    raw_status = serialized.get("status")
    raw_stage = serialized.get("stage")

    normalized_status = (
        str(raw_status).strip().casefold()
        if raw_status is not None
        else ""
    )

    normalized_stage = (
        str(raw_stage).strip().casefold()
        if raw_stage is not None
        else ""
    )

    status_phase_mapping = {
        TaskStatus.ANALYZING.value: (
            CodeBuilderTaskPhase.ANALYZING
        ),
        TaskStatus.PLANNING.value: (
            CodeBuilderTaskPhase.PLANNING
        ),
        TaskStatus.BACKING_UP.value: (
            CodeBuilderTaskPhase.APPLYING
        ),
        TaskStatus.GENERATING_PATCH.value: (
            CodeBuilderTaskPhase.VALIDATING
        ),
        TaskStatus.VALIDATING_PATCH.value: (
            CodeBuilderTaskPhase.VALIDATING
        ),
        TaskStatus.APPLYING_PATCH.value: (
            CodeBuilderTaskPhase.APPLYING
        ),
        TaskStatus.BUILDING.value: (
            CodeBuilderTaskPhase.VERIFYING
        ),
        TaskStatus.ROLLING_BACK.value: (
            CodeBuilderTaskPhase.ROLLING_BACK
        ),
        TaskStatus.SUCCEEDED.value: (
            CodeBuilderTaskPhase.COMPLETED
        ),
        TaskStatus.DRY_RUN.value: (
            CodeBuilderTaskPhase.COMPLETED
        ),
        TaskStatus.FAILED.value: (
            CodeBuilderTaskPhase.FAILED
        ),
        TaskStatus.CANCELLED.value: (
            CodeBuilderTaskPhase.CANCELLED
        ),
        TaskStatus.TIMED_OUT.value: (
            CodeBuilderTaskPhase.TIMED_OUT
        ),
        TaskStatus.ROLLED_BACK.value: (
            CodeBuilderTaskPhase.ROLLED_BACK
        ),
        TaskStatus.ROLLBACK_FAILED.value: (
            CodeBuilderTaskPhase.ROLLBACK_FAILED
        ),
    }

    new_phase = status_phase_mapping.get(
        normalized_status
    )

    if new_phase is None:
        if normalized_stage == "analysis":
            new_phase = CodeBuilderTaskPhase.ANALYZING
        elif normalized_stage == "planning":
            new_phase = CodeBuilderTaskPhase.PLANNING
        elif normalized_stage in {
            "patch_generation",
            "patch_validation",
        }:
            new_phase = CodeBuilderTaskPhase.VALIDATING
        elif normalized_stage in {
            "backup",
            "patch_application",
        }:
            new_phase = CodeBuilderTaskPhase.APPLYING
        elif normalized_stage == "build":
            new_phase = CodeBuilderTaskPhase.VERIFYING
        elif normalized_stage == "rollback":
            new_phase = CodeBuilderTaskPhase.ROLLING_BACK

    if (
        stored_task.require_approval
        and stored_task.approved_at_epoch is None
        and new_phase in {
            CodeBuilderTaskPhase.APPLYING,
            CodeBuilderTaskPhase.VERIFYING,
            CodeBuilderTaskPhase.EXECUTING,
            CodeBuilderTaskPhase.COMPLETED,
        }
    ):
        # Preparation may generate/validate a diff, but public state must never
        # imply repository mutation before explicit approval.
        new_phase = CodeBuilderTaskPhase.VALIDATING

    if new_phase is not None:
        stored_task.phase = new_phase

    stored_task.touch()


def _task_event_callback(
    task_store: TaskStore,
    stored_task: StoredTask,
) -> Callable[[Any], None]:
    def callback(event: Any) -> None:
        task_store.append_event(
            stored_task.request.task_id,
            event,
        )
        _update_phase_from_event(
            stored_task,
            event,
        )

    return callback


def _store_execution_failure(
    stored_task: StoredTask,
    error: BaseException,
) -> None:
    stored_task.result = {
        "task_id": stored_task.request.task_id,
        "status": TaskStatus.FAILED.value,
        "success": False,
        "error_type": type(error).__name__,
        "error_message": str(error),
    }

    if isinstance(
        error,
        TaskCancellationError,
    ):
        stored_task.phase = (
            CodeBuilderTaskPhase.CANCELLED
        )
    elif isinstance(
        error,
        TaskTimeoutError,
    ):
        stored_task.phase = (
            CodeBuilderTaskPhase.TIMED_OUT
        )
    else:
        stored_task.phase = (
            CodeBuilderTaskPhase.FAILED
        )

    stored_task.finished_at_epoch = time.time()
    stored_task.touch()


def _run_stored_task_sync(
    *,
    task_service: TaskService,
    task_store: TaskStore,
    stored_task: StoredTask,
) -> None:
    with stored_task.execution_lock:
        if stored_task.phase in {
            CodeBuilderTaskPhase.APPLYING,
            CodeBuilderTaskPhase.VERIFYING,
            CodeBuilderTaskPhase.EXECUTING,
            CodeBuilderTaskPhase.COMPLETED,
            CodeBuilderTaskPhase.ROLLED_BACK,
        }:
            return

        preparing = (
            stored_task.require_approval
            and stored_task.approved_at_epoch is None
        )
        stored_task.phase = (
            CodeBuilderTaskPhase.ANALYZING
            if preparing
            else CodeBuilderTaskPhase.APPLYING
        )
        stored_task.started_at_epoch = time.time()
        stored_task.finished_at_epoch = None
        stored_task.touch()

    callback = _task_event_callback(
        task_store,
        stored_task,
    )
    execution_request = (
        _build_preparation_request(stored_task)
        if preparing
        else stored_task.request
    )

    try:
        result = task_service.execute(
            execution_request,
            event_callback=callback,
            cancellation_token=(
                stored_task.cancellation_token
            ),
            return_domain_model=False,
        )
    except BaseException as exc:
        logger.exception(
            "Code Builder task %s failed outside the "
            "normal result pipeline.",
            stored_task.request.task_id,
        )

        with stored_task.execution_lock:
            _store_execution_failure(
                stored_task,
                exc,
            )

        return

    with stored_task.execution_lock:
        stored_task.result = result
        if preparing:
            if _phase_from_result(result) is not CodeBuilderTaskPhase.COMPLETED:
                stored_task.phase = _phase_from_result(result)
                stored_task.finished_at_epoch = time.time()
            else:
                stored_task.preparation_result = result
                stored_task.review_result = _review_prepared_change(
                    task_service=task_service,
                    stored_task=stored_task,
                    preparation_result=result,
                )
                stored_task.phase = CodeBuilderTaskPhase.AWAITING_APPROVAL
                stored_task.metadata["preparation_completed_at_epoch"] = time.time()
                stored_task.finished_at_epoch = None
        else:
            stored_task.phase = _phase_from_result(result)
            stored_task.finished_at_epoch = time.time()
        stored_task.touch()


async def _run_stored_task(
    *,
    task_service: TaskService,
    task_store: TaskStore,
    stored_task: StoredTask,
) -> None:
    await asyncio.to_thread(
        _run_stored_task_sync,
        task_service=task_service,
        task_store=task_store,
        stored_task=stored_task,
    )


def _schedule_task_execution(
    *,
    background_tasks: BackgroundTasks,
    task_service: TaskService,
    task_store: TaskStore,
    stored_task: StoredTask,
) -> None:
    background_tasks.add_task(
        _run_stored_task,
        task_service=task_service,
        task_store=task_store,
        stored_task=stored_task,
    )


def _call_service_method(
    service: Any,
    method_names: Sequence[str],
    *,
    keyword_variants: Sequence[Mapping[str, Any]],
    positional_variants: Sequence[tuple[Any, ...]],
    operation_name: str,
) -> Any:
    available_methods = [
        getattr(service, method_name)
        for method_name in method_names
        if callable(
            getattr(
                service,
                method_name,
                None,
            )
        )
    ]

    if not available_methods:
        raise CodeBuilderDependencyError(
            f"No compatible service method is available "
            f"for {operation_name}."
        )

    invocation_errors: list[BaseException] = []

    for method in available_methods:
        for keyword_arguments in keyword_variants:
            filtered_arguments = {
                key: value
                for key, value
                in keyword_arguments.items()
                if value is not None
            }

            try:
                return method(
                    **filtered_arguments
                )
            except TypeError as exc:
                invocation_errors.append(exc)
                continue

        for positional_arguments in positional_variants:
            try:
                return method(
                    *positional_arguments
                )
            except TypeError as exc:
                invocation_errors.append(exc)
                continue

    error_summary = "; ".join(
        str(error)
        for error in invocation_errors[-3:]
    )

    raise CodeBuilderDependencyError(
        f"Could not invoke a compatible service method "
        f"for {operation_name}. {error_summary}"
    )


def _manual_rollback_sync(
    *,
    task_service: TaskService,
    backup_service: BackupService,
    stored_task: StoredTask,
    reason: str | None,
    force: bool,
) -> Any:
    with stored_task.execution_lock:
        if stored_task.rollback_requested:
            raise CodeBuilderTaskConflictError(
                "Rollback has already been requested "
                "for this task."
            )

        if (
            not force
            and not _phase_allows_rollback(
                stored_task.phase
            )
        ):
            raise CodeBuilderTaskConflictError(
                f"Task cannot be rolled back while in "
                f"phase {stored_task.phase.value!r}."
            )

        stored_task.rollback_requested = True
        stored_task.phase = (
            CodeBuilderTaskPhase.ROLLING_BACK
        )
        stored_task.touch()

    result_payload = _serialize_value(
        stored_task.result
    )

    backup_reference: Any = None
    patch_reference: Any = None
    changed_paths: tuple[str, ...] = ()

    if isinstance(
        stored_task.result,
        TaskExecutionResult,
    ):
        backup_reference = (
            stored_task.result.backup
        )
        patch_reference = (
            stored_task.result.patch_application
            or stored_task.result.patch
        )
        changed_paths = (
            stored_task.result.changed_paths
        )
    elif isinstance(
        result_payload,
        Mapping,
    ):
        backup_reference = (
            result_payload.get("backup")
            or result_payload.get(
                "backup_result"
            )
            or result_payload.get(
                "backup_reference"
            )
        )
        patch_reference = (
            result_payload.get(
                "patch_application"
            )
            or result_payload.get(
                "patch"
            )
            or result_payload.get(
                "apply_result"
            )
        )

        raw_paths = (
            result_payload.get(
                "changed_paths"
            )
            or result_payload.get(
                "modified_paths"
            )
            or ()
        )

        if isinstance(
            raw_paths,
            Sequence,
        ) and not isinstance(
            raw_paths,
            (
                str,
                bytes,
                bytearray,
            ),
        ):
            changed_paths = tuple(
                str(path)
                for path in raw_paths
            )

    if backup_reference is None:
        with stored_task.execution_lock:
            stored_task.phase = (
                CodeBuilderTaskPhase.ROLLBACK_FAILED
            )
            stored_task.touch()

        raise CodeBuilderRollbackError(
            "The task result does not contain a "
            "backup reference."
        )

    try:
        rollback_result = _call_service_method(
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
                    "backup": backup_reference,
                    "backup_reference": (
                        backup_reference
                    ),
                    "task_id": (
                        stored_task.request.task_id
                    ),
                    "repository_root": (
                        _repository_root_from_task_service(
                            task_service
                        )
                    ),
                    "changed_paths": changed_paths,
                    "reason": reason,
                    "force": force,
                },
                {
                    "backup_result": (
                        backup_reference
                    ),
                    "task": stored_task.request,
                    "reason": reason,
                },
                {
                    "snapshot": backup_reference,
                },
            ),
            positional_variants=(
                (backup_reference,),
                (
                    stored_task.request.task_id,
                    backup_reference,
                ),
            ),
            operation_name="manual rollback",
        )
    except BaseException:
        with stored_task.execution_lock:
            stored_task.phase = (
                CodeBuilderTaskPhase.ROLLBACK_FAILED
            )
            stored_task.finished_at_epoch = (
                time.time()
            )
            stored_task.touch()

        raise

    serialized_rollback = _serialize_value(
        rollback_result
    )

    rollback_success = True

    if isinstance(
        serialized_rollback,
        Mapping,
    ):
        for success_key in (
            "success",
            "succeeded",
            "restored",
            "rolled_back",
            "completed",
        ):
            if success_key in serialized_rollback:
                rollback_success = bool(
                    serialized_rollback[
                        success_key
                    ]
                )
                break

    with stored_task.execution_lock:
        stored_task.rollback_result = (
            rollback_result
        )
        stored_task.finished_at_epoch = time.time()
        stored_task.phase = (
            CodeBuilderTaskPhase.ROLLED_BACK
            if rollback_success
            else CodeBuilderTaskPhase.ROLLBACK_FAILED
        )
        stored_task.touch()

    if not rollback_success:
        raise CodeBuilderRollbackError(
            "Backup service reported an "
            "unsuccessful rollback."
        )

    return rollback_result


async def _manual_rollback(
    *,
    task_service: TaskService,
    backup_service: BackupService,
    stored_task: StoredTask,
    reason: str | None,
    force: bool,
) -> Any:
    return await asyncio.to_thread(
        _manual_rollback_sync,
        task_service=task_service,
        backup_service=backup_service,
        stored_task=stored_task,
        reason=reason,
        force=force,
    )


def _is_hidden_path(
    path: Path,
    *,
    repository_root: Path,
) -> bool:
    try:
        relative = path.relative_to(
            repository_root
        )
    except ValueError:
        return True

    ignored_names = {
        ".git",
        ".idea",
        ".vscode",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        ".next",
        ".venv",
        "venv",
    }

    return any(
        part in ignored_names
        for part in relative.parts
    )


def _scan_repository_node(
    path: Path,
    *,
    repository_root: Path,
    current_depth: int,
    max_depth: int,
    include_hidden: bool,
    max_items: int,
    counter: list[int],
    truncated: list[bool],
) -> RepositoryNodeResponse:
    if counter[0] >= max_items:
        truncated[0] = True

        return RepositoryNodeResponse(
            name=path.name or path.anchor,
            path=(
                "."
                if path == repository_root
                else path.relative_to(
                    repository_root
                ).as_posix()
            ),
            node_type=(
                RepositoryNodeType.DIRECTORY
                if path.is_dir()
                else RepositoryNodeType.FILE
            ),
        )

    counter[0] += 1

    try:
        stat_result = path.lstat()
    except OSError as exc:
        logger.warning(
            "Could not stat repository path %s: %s",
            path,
            exc,
        )

        return RepositoryNodeResponse(
            name=path.name or path.anchor,
            path=(
                "."
                if path == repository_root
                else path.relative_to(
                    repository_root
                ).as_posix()
            ),
            node_type=RepositoryNodeType.OTHER,
        )

    if path.is_symlink():
        node_type = RepositoryNodeType.SYMLINK
    elif path.is_dir():
        node_type = RepositoryNodeType.DIRECTORY
    elif path.is_file():
        node_type = RepositoryNodeType.FILE
    else:
        node_type = RepositoryNodeType.OTHER

    relative_path = (
        "."
        if path == repository_root
        else path.relative_to(
            repository_root
        ).as_posix()
    )

    children: list[
        RepositoryNodeResponse
    ] = []

    if (
        node_type is RepositoryNodeType.DIRECTORY
        and current_depth < max_depth
        and counter[0] < max_items
    ):
        try:
            directory_entries = sorted(
                path.iterdir(),
                key=lambda item: (
                    not item.is_dir(),
                    item.name.casefold(),
                ),
            )
        except OSError as exc:
            logger.warning(
                "Could not read repository directory "
                "%s: %s",
                path,
                exc,
            )
            directory_entries = []

        for child in directory_entries:
            if (
                not include_hidden
                and _is_hidden_path(
                    child,
                    repository_root=repository_root,
                )
            ):
                continue

            if counter[0] >= max_items:
                truncated[0] = True
                break

            children.append(
                _scan_repository_node(
                    child,
                    repository_root=(
                        repository_root
                    ),
                    current_depth=(
                        current_depth + 1
                    ),
                    max_depth=max_depth,
                    include_hidden=(
                        include_hidden
                    ),
                    max_items=max_items,
                    counter=counter,
                    truncated=truncated,
                )
            )

    return RepositoryNodeResponse(
        name=path.name or path.anchor,
        path=relative_path,
        node_type=node_type,
        size_bytes=(
            stat_result.st_size
            if node_type
            is RepositoryNodeType.FILE
            else None
        ),
        modified_at_epoch=(
            stat_result.st_mtime
        ),
        children=tuple(children),
    )


def _scan_repository(
    *,
    repository_root: Path,
    max_depth: int,
    include_hidden: bool,
    max_items: int,
) -> RepositoryStructureResponse:
    resolved_root = repository_root.resolve()

    if not resolved_root.exists():
        raise CodeBuilderRepositoryError(
            f"Repository root does not exist: "
            f"{resolved_root}"
        )

    if not resolved_root.is_dir():
        raise CodeBuilderRepositoryError(
            f"Repository root is not a directory: "
            f"{resolved_root}"
        )

    counter = [0]
    truncated = [False]

    root_node = _scan_repository_node(
        resolved_root,
        repository_root=resolved_root,
        current_depth=0,
        max_depth=max_depth,
        include_hidden=include_hidden,
        max_items=max_items,
        counter=counter,
        truncated=truncated,
    )

    return RepositoryStructureResponse(
        repository_root=str(
            resolved_root
        ),
        generated_at_epoch=time.time(),
        max_depth=max_depth,
        item_count=counter[0],
        truncated=truncated[0],
        root=root_node,
    )


async def _scan_repository_async(
    *,
    repository_root: Path,
    max_depth: int,
    include_hidden: bool,
    max_items: int,
) -> RepositoryStructureResponse:
    return await asyncio.to_thread(
        _scan_repository,
        repository_root=repository_root,
        max_depth=max_depth,
        include_hidden=include_hidden,
        max_items=max_items,
    )
@router.post(
    "/tasks",
    response_model=TaskCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create Code Builder task",
    description=(
        "Creates a new Code Builder task. Tasks requiring approval "
        "remain pending until the approval endpoint is called."
    ),
    responses={
        status.HTTP_202_ACCEPTED: {
            "model": TaskCreateResponse,
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
        },
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "model": ErrorResponse,
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
        },
    },
)
async def create_code_builder_task(
    payload: TaskCreateRequest,
    background_tasks: BackgroundTasks,
    task_service: Annotated[
        TaskService,
        Depends(get_task_service),
    ],
    task_store: Annotated[
        TaskStore,
        Depends(get_task_store),
    ],
   idempotency_key: Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
    ),
] = None,
) -> TaskCreateResponse:
    normalized_idempotency_key = (
        _normalize_idempotency_key(
            idempotency_key
        )
    )

    task_id = uuid.uuid4().hex

    task_request = _task_request_from_api(
        payload,
        task_id=task_id,
    )

    now = time.time()

    initial_phase = CodeBuilderTaskPhase.QUEUED

    stored_task = StoredTask(
        request=task_request,
        api_request=payload,
        phase=initial_phase,
        created_at_epoch=now,
        updated_at_epoch=now,
        require_approval=payload.require_approval,
        auto_start_after_approval=(
            payload.auto_start_after_approval
        ),
        cancellation_token=(
            task_service.create_cancellation_token(
                task_id
            )
        ),
        metadata={
            "idempotency_key_used": (
                normalized_idempotency_key
                is not None
            ),
        },
    )

    try:
        created_task = task_store.create(
            stored_task,
            idempotency_key=(
                normalized_idempotency_key
            ),
        )
    except CodeBuilderTaskConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "task_conflict",
                "message": str(exc),
                "task_id": task_id,
            },
        ) from exc

    is_existing_idempotent_task = (
        created_task is not stored_task
    )

    if is_existing_idempotent_task:
        existing_payload = created_task.api_request.model_dump(mode="json")
        incoming_payload = payload.model_dump(mode="json")
        if existing_payload != incoming_payload:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "idempotency_key_conflict",
                    "message": (
                        "This Idempotency-Key is already bound to a different "
                        "Code Builder request."
                    ),
                    "task_id": created_task.request.task_id,
                },
            )

    if not is_existing_idempotent_task:
        _schedule_task_execution(
            background_tasks=background_tasks,
            task_service=task_service,
            task_store=task_store,
            stored_task=created_task,
        )

    return TaskCreateResponse(
        task=_task_detail_response(
            created_task
        ),
        accepted=True,
    )


@router.get(
    "/tasks",
    response_model=TaskListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Code Builder tasks",
    responses={
        status.HTTP_200_OK: {
            "model": TaskListResponse,
        },
    },
)
async def list_code_builder_tasks(
    task_store: Annotated[
        TaskStore,
        Depends(get_task_store),
    ],
    offset: Annotated[
        int,
        Query(
            ge=0,
            description=(
                "Number of tasks to skip."
            ),
        ),
    ] = 0,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_TASK_LIST_LIMIT,
            description=(
                "Maximum number of tasks to return."
            ),
        ),
    ] = DEFAULT_TASK_LIST_LIMIT,
    phase: Annotated[
        list[CodeBuilderTaskPhase] | None,
        Query(
            description=(
                "Optional task phases to include."
            ),
        ),
    ] = None,
) -> TaskListResponse:
    phases = set(phase) if phase else None

    tasks, total = task_store.list(
        offset=offset,
        limit=limit,
        phases=phases,
    )

    return TaskListResponse(
        items=tuple(
            _task_summary_response(task)
            for task in tasks
        ),
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/tasks/{task_id}",
    response_model=TaskDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Code Builder task",
    responses={
        status.HTTP_200_OK: {
            "model": TaskDetailResponse,
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
        },
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "model": ErrorResponse,
        },
    },
)
async def get_code_builder_task(
    task_id: str,
    task_store: Annotated[
        TaskStore,
        Depends(get_task_store),
    ],
) -> TaskDetailResponse:
    normalized_task_id = _validate_task_id(
        task_id
    )

    stored_task = _get_task_or_404(
        task_store,
        normalized_task_id,
    )

    return _task_detail_response(
        stored_task
    )


@router.get(
    "/tasks/{task_id}/events",
    response_model=tuple[TaskEventResponse, ...],
    status_code=status.HTTP_200_OK,
    summary="Get Code Builder task events",
    responses={
        status.HTTP_200_OK: {
            "description": (
                "Chronological task event history."
            ),
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
        },
    },
)
async def get_code_builder_task_events(
    task_id: str,
    task_store: Annotated[
        TaskStore,
        Depends(get_task_store),
    ],
    after_sequence: Annotated[
    int | None,
    Query(
        ge=0,
        description=(
            "Return only events whose sequence "
            "is greater than this value."
        ),
    ),
] = None,
) -> tuple[TaskEventResponse, ...]:
    normalized_task_id = _validate_task_id(
        task_id
    )

    stored_task = _get_task_or_404(
        task_store,
        normalized_task_id,
    )

    events: list[TaskEventResponse] = []

    for raw_event in stored_task.events:
        event = TaskEventResponse.model_validate(
            raw_event
        )

        if (
            after_sequence is not None
            and event.sequence is not None
            and event.sequence <= after_sequence
        ):
            continue

        events.append(event)

    return tuple(events)


def _validate_review_allows_approval(
    review_result: Any,
    *,
    task_id: str,
) -> None:
    serialized_review = _serialize_value(review_result)
    if not isinstance(serialized_review, Mapping):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ai_review_unavailable",
                "message": "Independent AI review must complete before approval.",
                "task_id": task_id,
            },
        )

    review_status = str(serialized_review.get("status") or "").strip().casefold()
    verdict = str(serialized_review.get("verdict") or "").strip().casefold()

    if review_status != "completed" or verdict not in {"pass", "warn", "block"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ai_review_unavailable",
                "message": "Independent AI review must complete successfully before approval.",
                "task_id": task_id,
            },
        )

    if verdict == "block":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ai_review_blocked",
                "message": "AI review blocked this prepared change. Revise the task before approval.",
                "task_id": task_id,
            },
        )


@router.post(
    "/tasks/{task_id}/approve",
    response_model=TaskApprovalResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Approve or reject Code Builder changes",
    responses={
        status.HTTP_202_ACCEPTED: {
            "model": TaskApprovalResponse,
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
        },
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "model": ErrorResponse,
        },
    },
)
async def approve_code_builder_task(
    task_id: str,
    payload: TaskApprovalRequest,
    background_tasks: BackgroundTasks,
    task_service: Annotated[
        TaskService,
        Depends(get_task_service),
    ],
    task_store: Annotated[
        TaskStore,
        Depends(get_task_store),
    ],
) -> TaskApprovalResponse:
    normalized_task_id = _validate_task_id(
        task_id
    )

    stored_task = _get_task_or_404(
        task_store,
        normalized_task_id,
    )

    execution_started = False

    with stored_task.execution_lock:
        if not stored_task.require_approval:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "approval_not_required",
                    "message": (
                        "This task does not require approval."
                    ),
                    "task_id": normalized_task_id,
                },
            )

        if not _phase_allows_approval(
            stored_task.phase
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "task_not_approvable",
                    "message": (
                        "Task cannot be approved while in "
                        f"phase {stored_task.phase.value!r}."
                    ),
                    "task_id": normalized_task_id,
                },
            )

        if (
            payload.decision
            is ApprovalDecision.REJECT
        ):
            stored_task.phase = (
                CodeBuilderTaskPhase.CANCELLED
            )
            stored_task.approval_comment = (
                payload.comment
            )
            stored_task.finished_at_epoch = (
                time.time()
            )
            stored_task.result = {
                "task_id": normalized_task_id,
                "status": (
                    TaskStatus.CANCELLED.value
                ),
                "success": False,
                "error_type": (
                    "TaskApprovalRejected"
                ),
                "error_message": (
                    payload.comment
                    or "Task approval was rejected."
                ),
            }
            stored_task.cancellation_token.cancel(
                payload.comment
                or "Task approval was rejected."
            )
            stored_task.touch()

            return TaskApprovalResponse(
                task=_task_detail_response(
                    stored_task
                ),
                approved=False,
                execution_started=False,
            )

        _validate_review_allows_approval(
            stored_task.review_result,
            task_id=normalized_task_id,
        )

        try:
            stored_task.request = _bind_prepared_patch_to_request(
                stored_task
            )
        except CodeBuilderApprovalError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "task_not_prepared",
                    "message": str(exc),
                    "task_id": normalized_task_id,
                },
            ) from exc

        stored_task.approved_at_epoch = (
            time.time()
        )
        stored_task.approval_comment = (
            payload.comment
        )
        stored_task.phase = (
            CodeBuilderTaskPhase.APPROVED
        )
        stored_task.touch()

        should_start = (
            payload.start_immediately
            and stored_task.auto_start_after_approval
        )

    if should_start:
        _schedule_task_execution(
            background_tasks=background_tasks,
            task_service=task_service,
            task_store=task_store,
            stored_task=stored_task,
        )
        execution_started = True

    return TaskApprovalResponse(
        task=_task_detail_response(
            stored_task
        ),
        approved=True,
        execution_started=execution_started,
    )


@router.post(
    "/tasks/{task_id}/start",
    response_model=TaskDetailResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start an approved Code Builder task",
    responses={
        status.HTTP_202_ACCEPTED: {
            "model": TaskDetailResponse,
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
        },
    },
)
async def start_code_builder_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    task_service: Annotated[
        TaskService,
        Depends(get_task_service),
    ],
    task_store: Annotated[
        TaskStore,
        Depends(get_task_store),
    ],
) -> TaskDetailResponse:
    normalized_task_id = _validate_task_id(
        task_id
    )

    stored_task = _get_task_or_404(
        task_store,
        normalized_task_id,
    )

    with stored_task.execution_lock:
        if (
            stored_task.require_approval
            and stored_task.approved_at_epoch is None
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "task_not_approved",
                    "message": (
                        "Task must be approved before "
                        "execution can start."
                    ),
                    "task_id": normalized_task_id,
                },
            )

        if stored_task.phase not in {
            CodeBuilderTaskPhase.QUEUED,
            CodeBuilderTaskPhase.APPROVED,
            CodeBuilderTaskPhase.AWAITING_APPROVAL,
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "task_not_startable",
                    "message": (
                        "Task cannot be started while in "
                        f"phase {stored_task.phase.value!r}."
                    ),
                    "task_id": normalized_task_id,
                },
            )

        stored_task.phase = (
            CodeBuilderTaskPhase.APPROVED
            if stored_task.require_approval
            else CodeBuilderTaskPhase.QUEUED
        )
        stored_task.touch()

    _schedule_task_execution(
        background_tasks=background_tasks,
        task_service=task_service,
        task_store=task_store,
        stored_task=stored_task,
    )

    return _task_detail_response(
        stored_task
    )


@router.post(
    "/tasks/{task_id}/cancel",
    response_model=TaskDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel Code Builder task",
    responses={
        status.HTTP_200_OK: {
            "model": TaskDetailResponse,
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
        },
    },
)
async def cancel_code_builder_task(
    task_id: str,
    payload: TaskCancelRequest,
    task_service: Annotated[
        TaskService,
        Depends(get_task_service),
    ],
    task_store: Annotated[
        TaskStore,
        Depends(get_task_store),
    ],
) -> TaskDetailResponse:
    normalized_task_id = _validate_task_id(
        task_id
    )

    stored_task = _get_task_or_404(
        task_store,
        normalized_task_id,
    )

    with stored_task.execution_lock:
        if not _phase_allows_cancellation(
            stored_task.phase
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "task_not_cancellable",
                    "message": (
                        "Task cannot be cancelled while in "
                        f"phase {stored_task.phase.value!r}."
                    ),
                    "task_id": normalized_task_id,
                },
            )

        cancellation_reason = (
            payload.reason
            or "Task cancelled by user."
        )

        stored_task.cancellation_token.cancel(
            cancellation_reason
        )

        task_service.cancel_task(
            normalized_task_id,
            reason=cancellation_reason,
        )

        if stored_task.phase in {
            CodeBuilderTaskPhase.QUEUED,
            CodeBuilderTaskPhase.AWAITING_APPROVAL,
            CodeBuilderTaskPhase.APPROVED,
        }:
            stored_task.phase = (
                CodeBuilderTaskPhase.CANCELLED
            )
            stored_task.finished_at_epoch = (
                time.time()
            )
            stored_task.result = {
                "task_id": normalized_task_id,
                "status": (
                    TaskStatus.CANCELLED.value
                ),
                "success": False,
                "error_type": (
                    "TaskCancellationError"
                ),
                "error_message": (
                    cancellation_reason
                ),
            }

        stored_task.touch()

    return _task_detail_response(
        stored_task
    )


@router.post(
    "/tasks/{task_id}/rollback",
    response_model=TaskRollbackResponse,
    status_code=status.HTTP_200_OK,
    summary="Manually rollback Code Builder task",
    responses={
        status.HTTP_200_OK: {
            "model": TaskRollbackResponse,
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponse,
        },
    },
)
async def rollback_code_builder_task(
    task_id: str,
    payload: TaskRollbackRequest,
    task_service: Annotated[
        TaskService,
        Depends(get_task_service),
    ],
    backup_service: Annotated[
        BackupService,
        Depends(get_backup_service),
    ],
    task_store: Annotated[
        TaskStore,
        Depends(get_task_store),
    ],
) -> TaskRollbackResponse:
    normalized_task_id = _validate_task_id(
        task_id
    )

    stored_task = _get_task_or_404(
        task_store,
        normalized_task_id,
    )

    try:
        await _manual_rollback(
            task_service=task_service,
            backup_service=backup_service,
            stored_task=stored_task,
            reason=payload.reason,
            force=payload.force,
        )
    except CodeBuilderTaskConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "rollback_conflict",
                "message": str(exc),
                "task_id": normalized_task_id,
            },
        ) from exc
    except CodeBuilderRollbackError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail={
                "error": "rollback_failed",
                "message": str(exc),
                "task_id": normalized_task_id,
            },
        ) from exc
    except CodeBuilderDependencyError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail={
                "error": "rollback_dependency_error",
                "message": str(exc),
                "task_id": normalized_task_id,
            },
        ) from exc
    except Exception as exc:
        logger.exception(
            "Manual rollback failed for task %s.",
            normalized_task_id,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail={
                "error": "rollback_failed",
                "message": str(exc),
                "task_id": normalized_task_id,
            },
        ) from exc

    return TaskRollbackResponse(
        task=_task_detail_response(
            stored_task
        ),
        rollback_started=True,
        rollback_completed=(
            stored_task.phase
            is CodeBuilderTaskPhase.ROLLED_BACK
        ),
    )


@router.delete(
    "/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete stored Code Builder task",
    responses={
        status.HTTP_204_NO_CONTENT: {
            "description": (
                "Task record deleted successfully."
            ),
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
        },
    },
)
async def delete_code_builder_task(
    task_id: str,
    task_service: Annotated[
        TaskService,
        Depends(get_task_service),
    ],
    task_store: Annotated[
        TaskStore,
        Depends(get_task_store),
    ],
) -> Response:
    normalized_task_id = _validate_task_id(
        task_id
    )

    stored_task = _get_task_or_404(
        task_store,
        normalized_task_id,
    )

    with stored_task.execution_lock:
        if stored_task.phase in {
            CodeBuilderTaskPhase.ANALYZING,
            CodeBuilderTaskPhase.PLANNING,
            CodeBuilderTaskPhase.VALIDATING,
            CodeBuilderTaskPhase.APPLYING,
            CodeBuilderTaskPhase.VERIFYING,
            CodeBuilderTaskPhase.EXECUTING,
            CodeBuilderTaskPhase.ROLLING_BACK,
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "active_task_cannot_be_deleted",
                    "message": (
                        "An active task must be cancelled "
                        "before it can be deleted."
                    ),
                    "task_id": normalized_task_id,
                },
            )

        task_service.cancel_task(
            normalized_task_id,
            reason=(
                "Task record deleted by user."
            ),
        )

        removed = task_store.remove(
            normalized_task_id
        )

    if not removed:
        _raise_task_not_found(
            normalized_task_id
        )

    return Response(
        status_code=status.HTTP_204_NO_CONTENT
    )


@router.get(
    "/repository/structure",
    response_model=RepositoryStructureResponse,
    status_code=status.HTTP_200_OK,
    summary="Scan repository structure",
    responses={
        status.HTTP_200_OK: {
            "model": RepositoryStructureResponse,
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponse,
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
        },
    },
)
async def get_repository_structure(
    task_service: Annotated[
        TaskService,
        Depends(get_task_service),
    ],
    repository_service: Annotated[
        RepositoryService,
        Depends(get_repository_service),
    ],
    max_depth: Annotated[
        int,
        Query(
            ge=0,
            le=MAX_REPOSITORY_DEPTH,
            description=(
                "Maximum recursive directory depth."
            ),
        ),
    ] = DEFAULT_REPOSITORY_DEPTH,
    include_hidden: Annotated[
        bool,
        Query(
            description=(
                "Include ignored and hidden repository "
                "directories."
            ),
        ),
    ] = False,
    max_items: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_REPOSITORY_ITEMS,
            description=(
                "Maximum number of repository nodes."
            ),
        ),
    ] = DEFAULT_MAX_REPOSITORY_ITEMS,
) -> RepositoryStructureResponse:
    del repository_service

    try:
        repository_root = (
            _repository_root_from_task_service(
                task_service
            )
        )

        return await _scan_repository_async(
            repository_root=repository_root,
            max_depth=max_depth,
            include_hidden=include_hidden,
            max_items=max_items,
        )
    except CodeBuilderDependencyError:
        raise
    except CodeBuilderRepositoryError:
        raise
    except Exception as exc:
        logger.exception(
            "Repository structure scan failed."
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail={
                "error": "repository_scan_failed",
                "message": str(exc),
            },
        ) from exc


@router.get(
    "/repository/status",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Get repository status",
    responses={
        status.HTTP_200_OK: {
            "description": (
                "Repository status returned successfully."
            ),
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
        },
    },
)
async def get_repository_status(
    task_service: Annotated[
        TaskService,
        Depends(get_task_service),
    ],
    repository_service: Annotated[
        RepositoryService,
        Depends(get_repository_service),
    ],
) -> dict[str, Any]:
    repository_root = (
        _repository_root_from_task_service(
            task_service
        )
    )

    try:
        result = await asyncio.to_thread(
            _call_service_method,
            repository_service,
            (
                "get_status",
                "status",
                "inspect_status",
                "repository_status",
                "get_repository_status",
            ),
            keyword_variants=(
                {
                    "repository_root": (
                        repository_root
                    ),
                    "root": repository_root,
                },
                {
                    "path": repository_root,
                },
                {},
            ),
            positional_variants=(
                (repository_root,),
                (),
            ),
            operation_name="repository status",
        )
    except CodeBuilderDependencyError:
        return {
            "repository_root": str(
                repository_root
            ),
            "exists": repository_root.exists(),
            "is_directory": (
                repository_root.is_dir()
            ),
            "service_status_available": False,
            "timestamp_epoch": time.time(),
        }

    serialized = _serialize_value(
        result
    )

    if isinstance(serialized, Mapping):
        response = dict(serialized)
    else:
        response = {
            "value": serialized,
        }

    response.setdefault(
        "repository_root",
        str(repository_root),
    )
    response.setdefault(
        "timestamp_epoch",
        time.time(),
    )

    return response


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Code Builder health check",
    responses={
        status.HTTP_200_OK: {
            "model": HealthResponse,
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
        },
    },
)
async def code_builder_health(
    task_service: Annotated[
        TaskService,
        Depends(get_task_service),
    ],
    task_store: Annotated[
        TaskStore,
        Depends(get_task_store),
    ],
) -> HealthResponse:
    repository_root = (
        _repository_root_from_task_service(
            task_service
        )
    )

    healthy = (
        repository_root.exists()
        and repository_root.is_dir()
    )

    if not healthy:
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail={
                "error": "repository_unavailable",
                "message": (
                    "Configured repository root is unavailable."
                ),
                "repository_root": str(
                    repository_root
                ),
            },
        )

    return HealthResponse(
        status="healthy",
        active_tasks=len(
            task_service.active_task_ids()
        ),
        stored_tasks=task_store.count(),
        repository_root=str(
            repository_root
        ),
        timestamp_epoch=time.time(),
    )


def create_code_builder_router(
    *,
    task_service: TaskService,
    repository_service: RepositoryService,
    backup_service: BackupService,
    task_store: TaskStore | None = None,
) -> APIRouter:
    configure_code_builder_router(
        task_service=task_service,
        repository_service=repository_service,
        backup_service=backup_service,
        task_store=task_store,
    )

    return router


def build_code_builder_router(
    *,
    repository_root: str | Path,
    repository_service: RepositoryService,
    planning_service: PlanningService,
    backup_service: BackupService,
    patch_service: PatchService,
    build_service: BuildService,
    ollama_service: OllamaService,
    task_store: TaskStore | None = None,
    configuration: (
        TaskServiceConfiguration | None
    ) = None,
) -> APIRouter:
    effective_configuration = (
        configuration
        or TaskServiceConfiguration(
            repository_root=Path(
                repository_root
            ),
        )
    )

    task_service = create_task_service(
        repository_root=(
            effective_configuration.repository_root
        ),
        repository_service=repository_service,
        planning_service=planning_service,
        backup_service=backup_service,
        patch_service=patch_service,
        build_service=build_service,
        ollama_service=ollama_service,
        analysis_timeout_seconds=(
            effective_configuration
            .analysis_timeout_seconds
        ),
        planning_timeout_seconds=(
            effective_configuration
            .planning_timeout_seconds
        ),
        patch_timeout_seconds=(
            effective_configuration
            .patch_timeout_seconds
        ),
        build_timeout_seconds=(
            effective_configuration
            .build_timeout_seconds
        ),
        rollback_timeout_seconds=(
            effective_configuration
            .rollback_timeout_seconds
        ),
        max_event_count=(
            effective_configuration
            .max_event_count
        ),
        use_default_build_sequence=(
            effective_configuration
            .use_default_build_sequence
        ),
        default_backend_directory=(
            effective_configuration
            .default_backend_directory
        ),
        default_frontend_directory=(
            effective_configuration
            .default_frontend_directory
        ),
        include_ruff=(
            effective_configuration.include_ruff
        ),
        include_mypy=(
            effective_configuration.include_mypy
        ),
        include_frontend_tests=(
            effective_configuration
            .include_frontend_tests
        ),
        include_frontend_build=(
            effective_configuration
            .include_frontend_build
        ),
    )

    return create_code_builder_router(
        task_service=task_service,
        repository_service=repository_service,
        backup_service=backup_service,
        task_store=task_store,
    )


__all__ = [
    "ROUTER_PREFIX",
    "ROUTER_TAG",
    "DEFAULT_TASK_LIST_LIMIT",
    "MAX_TASK_LIST_LIMIT",
    "DEFAULT_REPOSITORY_DEPTH",
    "MAX_REPOSITORY_DEPTH",
    "DEFAULT_MAX_REPOSITORY_ITEMS",
    "MAX_REPOSITORY_ITEMS",
    "DEFAULT_MAX_STORED_EVENTS",
    "DEFAULT_TASK_RETENTION_SECONDS",
    "DEFAULT_APPROVAL_TIMEOUT_SECONDS",
    "CodeBuilderRouterError",
    "CodeBuilderDependencyError",
    "CodeBuilderTaskNotFoundError",
    "CodeBuilderTaskConflictError",
    "CodeBuilderApprovalError",
    "CodeBuilderRollbackError",
    "CodeBuilderRepositoryError",
    "CodeBuilderTaskPhase",
    "ApprovalDecision",
    "RepositoryNodeType",
    "TaskCreateRequest",
    "TaskApprovalRequest",
    "TaskRollbackRequest",
    "TaskCancelRequest",
    "TaskEventResponse",
    "TaskSummaryResponse",
    "TaskDetailResponse",
    "TaskListResponse",
    "TaskCreateResponse",
    "TaskApprovalResponse",
    "TaskRollbackResponse",
    "RepositoryNodeResponse",
    "RepositoryStructureResponse",
    "ErrorResponse",
    "HealthResponse",
    "StoredTask",
    "TaskStore",
    "CodeBuilderRouterDependencies",
    "configure_code_builder_router",
    "get_router_dependencies",
    "get_task_service",
    "get_repository_service",
    "get_backup_service",
    "get_task_store",
    "router",
    "create_code_builder_router",
    "build_code_builder_router",
]