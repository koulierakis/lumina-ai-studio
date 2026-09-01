"""Pydantic models for the LUMINA Code Builder.

This module contains the shared API contracts and internal data structures
used by the Code Builder backend.

The models are designed for Pydantic v2 and cover:

- Code Builder task lifecycle
- Repository and codebase analysis
- File discovery and metadata
- Proposed file changes
- Unified diffs
- Approval and execution
- Backups and rollback
- Build and validation results
- Ollama requests and responses
- Task history and event streaming
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


def utc_now() -> datetime:
    """Return the current UTC datetime."""

    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    """Base model with strict validation and forbidden extra fields."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
        use_enum_values=False,
        populate_by_name=True,
    )


class TaskStatus(str, Enum):
    """Lifecycle status of a Code Builder task."""

    CREATED = "created"
    ANALYZING = "analyzing"
    INDEXING = "indexing"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    BACKING_UP = "backing_up"
    APPLYING = "applying"
    VALIDATING = "validating"
    BUILDING = "building"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    """Execution priority of a Code Builder task."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class TaskType(str, Enum):
    """Supported Code Builder task types."""

    ANALYZE = "analyze"
    MODIFY = "modify"
    CREATE = "create"
    REFACTOR = "refactor"
    FIX = "fix"
    TEST = "test"
    DOCUMENT = "document"
    REVIEW = "review"
    BUILD = "build"
    ROLLBACK = "rollback"


class ChangeType(str, Enum):
    """Type of a proposed repository change."""

    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"
    RENAME = "rename"


class ApprovalStatus(str, Enum):
    """Approval status for a proposed change plan."""

    PENDING = "pending"
    APPROVED = "approved"
    PARTIALLY_APPROVED = "partially_approved"
    REJECTED = "rejected"


class FileType(str, Enum):
    """Classification of a repository file."""

    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    JSX = "jsx"
    TSX = "tsx"
    JSON = "json"
    YAML = "yaml"
    TOML = "toml"
    MARKDOWN = "markdown"
    HTML = "html"
    CSS = "css"
    SCSS = "scss"
    SHELL = "shell"
    POWERSHELL = "powershell"
    SQL = "sql"
    TEXT = "text"
    BINARY = "binary"
    UNKNOWN = "unknown"


class FileRole(str, Enum):
    """Architectural role of a repository file."""

    SOURCE = "source"
    TEST = "test"
    CONFIGURATION = "configuration"
    DOCUMENTATION = "documentation"
    ASSET = "asset"
    GENERATED = "generated"
    DEPENDENCY = "dependency"
    BUILD_ARTIFACT = "build_artifact"
    SECRET = "secret"
    UNKNOWN = "unknown"


class RiskLevel(str, Enum):
    """Risk level assigned to a proposed operation."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ValidationStatus(str, Enum):
    """Status of a validation or build check."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class ValidationType(str, Enum):
    """Type of validation performed after applying changes."""

    PATH_SECURITY = "path_security"
    PYTHON_SYNTAX = "python_syntax"
    PYTHON_COMPILE = "python_compile"
    BACKEND_TESTS = "backend_tests"
    FRONTEND_TESTS = "frontend_tests"
    FRONTEND_BUILD = "frontend_build"
    TYPE_CHECK = "type_check"
    LINT = "lint"
    IMPORT_CHECK = "import_check"
    CUSTOM = "custom"


class BackupStatus(str, Enum):
    """Status of a repository backup."""

    CREATING = "creating"
    COMPLETED = "completed"
    FAILED = "failed"
    RESTORING = "restoring"
    RESTORED = "restored"
    DELETED = "deleted"


class RollbackStatus(str, Enum):
    """Status of a rollback operation."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EventType(str, Enum):
    """Type of event emitted by a Code Builder task."""

    TASK_CREATED = "task_created"
    STATUS_CHANGED = "status_changed"
    ANALYSIS_STARTED = "analysis_started"
    ANALYSIS_COMPLETED = "analysis_completed"
    PLAN_CREATED = "plan_created"
    APPROVAL_REQUIRED = "approval_required"
    APPROVED = "approved"
    REJECTED = "rejected"
    BACKUP_CREATED = "backup_created"
    FILE_CHANGED = "file_changed"
    VALIDATION_STARTED = "validation_started"
    VALIDATION_COMPLETED = "validation_completed"
    BUILD_STARTED = "build_started"
    BUILD_COMPLETED = "build_completed"
    ROLLBACK_STARTED = "rollback_started"
    ROLLBACK_COMPLETED = "rollback_completed"
    ERROR = "error"
    LOG = "log"
    COMPLETED = "completed"


class LogLevel(str, Enum):
    """Severity of a Code Builder log entry."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class OllamaConnectionStatus(str, Enum):
    """Connection status of the local Ollama service."""

    UNKNOWN = "unknown"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class PathReference(StrictModel):
    """Normalized reference to a repository path."""

    relative_path: str = Field(
        min_length=1,
        description="Repository-relative path using forward slashes.",
    )

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/").strip()

        if not normalized:
            raise ValueError("Path cannot be empty.")

        candidate = Path(normalized)

        if candidate.is_absolute():
            raise ValueError("Absolute paths are not permitted.")

        parts = candidate.parts

        if any(part == ".." for part in parts):
            raise ValueError("Path traversal is not permitted.")

        return Path(*parts).as_posix()


class SourceLocation(StrictModel):
    """Location of an item inside a source file."""

    relative_path: str = Field(min_length=1)
    start_line: int = Field(default=1, ge=1)
    end_line: int = Field(default=1, ge=1)
    start_column: int | None = Field(default=None, ge=1)
    end_column: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_line_range(self) -> "SourceLocation":
        if self.end_line < self.start_line:
            raise ValueError("end_line cannot be smaller than start_line.")

        if (
            self.start_line == self.end_line
            and self.start_column is not None
            and self.end_column is not None
            and self.end_column < self.start_column
        ):
            raise ValueError(
                "end_column cannot be smaller than start_column."
            )

        return self


class FileMetadata(StrictModel):
    """Metadata collected for one repository file."""

    relative_path: str = Field(min_length=1)
    file_name: str = Field(min_length=1)
    extension: str = ""
    file_type: FileType = FileType.UNKNOWN
    role: FileRole = FileRole.UNKNOWN
    size_bytes: int = Field(default=0, ge=0)
    line_count: int | None = Field(default=None, ge=0)
    sha256: str | None = None
    encoding: str | None = None
    is_binary: bool = False
    is_symlink: bool = False
    is_generated: bool = False
    is_protected: bool = False
    protection_reason: str | None = None
    modified_at: datetime | None = None
    language: str | None = None

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.lower().strip()

        if len(normalized) != 64:
            raise ValueError("SHA-256 digest must contain 64 characters.")

        if any(character not in "0123456789abcdef" for character in normalized):
            raise ValueError("SHA-256 digest must be hexadecimal.")

        return normalized


class CodeSymbol(StrictModel):
    """Code symbol discovered during codebase analysis."""

    name: str = Field(min_length=1)
    qualified_name: str | None = None
    symbol_type: Literal[
        "module",
        "class",
        "function",
        "method",
        "variable",
        "constant",
        "interface",
        "type",
        "enum",
        "route",
        "component",
        "hook",
        "unknown",
    ] = "unknown"
    location: SourceLocation
    signature: str | None = None
    docstring: str | None = None
    decorators: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    exported: bool = False


class ImportReference(StrictModel):
    """Import or dependency reference discovered in a source file."""

    source_path: str = Field(min_length=1)
    module: str = Field(min_length=1)
    imported_names: list[str] = Field(default_factory=list)
    alias: str | None = None
    line_number: int = Field(default=1, ge=1)
    is_relative: bool = False
    resolved_path: str | None = None


class RepositoryStatistics(StrictModel):
    """Aggregated repository statistics."""

    total_files: int = Field(default=0, ge=0)
    indexed_files: int = Field(default=0, ge=0)
    skipped_files: int = Field(default=0, ge=0)
    protected_files: int = Field(default=0, ge=0)
    binary_files: int = Field(default=0, ge=0)
    total_size_bytes: int = Field(default=0, ge=0)
    total_lines: int = Field(default=0, ge=0)
    files_by_type: dict[str, int] = Field(default_factory=dict)
    files_by_role: dict[str, int] = Field(default_factory=dict)
    files_by_extension: dict[str, int] = Field(default_factory=dict)


class RepositoryConfiguration(StrictModel):
    """Configuration used when scanning a repository."""

    repository_root: str = Field(min_length=1)
    include_hidden_files: bool = False
    follow_symlinks: bool = False
    calculate_hashes: bool = True
    detect_encoding: bool = True
    extract_symbols: bool = True
    extract_imports: bool = True
    maximum_file_size_bytes: int = Field(
        default=2_000_000,
        ge=1,
        le=100_000_000,
    )
    excluded_directories: list[str] = Field(
        default_factory=lambda: [
            ".git",
            ".hg",
            ".svn",
            ".lumina",
            "node_modules",
            "venv",
            ".venv",
            "env",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "dist",
            "build",
            "coverage",
        ]
    )
    excluded_file_patterns: list[str] = Field(
        default_factory=lambda: [
            "*.pyc",
            "*.pyo",
            "*.pyd",
            "*.dll",
            "*.exe",
            "*.zip",
            "*.rar",
            "*.7z",
            "*.tar",
            "*.gz",
            "*.log",
            "*.lock",
            ".env",
            ".env.*",
        ]
    )


class CodebaseAnalysisRequest(StrictModel):
    """Request to analyze and index the LUMINA repository."""

    configuration: RepositoryConfiguration
    force_reindex: bool = False


class CodebaseAnalysis(StrictModel):
    """Complete repository analysis result."""

    analysis_id: UUID = Field(default_factory=uuid4)
    repository_root: str = Field(min_length=1)
    repository_name: str = Field(min_length=1)
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    statistics: RepositoryStatistics = Field(
        default_factory=RepositoryStatistics
    )
    files: list[FileMetadata] = Field(default_factory=list)
    symbols: list[CodeSymbol] = Field(default_factory=list)
    imports: list[ImportReference] = Field(default_factory=list)
    backend_detected: bool = False
    frontend_detected: bool = False
    backend_framework: str | None = None
    frontend_framework: str | None = None
    package_managers: list[str] = Field(default_factory=list)
    test_frameworks: list[str] = Field(default_factory=list)
    build_commands: list[str] = Field(default_factory=list)
    test_commands: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class FileContent(StrictModel):
    """Text content and metadata of a repository file."""

    relative_path: str = Field(min_length=1)
    content: str
    encoding: str = "utf-8"
    sha256: str | None = None
    line_count: int = Field(default=0, ge=0)
    size_bytes: int = Field(default=0, ge=0)
    loaded_at: datetime = Field(default_factory=utc_now)


class ContextFile(StrictModel):
    """File included in the AI context for a Code Builder task."""

    relative_path: str = Field(min_length=1)
    content: str
    reason: str = Field(min_length=1)
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    token_estimate: int = Field(default=0, ge=0)
    truncated: bool = False
    original_size_bytes: int = Field(default=0, ge=0)


class CodeContext(StrictModel):
    """Repository context selected for an AI request."""

    task_id: UUID
    files: list[ContextFile] = Field(default_factory=list)
    total_token_estimate: int = Field(default=0, ge=0)
    maximum_tokens: int = Field(default=32_000, ge=1)
    repository_summary: str | None = None
    architectural_notes: list[str] = Field(default_factory=list)
    omitted_files: list[str] = Field(default_factory=list)


class DiffLine(StrictModel):
    """Single parsed line from a unified diff."""

    line_type: Literal["context", "addition", "deletion", "header"]
    content: str
    old_line_number: int | None = Field(default=None, ge=1)
    new_line_number: int | None = Field(default=None, ge=1)


class DiffHunk(StrictModel):
    """Parsed hunk from a unified diff."""

    header: str
    old_start: int = Field(ge=0)
    old_count: int = Field(ge=0)
    new_start: int = Field(ge=0)
    new_count: int = Field(ge=0)
    lines: list[DiffLine] = Field(default_factory=list)


class UnifiedDiff(StrictModel):
    """Unified diff generated for a proposed file change."""

    relative_path: str = Field(min_length=1)
    old_path: str = Field(min_length=1)
    new_path: str = Field(min_length=1)
    old_sha256: str
    new_sha256: str
    unified_diff: str
    changed: bool = False
    additions: int = Field(default=0, ge=0)
    deletions: int = Field(default=0, ge=0)
    hunks: list[DiffHunk] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_diff_counts(self) -> "UnifiedDiff":
        if not self.changed and (self.additions > 0 or self.deletions > 0):
            raise ValueError(
                "A diff marked as unchanged cannot contain additions "
                "or deletions."
            )

        return self


class ProposedFileChange(StrictModel):
    """One file change proposed by the Code Builder.

    File contents are byte-significant text.  Unlike normal labels and paths,
    ``old_content`` and ``new_content`` must never be globally stripped because
    trailing newlines and indentation are part of the proposed patch.
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=False,
        use_enum_values=False,
        populate_by_name=True,
    )

    change_id: UUID = Field(default_factory=uuid4)
    relative_path: str = Field(min_length=1)
    change_type: ChangeType
    previous_path: str | None = None
    old_content: str | None = None
    new_content: str | None = None
    old_sha256: str | None = None
    new_sha256: str | None = None
    diff: UnifiedDiff | None = None
    summary: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    risk_level: RiskLevel = RiskLevel.LOW
    dependencies: list[str] = Field(default_factory=list)
    approved: bool = False
    protected: bool = False
    protection_reason: str | None = None

    @field_validator("relative_path", "previous_path")
    @classmethod
    def normalize_change_paths(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.replace("\\", "/").strip()
        if not normalized:
            raise ValueError("Change path cannot be empty.")
        candidate = Path(normalized)
        if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
            raise ValueError("Change path must stay inside the repository.")
        return Path(*candidate.parts).as_posix()

    @field_validator("summary", "reason")
    @classmethod
    def normalize_required_labels(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Proposal summary and reason cannot be empty.")
        return normalized

    @field_validator("protection_reason")
    @classmethod
    def normalize_optional_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("dependencies")
    @classmethod
    def normalize_dependencies(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @model_validator(mode="after")
    def validate_change_payload(self) -> "ProposedFileChange":
        if self.change_type == ChangeType.CREATE:
            if self.old_content not in (None, ""):
                raise ValueError(
                    "CREATE changes cannot contain existing old content."
                )

            if self.new_content is None:
                raise ValueError(
                    "CREATE changes must include new_content."
                )

        elif self.change_type == ChangeType.MODIFY:
            if self.old_content is None:
                raise ValueError(
                    "MODIFY changes must include old_content."
                )

            if self.new_content is None:
                raise ValueError(
                    "MODIFY changes must include new_content."
                )

        elif self.change_type == ChangeType.DELETE:
            if self.old_content is None:
                raise ValueError(
                    "DELETE changes must include old_content."
                )

            if self.new_content not in (None, ""):
                raise ValueError(
                    "DELETE changes cannot contain new content."
                )

        elif self.change_type == ChangeType.RENAME:
            if not self.previous_path:
                raise ValueError(
                    "RENAME changes must include previous_path."
                )

            if self.new_content is None:
                raise ValueError(
                    "RENAME changes must include new_content."
                )

        if self.protected and self.approved:
            raise ValueError(
                "A protected file change cannot be approved."
            )

        return self


class ChangePlan(StrictModel):
    """Complete plan of changes proposed for a task."""

    plan_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1)
    reasoning_summary: str | None = None
    changes: list[ProposedFileChange] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = True
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    estimated_files_changed: int = Field(default=0, ge=0)
    estimated_additions: int = Field(default=0, ge=0)
    estimated_deletions: int = Field(default=0, ge=0)
    validation_commands: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    approved_at: datetime | None = None
    rejected_at: datetime | None = None

    @model_validator(mode="after")
    def synchronize_estimates(self) -> "ChangePlan":
        actual_file_count = len(self.changes)

        if self.estimated_files_changed == 0 and actual_file_count > 0:
            self.estimated_files_changed = actual_file_count

        return self


class ChangeApprovalRequest(StrictModel):
    """Request to approve all or selected proposed changes."""

    approved_change_ids: list[UUID] = Field(default_factory=list)
    approve_all: bool = False
    confirmation_text: str = Field(min_length=1)
    user_note: str | None = None

    @model_validator(mode="after")
    def validate_approval_selection(self) -> "ChangeApprovalRequest":
        if not self.approve_all and not self.approved_change_ids:
            raise ValueError(
                "Select at least one change or set approve_all to true."
            )

        return self


class ChangeRejectionRequest(StrictModel):
    """Request to reject a proposed change plan."""

    reason: str = Field(min_length=1)
    rejected_change_ids: list[UUID] = Field(default_factory=list)
    reject_all: bool = True


class BackupFileRecordModel(StrictModel):
    """Description of one file stored in a backup."""

    relative_path: str = Field(min_length=1)
    existed: bool
    is_file: bool
    size_bytes: int = Field(default=0, ge=0)
    sha256: str | None = None
    backup_relative_path: str | None = None


class BackupManifestModel(StrictModel):
    """Pydantic representation of a Code Builder backup manifest."""

    schema_version: int = Field(default=1, ge=1)
    backup_id: str = Field(min_length=1)
    repository_root: str = Field(min_length=1)
    created_at: datetime
    reason: str = Field(min_length=1)
    status: BackupStatus = BackupStatus.COMPLETED
    files: list[BackupFileRecordModel] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    rollback_count: int = Field(default=0, ge=0)
    last_rollback_at: datetime | None = None
    last_rollback_safety_backup_id: str | None = None


class BackupCreateRequest(StrictModel):
    """Request to create a backup before applying changes."""

    relative_paths: list[str] = Field(min_length=1)
    reason: str = Field(
        default="Before Code Builder modification",
        min_length=1,
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("relative_paths")
    @classmethod
    def validate_unique_paths(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()

        for value in values:
            path = value.replace("\\", "/").strip()

            if not path:
                raise ValueError("Backup paths cannot be empty.")

            if path not in seen:
                seen.add(path)
                normalized.append(path)

        return normalized


class BackupResultModel(StrictModel):
    """Result of a completed backup operation."""

    backup_id: str = Field(min_length=1)
    backup_directory: str = Field(min_length=1)
    manifest_path: str = Field(min_length=1)
    created_at: datetime
    file_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    reason: str = Field(min_length=1)
    status: BackupStatus = BackupStatus.COMPLETED


class BackupSummary(StrictModel):
    """Summary of an available repository backup."""

    backup_id: str = Field(min_length=1)
    created_at: datetime
    reason: str = Field(min_length=1)
    status: BackupStatus
    file_count: int = Field(default=0, ge=0)
    total_bytes: int = Field(default=0, ge=0)
    rollback_count: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RollbackRequest(StrictModel):
    """Request to restore repository files from a backup."""

    backup_id: str = Field(min_length=1)
    create_safety_backup: bool = True
    confirmation_text: str = Field(min_length=1)


class RollbackResultModel(StrictModel):
    """Result of a rollback operation."""

    backup_id: str = Field(min_length=1)
    restored_files: list[str] = Field(default_factory=list)
    removed_files: list[str] = Field(default_factory=list)
    safety_backup_id: str | None = None
    completed_at: datetime
    status: RollbackStatus = RollbackStatus.COMPLETED


class ValidationCommand(StrictModel):
    """Command that may be executed as part of validation."""

    validation_type: ValidationType
    command: list[str] = Field(min_length=1)
    working_directory: str = "."
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    required: bool = True
    environment: dict[str, str] = Field(default_factory=dict)


class ValidationResult(StrictModel):
    """Result of a single validation command."""

    validation_id: UUID = Field(default_factory=uuid4)
    validation_type: ValidationType
    status: ValidationStatus
    command: list[str] = Field(default_factory=list)
    working_directory: str = "."
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    required: bool = True
    error_message: str | None = None


class BuildResult(StrictModel):
    """Aggregated result of all validation and build operations."""

    build_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    status: ValidationStatus
    validations: list[ValidationResult] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    successful: bool = False
    rollback_required: bool = False
    failure_reason: str | None = None


class ApplyChangesRequest(StrictModel):
    """Request to apply an approved change plan."""

    plan_id: UUID
    approved_change_ids: list[UUID] = Field(default_factory=list)
    create_backup: bool = True
    run_validations: bool = True
    automatic_rollback: bool = True
    confirmation_text: str = Field(min_length=1)


class AppliedFileChange(StrictModel):
    """Result of applying one file change."""

    change_id: UUID
    relative_path: str = Field(min_length=1)
    change_type: ChangeType
    successful: bool
    previous_sha256: str | None = None
    current_sha256: str | None = None
    error_message: str | None = None
    applied_at: datetime = Field(default_factory=utc_now)


class ApplyChangesResult(StrictModel):
    """Result returned after applying an approved change plan."""

    task_id: UUID
    plan_id: UUID
    backup_id: str | None = None
    applied_changes: list[AppliedFileChange] = Field(default_factory=list)
    build_result: BuildResult | None = None
    successful: bool = False
    rolled_back: bool = False
    rollback_result: RollbackResultModel | None = None
    completed_at: datetime = Field(default_factory=utc_now)
    error_message: str | None = None


class OllamaModelInfo(StrictModel):
    """Information about one model installed in Ollama."""

    name: str = Field(min_length=1)
    model: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    digest: str | None = None
    modified_at: datetime | None = None
    parameter_size: str | None = None
    quantization_level: str | None = None
    family: str | None = None


class OllamaStatus(StrictModel):
    """Current availability and configuration of Ollama."""

    status: OllamaConnectionStatus
    base_url: str
    version: str | None = None
    models: list[OllamaModelInfo] = Field(default_factory=list)
    selected_model: str | None = None
    checked_at: datetime = Field(default_factory=utc_now)
    error_message: str | None = None


class OllamaGenerationOptions(StrictModel):
    """Generation options passed to an Ollama model."""

    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    top_k: int = Field(default=40, ge=1)
    seed: int | None = None
    num_ctx: int = Field(default=16_384, ge=1)
    num_predict: int = Field(default=2_048, ge=1)
    repeat_penalty: float = Field(default=1.1, ge=0.0)
    stop: list[str] = Field(default_factory=list)


class OllamaGenerationRequest(StrictModel):
    """Internal request sent to Ollama."""

    model: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    user_prompt: str = Field(min_length=1)
    context: CodeContext | None = None
    options: OllamaGenerationOptions = Field(
        default_factory=OllamaGenerationOptions
    )
    stream: bool = False
    format: Literal["json", "text"] = "json"


class OllamaGenerationResponse(StrictModel):
    """Normalized response returned by Ollama."""

    model: str = Field(min_length=1)
    response: str
    done: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    total_duration_nanoseconds: int | None = Field(default=None, ge=0)
    load_duration_nanoseconds: int | None = Field(default=None, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    raw_response: dict[str, Any] = Field(default_factory=dict)


class CodeBuilderTaskRequest(StrictModel):
    """User request for a new Code Builder task."""

    instruction: str = Field(min_length=3, max_length=50_000)
    task_type: TaskType = TaskType.MODIFY
    priority: TaskPriority = TaskPriority.NORMAL
    model: str | None = None
    include_paths: list[str] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)
    maximum_context_tokens: int = Field(
        default=32_000,
        ge=1_000,
        le=262_144,
    )
    allow_file_creation: bool = True
    allow_file_deletion: bool = False
    run_validations: bool = True
    automatic_rollback: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskError(StrictModel):
    """Structured error attached to a Code Builder task."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)
    recoverable: bool = False
    occurred_at: datetime = Field(default_factory=utc_now)


class TaskProgress(StrictModel):
    """Progress information for a running Code Builder task."""

    percentage: float = Field(default=0.0, ge=0.0, le=100.0)
    current_step: str = ""
    completed_steps: int = Field(default=0, ge=0)
    total_steps: int = Field(default=0, ge=0)
    estimated_seconds_remaining: float | None = Field(default=None, ge=0)
    updated_at: datetime = Field(default_factory=utc_now)


class CodeBuilderTask(StrictModel):
    """Persistent state of a Code Builder task."""

    task_id: UUID = Field(default_factory=uuid4)
    instruction: str = Field(min_length=3)
    task_type: TaskType
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.CREATED
    repository_root: str = Field(min_length=1)
    selected_model: str | None = None
    progress: TaskProgress = Field(default_factory=TaskProgress)
    analysis_id: UUID | None = None
    plan_id: UUID | None = None
    backup_id: str | None = None
    build_id: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    errors: list[TaskError] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskSummary(StrictModel):
    """Compact task representation used by history lists."""

    task_id: UUID
    instruction: str
    task_type: TaskType
    priority: TaskPriority
    status: TaskStatus
    progress_percentage: float = Field(default=0.0, ge=0.0, le=100.0)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    error_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)


class TaskEvent(StrictModel):
    """Event emitted during task execution."""

    event_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    event_type: EventType
    level: LogLevel = LogLevel.INFO
    message: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class TaskLogEntry(StrictModel):
    """Persistent log entry associated with a task."""

    log_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    level: LogLevel
    source: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class TaskHistoryEntry(StrictModel):
    """Complete historical record of a Code Builder task."""

    task: CodeBuilderTask
    plan: ChangePlan | None = None
    backup: BackupSummary | None = None
    build_result: BuildResult | None = None
    rollback_result: RollbackResultModel | None = None
    events: list[TaskEvent] = Field(default_factory=list)
    logs: list[TaskLogEntry] = Field(default_factory=list)


class TaskListResponse(StrictModel):
    """Paginated list of Code Builder tasks."""

    items: list[TaskSummary] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)
    pages: int = Field(default=0, ge=0)


class RepositoryTreeNode(StrictModel):
    """Node displayed in the repository file explorer."""

    name: str = Field(min_length=1)
    relative_path: str
    node_type: Literal["file", "directory"]
    children: list["RepositoryTreeNode"] = Field(default_factory=list)
    metadata: FileMetadata | None = None
    expanded: bool = False


class RepositoryTreeResponse(StrictModel):
    """Repository tree returned to the frontend."""

    repository_root: str = Field(min_length=1)
    generated_at: datetime = Field(default_factory=utc_now)
    root: RepositoryTreeNode
    total_nodes: int = Field(default=0, ge=0)


class CodeBuilderHealth(StrictModel):
    """Health status of Code Builder dependencies."""

    healthy: bool
    repository_accessible: bool
    backup_directory_accessible: bool
    ollama: OllamaStatus
    active_tasks: int = Field(default=0, ge=0)
    pending_approvals: int = Field(default=0, ge=0)
    checked_at: datetime = Field(default_factory=utc_now)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


RepositoryTreeNode.model_rebuild()
