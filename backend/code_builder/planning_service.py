"""Change-planning service for the LUMINA Code Builder.

This module converts a natural-language user request and an existing
repository analysis into a structured change plan.

The planning service does not modify files. Its responsibilities are:

- Validate and normalize the user's development request.
- Select the most relevant repository context.
- Normalize Windows and POSIX repository paths.
- Prevent plans from referencing files outside the repository.
- Build deterministic prompts for the local Ollama model.
- Request structured JSON through Ollama.
- Validate and normalize the generated change plan.
- Convert the normalized plan into the Pydantic models defined in models.py.
- Produce warnings when a model proposes unsafe, missing, or ambiguous paths.

The Ollama execution, plan validation, repair pass, model conversion, and
public helper methods continue in Part 2 of this file.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import math
import os
import re
import time
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Final
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import models as code_builder_models
from .ollama_service import (
    OllamaConfigurationError,
    OllamaModelNotFoundError,
    OllamaResponseValidationError,
    OllamaService,
    OllamaServiceError,
    OllamaStructuredOutputError,
    OllamaTimeoutError,
    OllamaUnavailableError,
)
from .security import (
    BlockedFileError,
    UnsafePathError,
    evaluate_safe_path,
)


LOGGER = logging.getLogger(__name__)

UTC = timezone.utc

DEFAULT_PLANNING_MODEL: Final[str] = "qwen2.5-coder:7b"
DEFAULT_MAX_CONTEXT_FILES: Final[int] = 80
DEFAULT_MAX_CONTEXT_CHARACTERS: Final[int] = 180_000
DEFAULT_MAX_FILE_SUMMARY_CHARACTERS: Final[int] = 4_000
DEFAULT_MAX_USER_REQUEST_CHARACTERS: Final[int] = 50_000
DEFAULT_TIMEOUT_SECONDS: Final[float] = 300.0
DEFAULT_MAX_PLAN_REPAIR_ATTEMPTS: Final[int] = 1
DEFAULT_TEMPERATURE: Final[float] = 0.1
DEFAULT_TOP_P: Final[float] = 0.9
DEFAULT_CONTEXT_WINDOW: Final[int] = 4_096
DEFAULT_MAX_OUTPUT_TOKENS: Final[int] = 2_048
DEFAULT_INPUT_TOKEN_SAFETY_MARGIN: Final[int] = 2_048
DEFAULT_FIXED_PROMPT_OVERHEAD_TOKENS: Final[int] = 1_500
DEFAULT_MAX_CONTEXT_INPUT_TOKENS: Final[int] = 6_000
DEFAULT_MAX_DEPENDENCY_EXPANSION_DEPTH: Final[int] = 1
DEFAULT_MAX_DEPENDENCY_EXPANDED_FILES: Final[int] = 24
DEFAULT_MAX_SYMBOLS_PER_FILE: Final[int] = 12
DEFAULT_MAX_IMPORTS_PER_FILE: Final[int] = 10
DEFAULT_MAX_EXCERPT_CHARACTERS_PER_FILE: Final[int] = 1_200
DEFAULT_MAX_TOTAL_EXCERPT_CHARACTERS: Final[int] = 6_000
DEFAULT_MAX_SELECTED_CONTEXT_FILES: Final[int] = 32

MAX_PLAN_STEPS: Final[int] = 500
MAX_FILE_CHANGES: Final[int] = 500
MAX_DEPENDENCIES: Final[int] = 500
MAX_WARNINGS: Final[int] = 500
MAX_ACCEPTANCE_CRITERIA: Final[int] = 500
MAX_PATH_CHARACTERS: Final[int] = 1_024
MAX_TEXT_FIELD_CHARACTERS: Final[int] = 100_000

SOURCE_FILE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".py",
        ".pyi",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".mts",
        ".cts",
        ".json",
        ".jsonc",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".md",
        ".mdx",
        ".rst",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".sass",
        ".sql",
        ".sh",
        ".bash",
        ".zsh",
        ".ps1",
        ".psm1",
        ".dockerfile",
    }
)

HIGH_VALUE_FILE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "requirements-test.txt",
        "package.json",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "tsconfig.json",
        "jsconfig.json",
        "vite.config.ts",
        "vite.config.js",
        "webpack.config.ts",
        "webpack.config.js",
        "dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "readme.md",
        "readme",
        ".env.example",
        "alembic.ini",
        "pytest.ini",
        "tox.ini",
        "ruff.toml",
        "mypy.ini",
    }
)

TEST_FILE_PATTERNS: Final[tuple[str, ...]] = (
    "test_*.py",
    "*_test.py",
    "*.test.js",
    "*.test.jsx",
    "*.test.ts",
    "*.test.tsx",
    "*.spec.js",
    "*.spec.jsx",
    "*.spec.ts",
    "*.spec.tsx",
)

COMMON_OPERATION_ALIASES: Final[dict[str, str]] = {
    "add": "create",
    "new": "create",
    "create_file": "create",
    "create-directory": "create",
    "create_directory": "create",
    "modify": "update",
    "edit": "update",
    "change": "update",
    "replace": "update",
    "patch": "update",
    "refactor": "update",
    "remove": "delete",
    "delete_file": "delete",
    "move": "rename",
    "rename_file": "rename",
}

VALID_OPERATION_VALUES: Final[frozenset[str]] = frozenset(
    {
        "create",
        "update",
        "delete",
        "rename",
    }
)

RISK_LEVEL_ALIASES: Final[dict[str, str]] = {
    "none": "low",
    "minimal": "low",
    "minor": "low",
    "normal": "medium",
    "moderate": "medium",
    "major": "high",
    "critical": "critical",
    "dangerous": "critical",
}

VALID_RISK_LEVELS: Final[frozenset[str]] = frozenset(
    {
        "low",
        "medium",
        "high",
        "critical",
    }
)

MODEL_NAME_CANDIDATES: Final[tuple[str, ...]] = (
    "ChangePlan",
    "CodeChangePlan",
    "PlanningResult",
)

REQUEST_MODEL_NAME_CANDIDATES: Final[tuple[str, ...]] = (
    "ChangePlanRequest",
    "CodeChangePlanRequest",
    "PlanningRequest",
)

FILE_CHANGE_MODEL_NAME_CANDIDATES: Final[tuple[str, ...]] = (
    "ProposedFileChange",
    "PlannedFileChange",
    "FileChangePlan",
    "ChangePlanFile",
    "FileChange",
)

PLAN_STEP_MODEL_NAME_CANDIDATES: Final[tuple[str, ...]] = (
    "ChangePlanStep",
    "PlanStep",
    "PlanningStep",
)

CODEBASE_ANALYSIS_MODEL_NAME: Final[str] = "CodebaseAnalysis"

TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[A-Za-z\u0391-\u03A9\u03B1-\u03C90-9_./\\:-]+",
    flags=re.UNICODE,
)

WINDOWS_DRIVE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z]:"
)

MULTIPLE_SLASH_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"/{2,}"
)

CONTROL_CHARACTER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]"
)


class PlanningServiceError(RuntimeError):
    """Base exception for change-planning failures."""


class PlanningConfigurationError(PlanningServiceError):
    """Raised when planning configuration is invalid."""


class PlanningRequestError(PlanningServiceError):
    """Raised when a user planning request is invalid."""


class PlanningContextError(PlanningServiceError):
    """Raised when repository analysis cannot provide valid context."""


class PlanningGenerationError(PlanningServiceError):
    """Raised when Ollama cannot generate a usable plan."""


class PlanningValidationError(PlanningServiceError):
    """Raised when a generated plan violates planning requirements."""


class PlanningModelCompatibilityError(PlanningServiceError):
    """Raised when models.py does not expose a compatible plan model."""


class PlanningPathError(PlanningValidationError):
    """Raised when a generated file path is invalid or unsafe."""


class PlanningOperation(str, Enum):
    """Canonical file operations supported by the planning service."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RENAME = "rename"


class PlanningRiskLevel(str, Enum):
    """Normalized risk classification for a change plan."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class PlanningConfiguration:
    """Runtime configuration for change-plan generation."""

    model: str = DEFAULT_PLANNING_MODEL
    maximum_context_files: int = DEFAULT_MAX_CONTEXT_FILES
    maximum_context_characters: int = DEFAULT_MAX_CONTEXT_CHARACTERS
    maximum_file_summary_characters: int = (
        DEFAULT_MAX_FILE_SUMMARY_CHARACTERS
    )
    maximum_user_request_characters: int = (
        DEFAULT_MAX_USER_REQUEST_CHARACTERS
    )
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    maximum_repair_attempts: int = DEFAULT_MAX_PLAN_REPAIR_ATTEMPTS
    temperature: float = DEFAULT_TEMPERATURE
    top_p: float = DEFAULT_TOP_P
    context_window: int = DEFAULT_CONTEXT_WINDOW
    maximum_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    input_token_safety_margin: int = DEFAULT_INPUT_TOKEN_SAFETY_MARGIN
    fixed_prompt_overhead_tokens: int = DEFAULT_FIXED_PROMPT_OVERHEAD_TOKENS
    maximum_context_input_tokens: int = DEFAULT_MAX_CONTEXT_INPUT_TOKENS
    maximum_dependency_expansion_depth: int = (
        DEFAULT_MAX_DEPENDENCY_EXPANSION_DEPTH
    )
    maximum_dependency_expanded_files: int = (
        DEFAULT_MAX_DEPENDENCY_EXPANDED_FILES
    )
    maximum_symbols_per_file: int = DEFAULT_MAX_SYMBOLS_PER_FILE
    maximum_imports_per_file: int = DEFAULT_MAX_IMPORTS_PER_FILE
    maximum_excerpt_characters_per_file: int = (
        DEFAULT_MAX_EXCERPT_CHARACTERS_PER_FILE
    )
    maximum_total_excerpt_characters: int = (
        DEFAULT_MAX_TOTAL_EXCERPT_CHARACTERS
    )
    maximum_selected_context_files: int = (
        DEFAULT_MAX_SELECTED_CONTEXT_FILES
    )
    verify_model_before_request: bool = False
    include_symbols: bool = True
    include_imports: bool = True
    include_repository_statistics: bool = True
    include_environment: bool = True
    allow_new_files: bool = True
    allow_delete_operations: bool = True
    allow_rename_operations: bool = True
    require_acceptance_criteria: bool = True
    require_test_plan: bool = True
    reject_protected_paths: bool = True

    def __post_init__(self) -> None:
        """Validate planning configuration."""

        normalized_model = self.model.strip()

        if not normalized_model:
            raise PlanningConfigurationError(
                "The planning model cannot be empty."
            )

        if CONTROL_CHARACTER_PATTERN.search(normalized_model):
            raise PlanningConfigurationError(
                "The planning model contains invalid control characters."
            )

        object.__setattr__(self, "model", normalized_model)

        integer_limits = {
            "maximum_context_files": (
                self.maximum_context_files,
                1,
                5_000,
            ),
            "maximum_context_characters": (
                self.maximum_context_characters,
                1_000,
                10_000_000,
            ),
            "maximum_file_summary_characters": (
                self.maximum_file_summary_characters,
                100,
                1_000_000,
            ),
            "maximum_user_request_characters": (
                self.maximum_user_request_characters,
                1,
                1_000_000,
            ),
            "maximum_repair_attempts": (
                self.maximum_repair_attempts,
                0,
                5,
            ),
            "context_window": (
                self.context_window,
                1_024,
                2_000_000,
            ),
            "maximum_output_tokens": (
                self.maximum_output_tokens,
                128,
                500_000,
            ),
            "input_token_safety_margin": (
                self.input_token_safety_margin,
                0,
                500_000,
            ),
            "fixed_prompt_overhead_tokens": (
                self.fixed_prompt_overhead_tokens,
                0,
                500_000,
            ),
            "maximum_context_input_tokens": (
                self.maximum_context_input_tokens,
                512,
                500_000,
            ),
            "maximum_dependency_expansion_depth": (
                self.maximum_dependency_expansion_depth,
                0,
                5,
            ),
            "maximum_dependency_expanded_files": (
                self.maximum_dependency_expanded_files,
                0,
                1_000,
            ),
            "maximum_symbols_per_file": (
                self.maximum_symbols_per_file,
                0,
                1_000,
            ),
            "maximum_imports_per_file": (
                self.maximum_imports_per_file,
                0,
                1_000,
            ),
            "maximum_excerpt_characters_per_file": (
                self.maximum_excerpt_characters_per_file,
                0,
                100_000,
            ),
            "maximum_total_excerpt_characters": (
                self.maximum_total_excerpt_characters,
                0,
                1_000_000,
            ),
            "maximum_selected_context_files": (
                self.maximum_selected_context_files,
                1,
                1_000,
            ),
        }

        for field_name, (
            value,
            minimum,
            maximum,
        ) in integer_limits.items():
            if isinstance(value, bool) or not isinstance(
                value,
                int,
            ):
                raise PlanningConfigurationError(
                    f"{field_name} must be an integer."
                )

            if value < minimum or value > maximum:
                raise PlanningConfigurationError(
                    f"{field_name} must be between "
                    f"{minimum} and {maximum}."
                )

        float_limits = {
            "timeout_seconds": (
                self.timeout_seconds,
                1.0,
                3_600.0,
            ),
            "temperature": (
                self.temperature,
                0.0,
                2.0,
            ),
            "top_p": (
                self.top_p,
                0.0,
                1.0,
            ),
        }

        for field_name, (
            value,
            minimum,
            maximum,
        ) in float_limits.items():
            if isinstance(value, bool) or not isinstance(
                value,
                (int, float),
            ):
                raise PlanningConfigurationError(
                    f"{field_name} must be numeric."
                )

            numeric_value = float(value)

            if not math.isfinite(numeric_value):
                raise PlanningConfigurationError(
                    f"{field_name} must be finite."
                )

            if numeric_value < minimum or numeric_value > maximum:
                raise PlanningConfigurationError(
                    f"{field_name} must be between "
                    f"{minimum} and {maximum}."
                )


class GeneratedPlanStep(BaseModel):
    """Structured step returned by the Ollama planning model."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    order: int = Field(
        ge=1,
        le=MAX_PLAN_STEPS,
    )
    title: str = Field(
        min_length=1,
        max_length=1_000,
    )
    description: str = Field(
        min_length=1,
        max_length=MAX_TEXT_FIELD_CHARACTERS,
    )
    file_paths: list[str] = Field(
        default_factory=list,
        max_length=MAX_FILE_CHANGES,
    )
    depends_on: list[int] = Field(
        default_factory=list,
        max_length=MAX_PLAN_STEPS,
    )
    validation: list[str] = Field(
        default_factory=list,
        max_length=MAX_ACCEPTANCE_CRITERIA,
    )


class GeneratedFileChange(BaseModel):
    """Structured file change returned by the Ollama planning model."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    path: str = Field(
        min_length=1,
        max_length=MAX_PATH_CHARACTERS,
    )
    operation: str = Field(
        min_length=1,
        max_length=50,
    )
    destination_path: str | None = Field(
        default=None,
        max_length=MAX_PATH_CHARACTERS,
    )
    summary: str = Field(
        min_length=1,
        max_length=MAX_TEXT_FIELD_CHARACTERS,
    )
    rationale: str = Field(
        min_length=1,
        max_length=MAX_TEXT_FIELD_CHARACTERS,
    )
    implementation_notes: list[str] = Field(
        default_factory=list,
        max_length=MAX_ACCEPTANCE_CRITERIA,
    )
    affected_symbols: list[str] = Field(
        default_factory=list,
        max_length=MAX_DEPENDENCIES,
    )
    dependencies: list[str] = Field(
        default_factory=list,
        max_length=MAX_DEPENDENCIES,
    )
    tests: list[str] = Field(
        default_factory=list,
        max_length=MAX_ACCEPTANCE_CRITERIA,
    )
    risk_level: str = Field(
        default="medium",
        min_length=1,
        max_length=50,
    )
    breaking_change: bool = False


class GeneratedChangePlan(BaseModel):
    """Canonical structured schema requested from Ollama."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    title: str = Field(
        min_length=1,
        max_length=1_000,
    )
    summary: str = Field(
        min_length=1,
        max_length=MAX_TEXT_FIELD_CHARACTERS,
    )
    objective: str = Field(
        min_length=1,
        max_length=MAX_TEXT_FIELD_CHARACTERS,
    )
    assumptions: list[str] = Field(
        default_factory=list,
        max_length=MAX_WARNINGS,
    )
    risk_level: str = Field(
        default="medium",
        min_length=1,
        max_length=50,
    )
    breaking_changes: bool = False
    requires_user_action: bool = False
    required_user_actions: list[str] = Field(
        default_factory=list,
        max_length=MAX_WARNINGS,
    )
    files: list[GeneratedFileChange] = Field(
        min_length=1,
        max_length=MAX_FILE_CHANGES,
    )
    steps: list[GeneratedPlanStep] = Field(
        min_length=1,
        max_length=MAX_PLAN_STEPS,
    )
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        max_length=MAX_ACCEPTANCE_CRITERIA,
    )
    test_plan: list[str] = Field(
        default_factory=list,
        max_length=MAX_ACCEPTANCE_CRITERIA,
    )
    rollback_plan: list[str] = Field(
        default_factory=list,
        max_length=MAX_ACCEPTANCE_CRITERIA,
    )
    warnings: list[str] = Field(
        default_factory=list,
        max_length=MAX_WARNINGS,
    )


def _model_field_contract(model_type: type[BaseModel]) -> str:
    """Return a compact field/type contract for a Pydantic model."""

    lines: list[str] = []
    for field_name, field_info in model_type.model_fields.items():
        annotation = field_info.annotation
        type_name = getattr(annotation, "__name__", None)
        if type_name is None:
            type_name = str(annotation).replace("typing.", "")
        required = "required" if field_info.is_required() else "optional"
        lines.append(f"- {field_name}: {type_name} ({required})")
    return "\n".join(lines)


def _generated_change_plan_contract() -> str:
    """Return concise schema guidance derived from GeneratedChangePlan."""

    return (
        "GeneratedChangePlan top-level fields:\n"
        f"{_model_field_contract(GeneratedChangePlan)}\n"
        "files[] fields:\n"
        f"{_model_field_contract(GeneratedFileChange)}\n"
        "steps[] fields:\n"
        f"{_model_field_contract(GeneratedPlanStep)}\n"
        "Use JSON arrays for every list field. The list fields "
        "assumptions, required_user_actions, acceptance_criteria, "
        "test_plan, rollback_plan, warnings, implementation_notes, "
        "affected_symbols, dependencies, tests, file_paths, depends_on, "
        "and validation must contain only primitive values of their declared "
        "type, not objects. Use JSON objects only for each files[] item and "
        "each steps[] item. Do not include unknown fields. Return exactly "
        "one complete JSON object and no prose."
    )


def _format_validation_error_details(error: Exception) -> str:
    """Return field-specific validation details when available."""

    validation_error = error
    cause = getattr(error, "__cause__", None)
    if isinstance(cause, ValidationError):
        validation_error = cause

    if not isinstance(validation_error, ValidationError):
        return str(error).strip()

    lines: list[str] = []
    for detail in validation_error.errors():
        location = detail.get("loc", ())
        if isinstance(location, tuple):
            path = ".".join(str(part) for part in location)
        else:
            path = str(location)
        message = str(detail.get("msg", "validation failed"))
        error_type = str(detail.get("type", "unknown"))
        actual = detail.get("input", None)
        actual_type = type(actual).__name__
        lines.append(
            f"- path={path or '<root>'}; error={message}; "
            f"expected={error_type}; actual_type={actual_type}"
        )

    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class PlanningContextFile:
    """One repository file selected for model context."""

    relative_path: str
    file_name: str
    file_type: str
    role: str
    language: str | None
    size_bytes: int
    line_count: int | None
    sha256: str | None
    encoding: str | None
    is_generated: bool
    is_protected: bool
    symbols: tuple[str, ...]
    imports: tuple[str, ...]
    relevance_score: float
    relevance_reasons: tuple[str, ...] = ()
    important_symbols: tuple[str, ...] = ()
    important_imports: tuple[str, ...] = ()
    direct_dependencies: tuple[str, ...] = ()
    direct_dependents: tuple[str, ...] = ()
    source_excerpt: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable context metadata."""

        result: dict[str, Any] = {
            "relative_path": self.relative_path,
            "file_type": self.file_type,
            "role": self.role,
            "relevance_score": self.relevance_score,
            "relevance_reasons": list(self.relevance_reasons),
        }

        optional_values: dict[str, Any] = {
            "language": self.language,
            "line_count": self.line_count,
            "important_symbols": list(self.important_symbols),
            "important_imports": list(self.important_imports),
            "direct_dependencies": list(self.direct_dependencies),
            "direct_dependents": list(self.direct_dependents),
            "source_excerpt": self.source_excerpt,
        }

        for key, value in optional_values.items():
            if value not in (None, "", [], ()): 
                result[key] = value

        return result


@dataclass(frozen=True, slots=True)
class PlanningContext:
    """Normalized repository context passed to Ollama."""

    repository_root: Path
    repository_name: str
    analysis_id: str | None
    request: str
    selected_files: tuple[PlanningContextFile, ...]
    repository_statistics: dict[str, Any]
    environment: dict[str, Any]
    warnings: tuple[str, ...]
    generated_at: datetime
    overview: dict[str, Any] | None = None
    context_metadata: dict[str, Any] | None = None
    omitted_files: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable planning context."""

        result: dict[str, Any] = {
            "repository_name": self.repository_name,
            "analysis_id": self.analysis_id,
            "request": self.request,
            "overview": self.overview or {},
            "selected_files": [
                file_context.to_dict()
                for file_context in self.selected_files
            ],
            "environment": self.environment,
            "context_metadata": self.context_metadata or {},
            "generated_at": self.generated_at.isoformat(),
        }

        if self.repository_statistics:
            result["repository_statistics"] = self.repository_statistics
        if self.warnings:
            result["warnings"] = list(self.warnings)
        if self.omitted_files:
            result["omitted_files"] = list(self.omitted_files)

        return result


@dataclass(frozen=True, slots=True)
class NormalizedFileChange:
    """Validated and normalized file change."""

    path: str
    operation: PlanningOperation
    destination_path: str | None
    summary: str
    rationale: str
    implementation_notes: tuple[str, ...]
    affected_symbols: tuple[str, ...]
    dependencies: tuple[str, ...]
    tests: tuple[str, ...]
    risk_level: PlanningRiskLevel
    breaking_change: bool
    exists_in_repository: bool
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable file-change data."""

        return {
            "path": self.path,
            "operation": self.operation.value,
            "destination_path": self.destination_path,
            "summary": self.summary,
            "rationale": self.rationale,
            "implementation_notes": list(
                self.implementation_notes
            ),
            "affected_symbols": list(
                self.affected_symbols
            ),
            "dependencies": list(self.dependencies),
            "tests": list(self.tests),
            "risk_level": self.risk_level.value,
            "breaking_change": self.breaking_change,
            "exists_in_repository": (
                self.exists_in_repository
            ),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class NormalizedChangePlan:
    """Internal normalized change-plan representation."""

    plan_id: UUID
    task_id: str | None
    title: str
    summary: str
    objective: str
    user_request: str
    repository_root: str
    repository_name: str
    analysis_id: str | None
    model: str
    risk_level: PlanningRiskLevel
    breaking_changes: bool
    requires_user_action: bool
    required_user_actions: tuple[str, ...]
    assumptions: tuple[str, ...]
    files: tuple[NormalizedFileChange, ...]
    steps: tuple[GeneratedPlanStep, ...]
    acceptance_criteria: tuple[str, ...]
    test_plan: tuple[str, ...]
    rollback_plan: tuple[str, ...]
    warnings: tuple[str, ...]
    created_at: datetime
    generation_duration_seconds: float
    repaired: bool

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable plan data."""

        return {
            "plan_id": str(self.plan_id),
            "task_id": self.task_id,
            "title": self.title,
            "summary": self.summary,
            "objective": self.objective,
            "user_request": self.user_request,
            "repository_root": self.repository_root,
            "repository_name": self.repository_name,
            "analysis_id": self.analysis_id,
            "model": self.model,
            "risk_level": self.risk_level.value,
            "breaking_changes": self.breaking_changes,
            "requires_user_action": (
                self.requires_user_action
            ),
            "required_user_actions": list(
                self.required_user_actions
            ),
            "assumptions": list(self.assumptions),
            "files": [
                file_change.to_dict()
                for file_change in self.files
            ],
            "steps": [
                step.model_dump(mode="json")
                for step in self.steps
            ],
            "acceptance_criteria": list(
                self.acceptance_criteria
            ),
            "test_plan": list(self.test_plan),
            "rollback_plan": list(self.rollback_plan),
            "warnings": list(self.warnings),
            "created_at": self.created_at.isoformat(),
            "generation_duration_seconds": (
                self.generation_duration_seconds
            ),
            "repaired": self.repaired,
        }


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""

    return datetime.now(UTC)


def _enum_value(value: Any) -> str:
    """Return a stable string value for enums and ordinary values."""

    if isinstance(value, Enum):
        return str(value.value)

    if value is None:
        return ""

    return str(value)


def _model_dump(
    value: Any,
    *,
    exclude_none: bool = False,
) -> dict[str, Any]:
    """Convert a Pydantic model, dataclass-like object, or mapping to dict."""

    if isinstance(value, BaseModel):
        return value.model_dump(
            mode="json",
            exclude_none=exclude_none,
        )

    if isinstance(value, Mapping):
        return dict(value)

    result: dict[str, Any] = {}

    for attribute_name in dir(value):
        if attribute_name.startswith("_"):
            continue

        try:
            attribute_value = getattr(
                value,
                attribute_name,
            )
        except Exception:
            continue

        if callable(attribute_value):
            continue

        result[attribute_name] = attribute_value

    return result


def _get_attribute(
    value: Any,
    *names: str,
    default: Any = None,
) -> Any:
    """Return the first available attribute or mapping key."""

    for name in names:
        if isinstance(value, Mapping) and name in value:
            return value[name]

        if hasattr(value, name):
            try:
                return getattr(value, name)
            except Exception:
                continue

    return default


def _normalize_request_text(
    request: str,
    *,
    maximum_characters: int,
) -> str:
    """Validate and normalize the user's planning instruction."""

    if not isinstance(request, str):
        raise PlanningRequestError(
            "The planning request must be a string."
        )

    normalized = request.strip()

    if not normalized:
        raise PlanningRequestError(
            "The planning request cannot be empty."
        )

    if CONTROL_CHARACTER_PATTERN.search(normalized):
        raise PlanningRequestError(
            "The planning request contains invalid control characters."
        )

    if len(normalized) > maximum_characters:
        raise PlanningRequestError(
            "The planning request exceeds the maximum permitted length "
            f"of {maximum_characters} characters."
        )

    return normalized


def _normalize_string_list(
    values: Iterable[Any] | None,
    *,
    maximum_items: int,
    maximum_item_characters: int = 10_000,
) -> tuple[str, ...]:
    """Normalize, bound, and deduplicate a sequence of strings."""

    if values is None:
        return ()

    if isinstance(values, (str, bytes, bytearray)):
        values = [values]

    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        if len(result) >= maximum_items:
            break

        normalized = str(value).strip()

        if not normalized:
            continue

        if len(normalized) > maximum_item_characters:
            normalized = normalized[
                :maximum_item_characters
            ].rstrip()

        comparison_key = normalized.casefold()

        if comparison_key in seen:
            continue

        seen.add(comparison_key)
        result.append(normalized)

    return tuple(result)


def _normalize_operation(
    value: str,
) -> PlanningOperation:
    """Normalize a model-generated file operation."""

    normalized = value.strip().casefold()
    normalized = normalized.replace(" ", "_")

    normalized = COMMON_OPERATION_ALIASES.get(
        normalized,
        normalized,
    )

    if normalized not in VALID_OPERATION_VALUES:
        raise PlanningValidationError(
            f"Unsupported file operation: {value}"
        )

    return PlanningOperation(normalized)


def _normalize_risk_level(
    value: str | None,
) -> PlanningRiskLevel:
    """Normalize a model-generated risk level."""

    normalized = (
        value.strip().casefold()
        if isinstance(value, str)
        else "medium"
    )

    normalized = RISK_LEVEL_ALIASES.get(
        normalized,
        normalized,
    )

    if normalized not in VALID_RISK_LEVELS:
        normalized = "medium"

    return PlanningRiskLevel(normalized)


def _canonical_path_text(path_value: str) -> str:
    """Convert a Windows or POSIX path to normalized POSIX notation."""

    if not isinstance(path_value, str):
        raise PlanningPathError(
            "A generated file path must be a string."
        )

    normalized = path_value.strip()

    if not normalized:
        raise PlanningPathError(
            "A generated file path cannot be empty."
        )

    if len(normalized) > MAX_PATH_CHARACTERS:
        raise PlanningPathError(
            "A generated file path exceeds the maximum length."
        )

    if CONTROL_CHARACTER_PATTERN.search(normalized):
        raise PlanningPathError(
            "A generated file path contains invalid control characters."
        )

    normalized = normalized.replace("\\", "/")
    normalized = MULTIPLE_SLASH_PATTERN.sub(
        "/",
        normalized,
    )

    while normalized.startswith("./"):
        normalized = normalized[2:]

    return normalized.rstrip("/")


def _resolve_repository_root(
    analysis: Any,
) -> Path:
    """Resolve the repository root from the codebase analysis."""

    root_value = _get_attribute(
        analysis,
        "repository_root",
        "root",
        default=None,
    )

    if root_value is None:
        raise PlanningContextError(
            "The codebase analysis does not contain a repository root."
        )

    try:
        root = Path(str(root_value)).expanduser().resolve(
            strict=False
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise PlanningContextError(
            "The repository root could not be resolved."
        ) from exc

    if not root.exists():
        raise PlanningContextError(
            f"The repository root does not exist: {root}"
        )

    if not root.is_dir():
        raise PlanningContextError(
            f"The repository root is not a directory: {root}"
        )

    return root


def _normalize_repository_path(
    path_value: str,
    *,
    repository_root: Path,
    allow_nonexistent: bool,
    reject_protected: bool,
) -> tuple[str, Path, bool, str | None]:
    """Normalize and validate a generated repository path.

    Returns:

    - normalized repository-relative POSIX path
    - resolved absolute path
    - whether the path currently exists
    - optional security warning
    """

    normalized = _canonical_path_text(
        path_value
    )

    root_text = str(repository_root).replace(
        "\\",
        "/",
    ).rstrip("/")

    normalized_casefold = normalized.casefold()
    root_casefold = root_text.casefold()

    if normalized_casefold == root_casefold:
        raise PlanningPathError(
            "A change plan cannot target the repository root itself."
        )

    if normalized_casefold.startswith(
        f"{root_casefold}/"
    ):
        normalized = normalized[
            len(root_text) + 1:
        ]

    if WINDOWS_DRIVE_PATTERN.match(normalized):
        windows_path = PureWindowsPath(normalized)

        try:
            candidate_absolute = Path(
                str(windows_path)
            ).resolve(strict=False)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PlanningPathError(
                f"Invalid Windows path: {path_value}"
            ) from exc

        try:
            relative_path = candidate_absolute.relative_to(
                repository_root
            )
        except ValueError as exc:
            raise PlanningPathError(
                "The generated path is outside the repository: "
                f"{path_value}"
            ) from exc

    elif normalized.startswith("/"):
        try:
            candidate_absolute = Path(
                normalized
            ).resolve(strict=False)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PlanningPathError(
                f"Invalid absolute path: {path_value}"
            ) from exc

        try:
            relative_path = candidate_absolute.relative_to(
                repository_root
            )
        except ValueError as exc:
            raise PlanningPathError(
                "The generated path is outside the repository: "
                f"{path_value}"
            ) from exc

    else:
        pure_path = PurePosixPath(normalized)

        if any(
            part in {"", ".", ".."}
            for part in pure_path.parts
        ):
            raise PlanningPathError(
                "The generated path contains an unsafe path segment: "
                f"{path_value}"
            )

        relative_path = Path(*pure_path.parts)

    decision = evaluate_safe_path(
        repository_root=repository_root,
        requested_path=relative_path,
        allow_absolute=False,
        require_exists=not allow_nonexistent,
        allow_repository_root=False,
        check_blocked=reject_protected,
    )

    if not decision.allowed:
        message = (
            decision.message
            or f"Unsafe generated path: {path_value}"
        )

        if reject_protected:
            raise PlanningPathError(message)

        security_warning = message
    else:
        security_warning = None

    try:
        resolved_path = (
            repository_root / relative_path
        ).resolve(strict=False)

        resolved_path.relative_to(repository_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PlanningPathError(
            "The generated path escapes the repository: "
            f"{path_value}"
        ) from exc

    relative_text = relative_path.as_posix()

    return (
        relative_text,
        resolved_path,
        resolved_path.exists(),
        security_warning,
    )


def _extract_request_tokens(
    request: str,
) -> set[str]:
    """Extract searchable tokens from the user's request."""

    tokens: set[str] = set()

    for match in TOKEN_PATTERN.finditer(request):
        token = match.group(0).strip(
            "._/\\:-"
        ).casefold()

        if len(token) < 2:
            continue

        tokens.add(token)

        for segment in re.split(
            r"[./\\:_-]+",
            token,
        ):
            segment = segment.strip()

            if len(segment) >= 2:
                tokens.add(segment)

    return tokens


def _path_tokens(path_value: str) -> set[str]:
    """Extract searchable tokens from a repository path."""

    normalized = path_value.replace("\\", "/")
    tokens: set[str] = set()

    for part in normalized.split("/"):
        part = part.strip().casefold()

        if not part:
            continue

        tokens.add(part)

        stem = Path(part).stem.casefold()

        if stem:
            tokens.add(stem)

        for segment in re.split(
            r"[._-]+",
            part,
        ):
            segment = segment.strip()

            if len(segment) >= 2:
                tokens.add(segment)

    return tokens


def _file_relevance_score(
    metadata: Any,
    *,
    request_tokens: set[str],
    symbol_names: Sequence[str],
    import_names: Sequence[str],
) -> float:
    """Calculate a deterministic relevance score for one repository file."""

    relative_path = str(
        _get_attribute(
            metadata,
            "relative_path",
            "path",
            default="",
        )
    )

    file_name = str(
        _get_attribute(
            metadata,
            "file_name",
            "name",
            default=Path(relative_path).name,
        )
    )

    role = _enum_value(
        _get_attribute(
            metadata,
            "role",
            default="",
        )
    ).casefold()

    path_token_values = _path_tokens(relative_path)
    symbol_token_values = {
        token.casefold()
        for symbol_name in symbol_names
        for token in _path_tokens(symbol_name)
    }
    import_token_values = {
        token.casefold()
        for import_name in import_names
        for token in _path_tokens(import_name)
    }

    exact_path_matches = len(
        request_tokens.intersection(
            path_token_values
        )
    )
    symbol_matches = len(
        request_tokens.intersection(
            symbol_token_values
        )
    )
    import_matches = len(
        request_tokens.intersection(
            import_token_values
        )
    )

    score = (
        exact_path_matches * 12.0
        + symbol_matches * 8.0
        + import_matches * 4.0
    )

    lowered_name = file_name.casefold()

    if lowered_name in HIGH_VALUE_FILE_NAMES:
        score += 8.0

    if role in {"source", "configuration", "test"}:
        score += 4.0

    if role in {
        "generated",
        "build_artifact",
        "dependency",
        "asset",
    }:
        score -= 20.0

    if _matches_test_pattern(file_name):
        score += 2.0

    if relative_path.casefold().startswith(
        "backend/code_builder/"
    ):
        score += 6.0

    return score


def _matches_test_pattern(file_name: str) -> bool:
    """Return whether a filename appears to be a test file."""

    lowered = file_name.casefold()

    return any(
        fnmatch.fnmatch(
            lowered,
            pattern.casefold(),
        )
        for pattern in TEST_FILE_PATTERNS
    )


def _analysis_files(
    analysis: Any,
) -> list[Any]:
    """Return the repository file metadata collection."""

    files_value = _get_attribute(
        analysis,
        "files",
        default=[],
    )

    if files_value is None:
        return []

    if isinstance(
        files_value,
        (str, bytes, bytearray),
    ):
        raise PlanningContextError(
            "The codebase analysis contains an invalid files collection."
        )

    try:
        return list(files_value)
    except TypeError as exc:
        raise PlanningContextError(
            "The codebase analysis files collection is not iterable."
        ) from exc


def _analysis_symbols_by_path(
    analysis: Any,
) -> dict[str, list[str]]:
    """Create a normalized symbol index grouped by repository path."""

    symbols_value = _get_attribute(
        analysis,
        "symbols",
        default=[],
    )

    result: dict[str, list[str]] = {}

    if symbols_value is None:
        return result

    for symbol in symbols_value:
        location = _get_attribute(
            symbol,
            "location",
            default=None,
        )

        relative_path = _get_attribute(
            location,
            "relative_path",
            "path",
            default=None,
        )

        if relative_path is None:
            relative_path = _get_attribute(
                symbol,
                "relative_path",
                "source_path",
                default=None,
            )

        name = _get_attribute(
            symbol,
            "qualified_name",
            "name",
            default=None,
        )

        if relative_path is None or name is None:
            continue

        path_key = str(relative_path).replace(
            "\\",
            "/",
        ).casefold()

        result.setdefault(path_key, []).append(
            str(name)
        )

    for path_key, names in result.items():
        result[path_key] = list(
            _normalize_string_list(
                names,
                maximum_items=500,
                maximum_item_characters=1_000,
            )
        )

    return result


def _analysis_imports_by_path(
    analysis: Any,
) -> dict[str, list[str]]:
    """Create a normalized import index grouped by source path."""

    imports_value = _get_attribute(
        analysis,
        "imports",
        default=[],
    )

    result: dict[str, list[str]] = {}

    if imports_value is None:
        return result

    for import_reference in imports_value:
        source_path = _get_attribute(
            import_reference,
            "source_path",
            "relative_path",
            default=None,
        )

        module_name = _get_attribute(
            import_reference,
            "module",
            "name",
            default=None,
        )

        resolved_path = _get_attribute(
            import_reference,
            "resolved_path",
            default=None,
        )

        if source_path is None:
            continue

        values: list[str] = []

        if module_name is not None:
            values.append(str(module_name))

        if resolved_path is not None:
            values.append(str(resolved_path))

        if not values:
            continue

        path_key = str(source_path).replace(
            "\\",
            "/",
        ).casefold()

        result.setdefault(path_key, []).extend(
            values
        )

    for path_key, values in result.items():
        result[path_key] = list(
            _normalize_string_list(
                values,
                maximum_items=500,
                maximum_item_characters=2_000,
            )
        )

    return result


def _truncate_text(
    value: str,
    maximum_characters: int,
) -> str:
    """Truncate text without producing invalid Unicode."""

    if len(value) <= maximum_characters:
        return value

    suffix = "\n[truncated]"

    available = max(
        maximum_characters - len(suffix),
        0,
    )

    return value[:available].rstrip() + suffix


def _estimate_tokens(value: str) -> int:
    """Estimate prompt tokens conservatively from text length."""

    if not value:
        return 0

    return max(1, math.ceil(len(value) / 4))


def _compact_dict(value: Mapping[str, Any]) -> dict[str, Any]:
    """Drop empty fields from a JSON-ready mapping."""

    result: dict[str, Any] = {}

    for key, item in value.items():
        if item in (None, "", [], (), {}):
            continue

        result[key] = item

    return result


def _path_key(value: str) -> str:
    """Normalize a repository path for dictionary indexes."""

    return str(value).replace("\\", "/").casefold()


def _file_summary_text(
    *,
    relative_path: str,
    role: str,
    language: str | None,
    symbols: Sequence[str],
    imports: Sequence[str],
) -> str:
    """Build a concise implementation-planning summary."""

    fragments = [relative_path, role]

    if language:
        fragments.append(language)

    if symbols:
        fragments.append(
            "symbols: " + ", ".join(symbols[:6])
        )

    if imports:
        fragments.append(
            "imports: " + ", ".join(imports[:4])
        )

    return "; ".join(fragments)


def _stable_json_hash(value: Any) -> str:
    """Calculate a deterministic SHA-256 hash for JSON-compatible data."""

    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )

    return hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()


class PlanningService:
    """Generate structured repository change plans through local Ollama."""

    def __init__(
        self,
        *,
        ollama_service: OllamaService,
        configuration: PlanningConfiguration | None = None,
    ) -> None:
        """Initialize the planning service."""

        if not isinstance(
            ollama_service,
            OllamaService,
        ):
            raise PlanningConfigurationError(
                "ollama_service must be an OllamaService instance."
            )

        self.ollama_service = ollama_service
        self.configuration = (
            configuration
            if configuration is not None
            else PlanningConfiguration()
        )

    def build_context(
        self,
        *,
        user_request: str,
        analysis: Any,
    ) -> PlanningContext:
        """Build compact semantic repository context for the planning model."""

        started_at = time.monotonic()

        normalized_request = _normalize_request_text(
            user_request,
            maximum_characters=(
                self.configuration
                .maximum_user_request_characters
            ),
        )

        repository_root = _resolve_repository_root(
            analysis
        )

        repository_name = str(
            _get_attribute(
                analysis,
                "repository_name",
                "name",
                default=repository_root.name,
            )
            or repository_root.name
            or "repository"
        )

        analysis_id_value = _get_attribute(
            analysis,
            "analysis_id",
            "id",
            default=None,
        )

        analysis_id = (
            str(analysis_id_value)
            if analysis_id_value is not None
            else None
        )

        files = _analysis_files(analysis)
        symbols_by_path = _analysis_symbols_by_path(analysis)
        imports_by_path = _analysis_imports_by_path(analysis)
        request_tokens = _extract_request_tokens(
            normalized_request
        )

        dependency_map: dict[str, set[str]] = {}
        importer_map: dict[str, set[str]] = {}
        path_lookup: dict[str, Any] = {}
        original_candidate_count = 0

        for metadata in files:
            relative_path_value = _get_attribute(
                metadata,
                "relative_path",
                "path",
                default=None,
            )

            if relative_path_value is None:
                continue

            relative_path = str(relative_path_value).replace("\\", "/")
            path_lookup[_path_key(relative_path)] = metadata

        for source_key, import_values in imports_by_path.items():
            for import_value in import_values:
                import_text = str(import_value).replace("\\", "/")
                if "/" not in import_text and not any(import_text.endswith(suffix) for suffix in SOURCE_FILE_SUFFIXES):
                    continue

                dependency_key = _path_key(import_text)
                if dependency_key not in path_lookup:
                    continue

                dependency_map.setdefault(source_key, set()).add(
                    dependency_key
                )
                importer_map.setdefault(dependency_key, set()).add(
                    source_key
                )

        context_candidates: list[PlanningContextFile] = []

        context_warnings: list[str] = []

        for metadata in files:
            relative_path_value = _get_attribute(
                metadata,
                "relative_path",
                "path",
                default=None,
            )

            if relative_path_value is None:
                continue

            relative_path = str(
                relative_path_value
            ).replace("\\", "/")

            file_name = str(
                _get_attribute(
                    metadata,
                    "file_name",
                    "name",
                    default=Path(relative_path).name,
                )
            )

            suffix = Path(file_name).suffix.casefold()

            is_binary = bool(
                _get_attribute(
                    metadata,
                    "is_binary",
                    default=False,
                )
            )

            is_protected = bool(
                _get_attribute(
                    metadata,
                    "is_protected",
                    default=False,
                )
            )

            is_generated = bool(
                _get_attribute(
                    metadata,
                    "is_generated",
                    default=False,
                )
            )

            if is_binary:
                continue

            if is_protected:
                context_warnings.append(
                    "Protected file excluded from model context: "
                    f"{relative_path}"
                )
                continue

            if (
                suffix
                and suffix not in SOURCE_FILE_SUFFIXES
                and file_name.casefold()
                not in HIGH_VALUE_FILE_NAMES
            ):
                continue

            original_candidate_count += 1

            path_key = _path_key(relative_path)
            symbol_names = symbols_by_path.get(
                path_key,
                [],
            )
            import_names = imports_by_path.get(
                path_key,
                [],
            )

            relevance_score = _file_relevance_score(
                metadata,
                request_tokens=request_tokens,
                symbol_names=symbol_names,
                import_names=import_names,
            )

            relevance_reasons: list[str] = []
            path_tokens = _path_tokens(relative_path)
            symbol_tokens = {
                token.casefold()
                for symbol_name in symbol_names
                for token in _extract_request_tokens(symbol_name)
            }
            import_tokens = {
                token.casefold()
                for import_name in import_names
                for token in _extract_request_tokens(import_name)
            }

            if request_tokens & path_tokens:
                relevance_score += 3.0
                relevance_reasons.append("path_or_filename_match")
            if request_tokens & symbol_tokens:
                relevance_score += 4.0
                relevance_reasons.append("symbol_match")
            if request_tokens & import_tokens:
                relevance_score += 1.5
                relevance_reasons.append("import_match")
            if _matches_test_pattern(file_name):
                relevance_score += 0.75
                relevance_reasons.append("test_file")
            if file_name.casefold() in HIGH_VALUE_FILE_NAMES:
                relevance_score += 1.0
                relevance_reasons.append("configuration_file")
            if not relevance_reasons:
                relevance_reasons.append("repository_relevance")

            file_type_value = _enum_value(
                _get_attribute(
                    metadata,
                    "file_type",
                    "type",
                    default="unknown",
                )
            )

            role_value = _enum_value(
                _get_attribute(
                    metadata,
                    "role",
                    default="unknown",
                )
            )

            language_value = _get_attribute(
                metadata,
                "language",
                default=None,
            )

            size_value = _get_attribute(
                metadata,
                "size_bytes",
                "size",
                default=0,
            )

            line_count_value = _get_attribute(
                metadata,
                "line_count",
                default=None,
            )

            context_candidates.append(
                PlanningContextFile(
                    relative_path=relative_path,
                    file_name=file_name,
                    file_type=file_type_value,
                    role=role_value,
                    language=(
                        str(language_value)
                        if language_value is not None
                        else None
                    ),
                    size_bytes=(
                        int(size_value)
                        if isinstance(
                            size_value,
                            int,
                        )
                        and not isinstance(
                            size_value,
                            bool,
                        )
                        else 0
                    ),
                    line_count=(
                        int(line_count_value)
                        if isinstance(
                            line_count_value,
                            int,
                        )
                        and not isinstance(
                            line_count_value,
                            bool,
                        )
                        else None
                    ),
                    sha256=(
                        str(
                            _get_attribute(
                                metadata,
                                "sha256",
                                default=None,
                            )
                        )
                        if _get_attribute(
                            metadata,
                            "sha256",
                            default=None,
                        )
                        is not None
                        else None
                    ),
                    encoding=(
                        str(
                            _get_attribute(
                                metadata,
                                "encoding",
                                default=None,
                            )
                        )
                        if _get_attribute(
                            metadata,
                            "encoding",
                            default=None,
                        )
                        is not None
                        else None
                    ),
                    is_generated=is_generated,
                    is_protected=is_protected,
                    symbols=tuple(symbol_names),
                    imports=tuple(import_names),
                    relevance_score=relevance_score,
                    relevance_reasons=tuple(relevance_reasons),
                    important_symbols=tuple(
                        symbol_names[
                            :self.configuration.maximum_symbols_per_file
                        ]
                    ),
                    important_imports=tuple(
                        import_names[
                            :self.configuration.maximum_imports_per_file
                        ]
                    ),
                    direct_dependencies=tuple(
                        sorted(dependency_map.get(path_key, set()))[
                            :self.configuration
                            .maximum_dependency_expanded_files
                        ]
                    ),
                    direct_dependents=tuple(
                        sorted(importer_map.get(path_key, set()))[
                            :self.configuration
                            .maximum_dependency_expanded_files
                        ]
                    ),
                )
            )

        context_candidates.sort(
            key=lambda item: (
                -item.relevance_score,
                item.relative_path.casefold(),
            )
        )

        selected_keys: set[str] = set()
        expanded_keys: set[str] = set()
        selected_candidates: list[PlanningContextFile] = []
        maximum_selected_files = min(
            self.configuration.maximum_context_files,
            self.configuration.maximum_selected_context_files,
        )

        for candidate in context_candidates:
            if len(selected_candidates) >= maximum_selected_files:
                break

            key = _path_key(candidate.relative_path)
            if key not in selected_keys:
                selected_candidates.append(candidate)
                selected_keys.add(key)

            if (
                self.configuration.maximum_dependency_expansion_depth > 0
                and len(expanded_keys)
                < self.configuration.maximum_dependency_expanded_files
            ):
                for related_key in sorted(
                    dependency_map.get(key, set())
                    | importer_map.get(key, set())
                ):
                    if len(selected_candidates) >= maximum_selected_files:
                        break
                    if (
                        len(expanded_keys)
                        >= self.configuration
                        .maximum_dependency_expanded_files
                    ):
                        break
                    if related_key in selected_keys:
                        continue
                    related = next(
                        (
                            item
                            for item in context_candidates
                            if _path_key(item.relative_path) == related_key
                        ),
                        None,
                    )
                    if related is None:
                        continue
                    selected_candidates.append(
                        replace(
                            related,
                            relevance_reasons=tuple(
                                [
                                    *related.relevance_reasons,
                                    "dependency_expansion",
                                ]
                            ),
                        )
                    )
                    selected_keys.add(related_key)
                    expanded_keys.add(related_key)

        base_prompt_tokens = (
            _estimate_tokens(normalized_request)
            + self.configuration.fixed_prompt_overhead_tokens
        )
        adaptive_input_budget_tokens = max(
            512,
            self.configuration.context_window
            - self.configuration.maximum_output_tokens
            - self.configuration.input_token_safety_margin,
        )
        if (
            self.configuration.context_window == DEFAULT_CONTEXT_WINDOW
            and self.configuration.input_token_safety_margin
            == DEFAULT_INPUT_TOKEN_SAFETY_MARGIN
        ):
            adaptive_input_budget_tokens = max(
                adaptive_input_budget_tokens,
                self.configuration.maximum_context_input_tokens,
            )
        context_budget_tokens = max(
            512,
            min(
                self.configuration.maximum_context_input_tokens,
                adaptive_input_budget_tokens,
            ),
        )
        available_context_tokens = max(
            256,
            context_budget_tokens - base_prompt_tokens,
        )

        budgeted_files: list[PlanningContextFile] = []
        used_context_tokens = 0
        excerpt_characters_used = 0

        for candidate in selected_candidates:
            excerpt: str | None = None
            if (
                candidate.relevance_score >= 4.0
                and excerpt_characters_used
                < self.configuration.maximum_total_excerpt_characters
                and self.configuration.maximum_excerpt_characters_per_file
                > 0
            ):
                excerpt = _file_summary_text(
                    relative_path=candidate.relative_path,
                    role=candidate.role,
                    language=candidate.language,
                    symbols=candidate.important_symbols,
                    imports=candidate.important_imports,
                )
                excerpt = _truncate_text(
                    excerpt,
                    min(
                        self.configuration
                        .maximum_excerpt_characters_per_file,
                        self.configuration
                        .maximum_total_excerpt_characters
                        - excerpt_characters_used,
                    ),
                )

            budget_candidate = replace(
                candidate,
                source_excerpt=excerpt,
            )
            candidate_tokens = _estimate_tokens(
                json.dumps(
                    budget_candidate.to_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
            )
            if (
                budgeted_files
                and used_context_tokens + candidate_tokens
                > available_context_tokens
            ):
                break
            budgeted_files.append(budget_candidate)
            used_context_tokens += candidate_tokens
            if excerpt:
                excerpt_characters_used += len(excerpt)

        selected_files = tuple(budgeted_files)
        omitted_candidates = max(
            0,
            len(context_candidates) - len(selected_files),
        )

        statistics_value = _get_attribute(
            analysis,
            "statistics",
            default={},
        )

        repository_statistics = (
            _compact_dict(
                {
                    "total_files": _get_attribute(
                        statistics_value,
                        "total_files",
                        default=None,
                    ),
                    "indexed_files": _get_attribute(
                        statistics_value,
                        "indexed_files",
                        default=None,
                    ),
                    "files_by_type": _get_attribute(
                        statistics_value,
                        "files_by_type",
                        default=None,
                    ),
                    "files_by_role": _get_attribute(
                        statistics_value,
                        "files_by_role",
                        default=None,
                    ),
                }
            )
            if self.configuration
            .include_repository_statistics
            else {}
        )

        environment = (
            {
                "backend_detected": _get_attribute(
                    analysis,
                    "backend_detected",
                    default=False,
                ),
                "frontend_detected": _get_attribute(
                    analysis,
                    "frontend_detected",
                    default=False,
                ),
                "backend_framework": _get_attribute(
                    analysis,
                    "backend_framework",
                    default=None,
                ),
                "frontend_framework": _get_attribute(
                    analysis,
                    "frontend_framework",
                    default=None,
                ),
                "package_managers": list(
                    _get_attribute(
                        analysis,
                        "package_managers",
                        default=[],
                    )
                    or []
                ),
                "test_frameworks": list(
                    _get_attribute(
                        analysis,
                        "test_frameworks",
                        default=[],
                    )
                    or []
                ),
                "build_commands": list(
                    _get_attribute(
                        analysis,
                        "build_commands",
                        default=[],
                    )
                    or []
                ),
                "test_commands": list(
                    _get_attribute(
                        analysis,
                        "test_commands",
                        default=[],
                    )
                    or []
                ),
            }
            if self.configuration.include_environment
            else {}
        )

        analysis_warnings = _get_attribute(
            analysis,
            "warnings",
            default=[],
        )

        warnings = _normalize_string_list(
            [
                *(analysis_warnings or []),
                *context_warnings,
            ],
            maximum_items=MAX_WARNINGS,
        )

        overview = _compact_dict(
            {
                "repository": repository_name,
                "backend_framework": environment.get(
                    "backend_framework"
                ),
                "frontend_framework": environment.get(
                    "frontend_framework"
                ),
                "package_managers": environment.get(
                    "package_managers"
                ),
                "test_frameworks": environment.get(
                    "test_frameworks"
                ),
                "build_commands": environment.get(
                    "build_commands"
                ),
                "test_commands": environment.get(
                    "test_commands"
                ),
            }
        )

        context_metadata = {
            "selected_file_count": len(selected_files),
            "omitted_candidate_count": omitted_candidates,
            "estimated_prompt_tokens": (
                base_prompt_tokens + used_context_tokens
            ),
            "context_budget_tokens": context_budget_tokens,
            "adaptive_input_budget_tokens": adaptive_input_budget_tokens,
            "reserved_output_tokens": (
                self.configuration.maximum_output_tokens
            ),
            "input_token_safety_margin": (
                self.configuration.input_token_safety_margin
            ),
            "fixed_prompt_overhead_tokens": (
                self.configuration.fixed_prompt_overhead_tokens
            ),
            "selection_strategy": (
                "weighted_semantic_relevance_with_dependency_expansion"
            ),
            "dependency_expansion_depth": (
                self.configuration
                .maximum_dependency_expansion_depth
            ),
            "dependency_expanded_file_count": len(expanded_keys),
            "excerpts_included": any(
                item.source_excerpt for item in selected_files
            ),
            "omitted_categories": [
                "low_relevance_files"
            ] if omitted_candidates else [],
        }

        LOGGER.info(
            "Planning context built: candidates=%s selected=%s "
            "dependency_expanded=%s omitted=%s estimated_tokens=%s "
            "context_budget_tokens=%s num_ctx=%s num_predict=%s "
            "selection_seconds=%.3f",
            original_candidate_count,
            len(selected_files),
            len(expanded_keys),
            omitted_candidates,
            context_metadata["estimated_prompt_tokens"],
            context_budget_tokens,
            self.configuration.context_window,
            self.configuration.maximum_output_tokens,
            time.monotonic() - started_at,
        )

        return PlanningContext(
            repository_root=repository_root,
            repository_name=repository_name,
            analysis_id=analysis_id,
            request=normalized_request,
            selected_files=selected_files,
            repository_statistics=repository_statistics,
            environment=environment,
            warnings=warnings,
            generated_at=utc_now(),
            overview=overview,
            context_metadata=context_metadata,
            omitted_files=tuple(
                item.relative_path
                for item in context_candidates[
                    len(selected_files):len(selected_files) + 25
                ]
            ),
        )

    def build_system_prompt(self) -> str:
        """Build the deterministic system prompt for the planning model."""

        restrictions: list[str] = [
            "You are the planning engine of the LUMINA Code Builder.",
            "Produce an implementation plan only.",
            "Do not write complete source files.",
            "Do not execute commands.",
            "Do not claim that code was tested.",
            "Use only repository-relative file paths.",
            "Use forward slashes in every path.",
            "Never use absolute Windows or POSIX paths.",
            "Never use parent traversal such as ../.",
            "Never reference files outside the repository.",
            "Never request access to secrets, credentials, private keys, "
            "tokens, environment values, or protected files.",
            "Every proposed file change must have one of these operations: "
            "create, update, delete, rename.",
            "A rename operation must include destination_path.",
            "A create operation must target a path that does not already "
            "exist.",
            "An update or delete operation must target an existing path.",
            "Keep the plan incremental and implementation-ready.",
            "Identify validation and testing actions separately.",
            "Return only JSON matching the supplied schema.",
            _generated_change_plan_contract(),
        ]

        if not self.configuration.allow_new_files:
            restrictions.append(
                "Do not propose create operations."
            )

        if not self.configuration.allow_delete_operations:
            restrictions.append(
                "Do not propose delete operations."
            )

        if not self.configuration.allow_rename_operations:
            restrictions.append(
                "Do not propose rename operations."
            )

        if self.configuration.require_acceptance_criteria:
            restrictions.append(
                "Provide measurable acceptance criteria."
            )

        if self.configuration.require_test_plan:
            restrictions.append(
                "Provide a concrete test plan."
            )

        return "\n".join(
            f"{index}. {instruction}"
            for index, instruction in enumerate(
                restrictions,
                start=1,
            )
        )

    def build_user_prompt(
        self,
        context: PlanningContext,
    ) -> str:
        """Build a bounded user prompt containing repository context."""

        context_payload = context.to_dict()

        serialized_context = json.dumps(
            context_payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
            default=str,
        )

        serialized_context = _truncate_text(
            serialized_context,
            self.configuration.maximum_context_characters,
        )

        return (
            "Create a structured Change Plan for the following user "
            "request and repository analysis.\n\n"
            "USER REQUEST\n"
            "============\n"
            f"{context.request}\n\n"
            "REPOSITORY CONTEXT\n"
            "==================\n"
            f"{serialized_context}\n\n"
            "PLANNING REQUIREMENTS\n"
            "=====================\n"
            "- Reference only repository-relative paths contained in the "
            "repository context, except for legitimate new files.\n"
            "- Use operation=create only for new files.\n"
            "- Use operation=update only for existing files.\n"
            "- Use operation=delete only when deletion is necessary.\n"
            "- Use operation=rename only when destination_path is supplied.\n"
            "- Include dependencies between affected files.\n"
            "- Include affected symbols when they are known.\n"
            "- Include implementation notes but not full source code.\n"
            "- Include tests for every behavior-changing modification.\n"
            "- Include rollback actions for high-risk changes.\n"
            "- Keep step order sequential, starting at 1.\n"
            "- Return valid JSON only."
        )

    def build_ollama_options(self) -> dict[str, Any]:
        """Return deterministic Ollama generation options."""

        return {
            "temperature": self.configuration.temperature,
            "top_p": self.configuration.top_p,
            "num_ctx": self.configuration.context_window,
            "num_predict": (
                self.configuration.maximum_output_tokens
            ),
        }

    def get_output_schema(self) -> dict[str, Any]:
        """Return the JSON Schema requested from Ollama."""

        return GeneratedChangePlan.model_json_schema()

    def build_prompt_package(
        self,
        *,
        user_request: str,
        analysis: Any,
    ) -> dict[str, Any]:
        """Build the complete prompt package without calling Ollama."""

        context = self.build_context(
            user_request=user_request,
            analysis=analysis,
        )

        system_prompt = self.build_system_prompt()
        user_prompt = self.build_user_prompt(
            context
        )
        output_schema = self.get_output_schema()
        options = self.build_ollama_options()

        package = {
            "model": self.configuration.model,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "output_schema": output_schema,
            "options": options,
            "context": context.to_dict(),
        }

        package["prompt_hash"] = _stable_json_hash(
            package
        )

        return package
    async def _generate_raw_plan(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        repair_instruction: str | None = None,
        timeout_seconds: float | None = None,
    ) -> GeneratedChangePlan:
        """Request and validate a structured change plan from Ollama."""

        effective_prompt = user_prompt

        if repair_instruction is not None:
            normalized_repair_instruction = (
                repair_instruction.strip()
            )

            if normalized_repair_instruction:
                effective_prompt = (
                    f"{user_prompt.rstrip()}\n\n"
                    "PLAN REPAIR REQUIREMENTS\n"
                    "========================\n"
                    f"{normalized_repair_instruction}"
                )

        try:
            result = await self.ollama_service.generate_structured(
                model=self.configuration.model,
                prompt=effective_prompt,
                system_prompt=system_prompt,
                response_model=GeneratedChangePlan,
                options=self.build_ollama_options(),
                timeout_seconds=(
                    timeout_seconds
                    if timeout_seconds is not None
                    else self.configuration.timeout_seconds
                ),
                verify_model=(
                    self.configuration.verify_model_before_request
                ),
                include_schema_in_prompt=False,
                require_object=True,
            )
        except OllamaModelNotFoundError as exc:
            raise PlanningGenerationError(
                "The configured local Ollama planning model is not "
                f"installed: {self.configuration.model}"
            ) from exc
        except OllamaTimeoutError as exc:
            raise PlanningGenerationError(
                "The local Ollama planning model did not respond before "
                "the configured timeout."
            ) from exc
        except OllamaUnavailableError as exc:
            raise PlanningGenerationError(
                "The local Ollama service is not available."
            ) from exc
        except (
            OllamaStructuredOutputError,
            OllamaResponseValidationError,
        ) as exc:
            raise PlanningValidationError(
                "Ollama returned a change plan that did not match the "
                "required structured schema."
            ) from exc
        except OllamaConfigurationError as exc:
            raise PlanningConfigurationError(
                f"Invalid Ollama planning configuration: {exc}"
            ) from exc
        except OllamaServiceError as exc:
            raise PlanningGenerationError(
                f"Ollama could not generate the change plan: {exc}"
            ) from exc

        validated_model = result.validated_model

        if isinstance(validated_model, GeneratedChangePlan):
            return validated_model

        try:
            return GeneratedChangePlan.model_validate(
                result.data
            )
        except ValidationError as exc:
            raise PlanningValidationError(
                "The generated change plan failed final schema "
                "validation."
            ) from exc

    def _existing_repository_paths(
        self,
        analysis: Any,
    ) -> set[str]:
        """Return normalized repository-relative paths from analysis."""

        result: set[str] = set()

        for metadata in _analysis_files(analysis):
            relative_path_value = _get_attribute(
                metadata,
                "relative_path",
                "path",
                default=None,
            )

            if relative_path_value is None:
                continue

            try:
                normalized = _canonical_path_text(
                    str(relative_path_value)
                )
            except PlanningPathError:
                continue

            result.add(normalized.casefold())

        return result

    def _normalize_file_change(
        self,
        *,
        file_change: GeneratedFileChange,
        repository_root: Path,
        existing_paths: set[str],
    ) -> NormalizedFileChange:
        """Validate and normalize one model-generated file change."""

        operation = _normalize_operation(
            file_change.operation
        )

        if (
            operation == PlanningOperation.CREATE
            and not self.configuration.allow_new_files
        ):
            raise PlanningValidationError(
                "The generated plan proposes a create operation while "
                "new files are disabled."
            )

        if (
            operation == PlanningOperation.DELETE
            and not self.configuration.allow_delete_operations
        ):
            raise PlanningValidationError(
                "The generated plan proposes a delete operation while "
                "deletions are disabled."
            )

        if (
            operation == PlanningOperation.RENAME
            and not self.configuration.allow_rename_operations
        ):
            raise PlanningValidationError(
                "The generated plan proposes a rename operation while "
                "renames are disabled."
            )

        allow_nonexistent = (
            operation == PlanningOperation.CREATE
        )

        (
            normalized_path,
            resolved_path,
            path_exists,
            security_warning,
        ) = _normalize_repository_path(
            file_change.path,
            repository_root=repository_root,
            allow_nonexistent=allow_nonexistent,
            reject_protected=(
                self.configuration.reject_protected_paths
            ),
        )

        normalized_key = normalized_path.casefold()
        indexed_as_existing = normalized_key in existing_paths
        exists_in_repository = (
            path_exists or indexed_as_existing
        )

        warnings: list[str] = []

        if security_warning:
            warnings.append(security_warning)

        destination_path: str | None = None

        if operation == PlanningOperation.CREATE:
            if exists_in_repository:
                raise PlanningValidationError(
                    "Create operation targets an existing repository "
                    f"path: {normalized_path}"
                )

            if resolved_path.exists():
                raise PlanningValidationError(
                    "Create operation targets a path that already exists "
                    f"on disk: {normalized_path}"
                )

        elif operation in {
            PlanningOperation.UPDATE,
            PlanningOperation.DELETE,
            PlanningOperation.RENAME,
        }:
            if not exists_in_repository:
                raise PlanningValidationError(
                    f"{operation.value.capitalize()} operation targets a "
                    f"file that does not exist: {normalized_path}"
                )

        if operation == PlanningOperation.RENAME:
            if not file_change.destination_path:
                raise PlanningValidationError(
                    "Rename operation requires destination_path for "
                    f"{normalized_path}."
                )

            (
                normalized_destination,
                destination_resolved,
                destination_exists,
                destination_warning,
            ) = _normalize_repository_path(
                file_change.destination_path,
                repository_root=repository_root,
                allow_nonexistent=True,
                reject_protected=(
                    self.configuration.reject_protected_paths
                ),
            )

            destination_key = (
                normalized_destination.casefold()
            )

            if destination_key == normalized_key:
                raise PlanningValidationError(
                    "Rename source and destination paths are identical: "
                    f"{normalized_path}"
                )

            if (
                destination_exists
                or destination_key in existing_paths
                or destination_resolved.exists()
            ):
                raise PlanningValidationError(
                    "Rename destination already exists: "
                    f"{normalized_destination}"
                )

            destination_path = normalized_destination

            if destination_warning:
                warnings.append(destination_warning)

        elif file_change.destination_path:
            warnings.append(
                "destination_path was ignored because the operation is "
                f"{operation.value}: {normalized_path}"
            )

        risk_level = _normalize_risk_level(
            file_change.risk_level
        )

        if operation == PlanningOperation.DELETE:
            if risk_level == PlanningRiskLevel.LOW:
                risk_level = PlanningRiskLevel.MEDIUM

            warnings.append(
                f"Deletion requires explicit review: {normalized_path}"
            )

        if operation == PlanningOperation.RENAME:
            warnings.append(
                "Rename may require import, reference, and configuration "
                f"updates: {normalized_path}"
            )

        if file_change.breaking_change:
            warnings.append(
                f"File change is marked as breaking: {normalized_path}"
            )

        return NormalizedFileChange(
            path=normalized_path,
            operation=operation,
            destination_path=destination_path,
            summary=file_change.summary.strip(),
            rationale=file_change.rationale.strip(),
            implementation_notes=_normalize_string_list(
                file_change.implementation_notes,
                maximum_items=MAX_ACCEPTANCE_CRITERIA,
            ),
            affected_symbols=_normalize_string_list(
                file_change.affected_symbols,
                maximum_items=MAX_DEPENDENCIES,
                maximum_item_characters=2_000,
            ),
            dependencies=_normalize_string_list(
                file_change.dependencies,
                maximum_items=MAX_DEPENDENCIES,
                maximum_item_characters=MAX_PATH_CHARACTERS,
            ),
            tests=_normalize_string_list(
                file_change.tests,
                maximum_items=MAX_ACCEPTANCE_CRITERIA,
            ),
            risk_level=risk_level,
            breaking_change=file_change.breaking_change,
            exists_in_repository=exists_in_repository,
            warnings=_normalize_string_list(
                warnings,
                maximum_items=MAX_WARNINGS,
            ),
        )

    def _normalize_steps(
        self,
        *,
        steps: Sequence[GeneratedPlanStep],
        valid_paths: set[str],
    ) -> tuple[GeneratedPlanStep, ...]:
        """Validate, reorder, and normalize generated implementation steps."""

        if not steps:
            raise PlanningValidationError(
                "The change plan must contain at least one step."
            )

        sorted_steps = sorted(
            steps,
            key=lambda item: (
                item.order,
                item.title.casefold(),
            ),
        )

        normalized_steps: list[GeneratedPlanStep] = []
        old_to_new_order: dict[int, int] = {}

        for new_order, step in enumerate(
            sorted_steps,
            start=1,
        ):
            if step.order not in old_to_new_order:
                old_to_new_order[step.order] = new_order

        for new_order, step in enumerate(
            sorted_steps,
            start=1,
        ):
            normalized_paths: list[str] = []
            seen_paths: set[str] = set()

            for path_value in step.file_paths:
                try:
                    normalized_path = _canonical_path_text(
                        path_value
                    )
                except PlanningPathError as exc:
                    raise PlanningValidationError(
                        f"Step {new_order} contains an invalid path."
                    ) from exc

                path_key = normalized_path.casefold()

                if path_key not in valid_paths:
                    raise PlanningValidationError(
                        f"Step {new_order} references a file that is not "
                        "present in the plan: "
                        f"{normalized_path}"
                    )

                if path_key in seen_paths:
                    continue

                seen_paths.add(path_key)
                normalized_paths.append(normalized_path)

            normalized_dependencies: list[int] = []

            for dependency in step.depends_on:
                mapped_dependency = old_to_new_order.get(
                    dependency
                )

                if mapped_dependency is None:
                    raise PlanningValidationError(
                        f"Step {new_order} depends on unknown step "
                        f"{dependency}."
                    )

                if mapped_dependency >= new_order:
                    raise PlanningValidationError(
                        f"Step {new_order} has a forward or circular "
                        f"dependency on step {mapped_dependency}."
                    )

                if (
                    mapped_dependency
                    not in normalized_dependencies
                ):
                    normalized_dependencies.append(
                        mapped_dependency
                    )

            normalized_steps.append(
                GeneratedPlanStep(
                    order=new_order,
                    title=step.title.strip(),
                    description=step.description.strip(),
                    file_paths=normalized_paths,
                    depends_on=normalized_dependencies,
                    validation=list(
                        _normalize_string_list(
                            step.validation,
                            maximum_items=(
                                MAX_ACCEPTANCE_CRITERIA
                            ),
                        )
                    ),
                )
            )

        return tuple(normalized_steps)

    def _validate_dependency_paths(
        self,
        *,
        files: Sequence[NormalizedFileChange],
        repository_root: Path,
    ) -> tuple[NormalizedFileChange, ...]:
        """Normalize dependency paths when they refer to repository files."""

        normalized_results: list[NormalizedFileChange] = []

        planned_paths = {
            file_change.path.casefold()
            for file_change in files
        }

        planned_destinations = {
            file_change.destination_path.casefold()
            for file_change in files
            if file_change.destination_path is not None
        }

        for file_change in files:
            normalized_dependencies: list[str] = []
            warnings = list(file_change.warnings)

            for dependency in file_change.dependencies:
                dependency_text = dependency.strip()

                if not dependency_text:
                    continue

                resembles_path = (
                    "/" in dependency_text
                    or "\\" in dependency_text
                    or Path(dependency_text).suffix != ""
                )

                if not resembles_path:
                    normalized_dependencies.append(
                        dependency_text
                    )
                    continue

                try:
                    normalized_dependency = (
                        _canonical_path_text(
                            dependency_text
                        )
                    )
                except PlanningPathError:
                    warnings.append(
                        "Dependency could not be normalized as a path: "
                        f"{dependency_text}"
                    )
                    normalized_dependencies.append(
                        dependency_text
                    )
                    continue

                dependency_key = (
                    normalized_dependency.casefold()
                )

                dependency_absolute = (
                    repository_root
                    / Path(
                        *PurePosixPath(
                            normalized_dependency
                        ).parts
                    )
                )

                if (
                    dependency_key not in planned_paths
                    and dependency_key
                    not in planned_destinations
                    and not dependency_absolute.exists()
                ):
                    warnings.append(
                        "Dependency path was not found in the repository "
                        "or current plan: "
                        f"{normalized_dependency}"
                    )

                normalized_dependencies.append(
                    normalized_dependency
                )

            normalized_results.append(
                NormalizedFileChange(
                    path=file_change.path,
                    operation=file_change.operation,
                    destination_path=(
                        file_change.destination_path
                    ),
                    summary=file_change.summary,
                    rationale=file_change.rationale,
                    implementation_notes=(
                        file_change.implementation_notes
                    ),
                    affected_symbols=(
                        file_change.affected_symbols
                    ),
                    dependencies=_normalize_string_list(
                        normalized_dependencies,
                        maximum_items=MAX_DEPENDENCIES,
                        maximum_item_characters=(
                            MAX_PATH_CHARACTERS
                        ),
                    ),
                    tests=file_change.tests,
                    risk_level=file_change.risk_level,
                    breaking_change=(
                        file_change.breaking_change
                    ),
                    exists_in_repository=(
                        file_change.exists_in_repository
                    ),
                    warnings=_normalize_string_list(
                        warnings,
                        maximum_items=MAX_WARNINGS,
                    ),
                )
            )

        return tuple(normalized_results)

    def normalize_generated_plan(
        self,
        *,
        generated_plan: GeneratedChangePlan,
        user_request: str,
        analysis: Any,
        generation_duration_seconds: float,
        repaired: bool,
        task_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> NormalizedChangePlan:
        """Validate and normalize a generated plan against the repository."""

        repository_root = _resolve_repository_root(
            analysis
        )

        repository_name = str(
            _get_attribute(
                analysis,
                "repository_name",
                "name",
                default=repository_root.name,
            )
            or repository_root.name
            or "repository"
        )

        analysis_id_value = _get_attribute(
            analysis,
            "analysis_id",
            "id",
            default=None,
        )

        analysis_id = (
            str(analysis_id_value)
            if analysis_id_value is not None
            else None
        )

        normalized_request = _normalize_request_text(
            user_request,
            maximum_characters=(
                self.configuration
                .maximum_user_request_characters
            ),
        )

        existing_paths = self._existing_repository_paths(
            analysis
        )

        normalized_files: list[
            NormalizedFileChange
        ] = []

        seen_source_paths: set[str] = set()
        seen_destination_paths: set[str] = set()

        for generated_file in generated_plan.files:
            normalized_file = self._normalize_file_change(
                file_change=generated_file,
                repository_root=repository_root,
                existing_paths=existing_paths,
            )

            source_key = normalized_file.path.casefold()

            if source_key in seen_source_paths:
                raise PlanningValidationError(
                    "The generated plan contains duplicate operations for "
                    f"the same path: {normalized_file.path}"
                )

            if source_key in seen_destination_paths:
                raise PlanningValidationError(
                    "A generated source path conflicts with an earlier "
                    "rename destination: "
                    f"{normalized_file.path}"
                )

            seen_source_paths.add(source_key)

            if normalized_file.destination_path is not None:
                destination_key = (
                    normalized_file.destination_path.casefold()
                )

                if (
                    destination_key in seen_source_paths
                    or destination_key in seen_destination_paths
                ):
                    raise PlanningValidationError(
                        "The generated plan contains a conflicting rename "
                        "destination: "
                        f"{normalized_file.destination_path}"
                    )

                seen_destination_paths.add(
                    destination_key
                )

            normalized_files.append(
                normalized_file
            )

        if not normalized_files:
            raise PlanningValidationError(
                "The generated plan does not contain any file changes."
            )

        validated_files = self._validate_dependency_paths(
            files=normalized_files,
            repository_root=repository_root,
        )

        valid_step_paths = {
            file_change.path.casefold()
            for file_change in validated_files
        }

        valid_step_paths.update(
            file_change.destination_path.casefold()
            for file_change in validated_files
            if file_change.destination_path is not None
        )

        normalized_steps = self._normalize_steps(
            steps=generated_plan.steps,
            valid_paths=valid_step_paths,
        )

        acceptance_criteria = _normalize_string_list(
            generated_plan.acceptance_criteria,
            maximum_items=MAX_ACCEPTANCE_CRITERIA,
        )

        test_plan = _normalize_string_list(
            generated_plan.test_plan,
            maximum_items=MAX_ACCEPTANCE_CRITERIA,
        )

        rollback_plan = _normalize_string_list(
            generated_plan.rollback_plan,
            maximum_items=MAX_ACCEPTANCE_CRITERIA,
        )

        if (
            self.configuration.require_acceptance_criteria
            and not acceptance_criteria
        ):
            raise PlanningValidationError(
                "The generated plan does not contain acceptance criteria."
            )

        if (
            self.configuration.require_test_plan
            and not test_plan
        ):
            raise PlanningValidationError(
                "The generated plan does not contain a test plan."
            )

        warnings: list[str] = list(
            _normalize_string_list(
                generated_plan.warnings,
                maximum_items=MAX_WARNINGS,
            )
        )

        for normalized_file in validated_files:
            warnings.extend(normalized_file.warnings)

        calculated_risk = _normalize_risk_level(
            generated_plan.risk_level
        )

        file_risk_order = {
            PlanningRiskLevel.LOW: 1,
            PlanningRiskLevel.MEDIUM: 2,
            PlanningRiskLevel.HIGH: 3,
            PlanningRiskLevel.CRITICAL: 4,
        }

        highest_file_risk = max(
            (
                file_change.risk_level
                for file_change in validated_files
            ),
            key=lambda risk: file_risk_order[risk],
        )

        if (
            file_risk_order[highest_file_risk]
            > file_risk_order[calculated_risk]
        ):
            calculated_risk = highest_file_risk
            warnings.append(
                "Overall risk level was raised to match the highest-risk "
                "file change."
            )

        contains_delete = any(
            file_change.operation
            == PlanningOperation.DELETE
            for file_change in validated_files
        )

        contains_breaking_file = any(
            file_change.breaking_change
            for file_change in validated_files
        )

        breaking_changes = (
            generated_plan.breaking_changes
            or contains_breaking_file
        )

        if contains_delete and not rollback_plan:
            warnings.append(
                "The plan contains file deletion but no explicit rollback "
                "instructions."
            )

        if (
            calculated_risk
            in {
                PlanningRiskLevel.HIGH,
                PlanningRiskLevel.CRITICAL,
            }
            and not rollback_plan
        ):
            warnings.append(
                "High-risk plan does not include a rollback plan."
            )

        required_user_actions = _normalize_string_list(
            generated_plan.required_user_actions,
            maximum_items=MAX_WARNINGS,
        )

        requires_user_action = (
            generated_plan.requires_user_action
            or bool(required_user_actions)
        )

        if (
            generated_plan.requires_user_action
            and not required_user_actions
        ):
            warnings.append(
                "The plan indicates that user action is required but does "
                "not specify the required actions."
            )

        assumptions = _normalize_string_list(
            generated_plan.assumptions,
            maximum_items=MAX_WARNINGS,
        )

        return NormalizedChangePlan(
            plan_id=uuid4(),
            task_id=(
                str(task_id)
                if task_id is not None
                else None
            ),
            title=generated_plan.title.strip(),
            summary=generated_plan.summary.strip(),
            objective=generated_plan.objective.strip(),
            user_request=normalized_request,
            repository_root=str(repository_root),
            repository_name=repository_name,
            analysis_id=analysis_id,
            model=self.configuration.model,
            risk_level=calculated_risk,
            breaking_changes=breaking_changes,
            requires_user_action=requires_user_action,
            required_user_actions=required_user_actions,
            assumptions=assumptions,
            files=validated_files,
            steps=normalized_steps,
            acceptance_criteria=acceptance_criteria,
            test_plan=test_plan,
            rollback_plan=rollback_plan,
            warnings=_normalize_string_list(
                warnings,
                maximum_items=MAX_WARNINGS,
            ),
            created_at=utc_now(),
            generation_duration_seconds=max(
                float(generation_duration_seconds),
                0.0,
            ),
            repaired=repaired,
        )

    def _build_repair_instruction(
        self,
        *,
        error: Exception,
    ) -> str:
        """Build a bounded repair instruction from a validation failure."""

        error_text = _format_validation_error_details(error)

        if not error_text:
            error_text = error.__class__.__name__

        error_text = _truncate_text(
            error_text,
            8_000,
        )

        return (
            "The previous response was rejected by the deterministic plan "
            "validator.\n"
            "Generate the complete plan again from the original request.\n"
            "Correct every issue described below.\n"
            "Do not mention the previous response.\n"
            "Return only a complete JSON object matching the schema.\n\n"
            "VALIDATION ERROR\n"
            "----------------\n"
            f"{error_text}\n\n"
            "MANDATORY REPAIR RULES\n"
            "----------------------\n"
            "- Use repository-relative paths with forward slashes.\n"
            "- Do not use absolute paths or parent traversal.\n"
            "- create must target a non-existing path.\n"
            "- update, delete, and rename must target existing paths.\n"
            "- rename must provide a unique non-existing "
            "destination_path.\n"
            "- Do not duplicate file operations.\n"
            "- Every step path must appear in the files collection.\n"
            "- Step order must begin at 1 and dependencies may reference "
            "only earlier steps.\n"
            "- Include acceptance criteria and a concrete test plan.\n\n"
            "REQUIRED STRUCTURE\n"
            "------------------\n"
            f"{_generated_change_plan_contract()}"
        )

    async def create_normalized_change_plan(
        self,
        *,
        user_request: str,
        analysis: Any,
        task_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> NormalizedChangePlan:
        """Generate a repository-aware normalized change plan."""

        context = self.build_context(
            user_request=user_request,
            analysis=analysis,
        )

        system_prompt = self.build_system_prompt()
        user_prompt = self.build_user_prompt(
            context
        )

        started_at = time.monotonic()
        repair_instruction: str | None = None
        final_error: Exception | None = None

        maximum_attempts = (
            self.configuration.maximum_repair_attempts + 1
        )

        for attempt_index in range(maximum_attempts):
            repaired = attempt_index > 0

            try:
                generated_plan = await self._generate_raw_plan(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    repair_instruction=repair_instruction,
                    timeout_seconds=timeout_seconds,
                )

                duration = time.monotonic() - started_at

                return self.normalize_generated_plan(
                    generated_plan=generated_plan,
                    user_request=context.request,
                    analysis=analysis,
                    task_id=task_id,
                    generation_duration_seconds=duration,
                    repaired=repaired,
                )

            except (
                PlanningValidationError,
                PlanningPathError,
            ) as exc:
                final_error = exc

                if attempt_index + 1 >= maximum_attempts:
                    break

                LOGGER.warning(
                    "Generated change plan failed validation; requesting "
                    "repair attempt %s of %s: %s",
                    attempt_index + 1,
                    self.configuration.maximum_repair_attempts,
                    exc,
                )

                repair_instruction = (
                    self._build_repair_instruction(
                        error=exc
                    )
                )

        if final_error is not None:
            raise PlanningValidationError(
                "Ollama could not produce a valid repository change plan "
                "after all permitted repair attempts."
            ) from final_error

        raise PlanningGenerationError(
            "Change-plan generation ended without producing a result."
        )

    def validate_change_plan(
        self,
        *,
        plan: GeneratedChangePlan | Mapping[str, Any],
        user_request: str,
        analysis: Any,
        task_id: str | None = None,
    ) -> NormalizedChangePlan:
        """Validate an externally supplied generated plan without Ollama."""

        if isinstance(plan, GeneratedChangePlan):
            generated_plan = plan
        else:
            try:
                generated_plan = (
                    GeneratedChangePlan.model_validate(
                        plan
                    )
                )
            except ValidationError as exc:
                raise PlanningValidationError(
                    "The supplied change plan does not match the required "
                    "schema."
                ) from exc

        return self.normalize_generated_plan(
            generated_plan=generated_plan,
            user_request=user_request,
            analysis=analysis,
            task_id=task_id,
            generation_duration_seconds=0.0,
            repaired=False,
        )

    @staticmethod
    def _find_model_class(
        candidate_names: Sequence[str],
    ) -> type[BaseModel] | None:
        """Return the first compatible Pydantic model from models.py."""

        for model_name in candidate_names:
            candidate = getattr(
                code_builder_models,
                model_name,
                None,
            )

            if (
                isinstance(candidate, type)
                and issubclass(candidate, BaseModel)
            ):
                return candidate

        return None

    @staticmethod
    def _field_names(
        model_class: type[BaseModel],
    ) -> set[str]:
        """Return declared Pydantic field names for a model class."""

        model_fields = getattr(
            model_class,
            "model_fields",
            {},
        )

        return set(model_fields.keys())

    @classmethod
    def _filter_model_payload(
        cls,
        *,
        model_class: type[BaseModel],
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Filter a payload to fields accepted by a Pydantic model."""

        field_names = cls._field_names(
            model_class
        )

        if not field_names:
            return dict(payload)

        return {
            key: value
            for key, value in payload.items()
            if key in field_names
        }

    @classmethod
    def _validate_compatible_model(
        cls,
        *,
        model_class: type[BaseModel],
        payload: Mapping[str, Any],
        model_description: str,
    ) -> BaseModel:
        """Validate a payload against a compatible models.py class."""

        filtered_payload = cls._filter_model_payload(
            model_class=model_class,
            payload=payload,
        )

        try:
            return model_class.model_validate(
                filtered_payload
            )
        except ValidationError as exc:
            raise PlanningModelCompatibilityError(
                f"The {model_description} model in models.py is not "
                "compatible with the normalized planning payload."
            ) from exc

    @classmethod
    def _convert_file_changes_for_model(
        cls,
        *,
        files: Sequence[NormalizedFileChange],
    ) -> list[Any]:
        """Convert normalized file changes to models.py file-change models."""

        file_model_class = cls._find_model_class(
            FILE_CHANGE_MODEL_NAME_CANDIDATES
        )

        results: list[Any] = []

        for index, file_change in enumerate(
            files,
            start=1,
        ):
            domain_change_type = (
                "modify"
                if file_change.operation == PlanningOperation.UPDATE
                else file_change.operation.value
            )

            previous_path = (
                file_change.path
                if file_change.operation == PlanningOperation.RENAME
                else None
            )

            old_content = None
            new_content = None

            if file_change.operation == PlanningOperation.CREATE:
                new_content = ""
            elif file_change.operation == PlanningOperation.UPDATE:
                old_content = ""
                new_content = ""
            elif file_change.operation == PlanningOperation.DELETE:
                old_content = ""
            elif file_change.operation == PlanningOperation.RENAME:
                new_content = ""

            payload: dict[str, Any] = {
                "id": str(uuid4()),
                "change_id": str(uuid4()),
                "order": index,
                "path": file_change.path,
                "file_path": file_change.path,
                "relative_path": file_change.path,
                "operation": file_change.operation.value,
                "change_type": domain_change_type,
                "destination_path": (
                    file_change.destination_path
                ),
                "new_path": file_change.destination_path,
                "previous_path": previous_path,
                "old_content": old_content,
                "new_content": new_content,
                "summary": file_change.summary,
                "description": file_change.summary,
                "rationale": file_change.rationale,
                "reason": file_change.rationale,
                "implementation_notes": list(
                    file_change.implementation_notes
                ),
                "notes": list(
                    file_change.implementation_notes
                ),
                "affected_symbols": list(
                    file_change.affected_symbols
                ),
                "symbols": list(
                    file_change.affected_symbols
                ),
                "dependencies": list(
                    file_change.dependencies
                ),
                "tests": list(file_change.tests),
                "test_requirements": list(
                    file_change.tests
                ),
                "risk_level": file_change.risk_level.value,
                "risk": file_change.risk_level.value,
                "breaking_change": (
                    file_change.breaking_change
                ),
                "is_breaking": (
                    file_change.breaking_change
                ),
                "exists_in_repository": (
                    file_change.exists_in_repository
                ),
                "warnings": list(file_change.warnings),
            }

            if file_model_class is None:
                results.append(
                    file_change.to_dict()
                )
                continue

            results.append(
                cls._validate_compatible_model(
                    model_class=file_model_class,
                    payload=payload,
                    model_description=(
                        "planned file-change"
                    ),
                )
            )

        return results

    @classmethod
    def _convert_steps_for_model(
        cls,
        *,
        steps: Sequence[GeneratedPlanStep],
    ) -> list[Any]:
        """Convert normalized steps to models.py step models."""

        step_model_class = cls._find_model_class(
            PLAN_STEP_MODEL_NAME_CANDIDATES
        )

        results: list[Any] = []

        for step in steps:
            payload: dict[str, Any] = {
                "id": str(uuid4()),
                "step_id": str(uuid4()),
                "order": step.order,
                "index": step.order,
                "sequence": step.order,
                "title": step.title,
                "name": step.title,
                "description": step.description,
                "details": step.description,
                "file_paths": list(step.file_paths),
                "files": list(step.file_paths),
                "depends_on": list(step.depends_on),
                "dependencies": list(step.depends_on),
                "validation": list(step.validation),
                "validation_steps": list(
                    step.validation
                ),
            }

            if step_model_class is None:
                results.append(
                    step.model_dump(mode="json")
                )
                continue

            results.append(
                cls._validate_compatible_model(
                    model_class=step_model_class,
                    payload=payload,
                    model_description="change-plan step",
                )
            )

        return results

    @classmethod
    def to_change_plan_model(
        cls,
        normalized_plan: NormalizedChangePlan,
    ) -> BaseModel:
        """Convert a normalized plan to the ChangePlan model in models.py."""

        plan_model_class = cls._find_model_class(
            MODEL_NAME_CANDIDATES
        )

        if plan_model_class is None:
            raise PlanningModelCompatibilityError(
                "models.py does not expose a compatible ChangePlan model. "
                "Expected one of: "
                + ", ".join(MODEL_NAME_CANDIDATES)
            )

        converted_files = (
            cls._convert_file_changes_for_model(
                files=normalized_plan.files
            )
        )

        converted_steps = (
            cls._convert_steps_for_model(
                steps=normalized_plan.steps
            )
        )

        payload: dict[str, Any] = {
            "id": str(normalized_plan.plan_id),
            "plan_id": str(normalized_plan.plan_id),
            "task_id": normalized_plan.task_id,
            "title": normalized_plan.title,
            "name": normalized_plan.title,
            "summary": normalized_plan.summary,
            "description": normalized_plan.summary,
            "objective": normalized_plan.objective,
            "user_request": normalized_plan.user_request,
            "request": normalized_plan.user_request,
            "repository_root": (
                normalized_plan.repository_root
            ),
            "repository_name": (
                normalized_plan.repository_name
            ),
            "analysis_id": normalized_plan.analysis_id,
            "model": normalized_plan.model,
            "model_name": normalized_plan.model,
            "risk_level": normalized_plan.risk_level.value,
            "risk": normalized_plan.risk_level.value,
            "breaking_changes": (
                normalized_plan.breaking_changes
            ),
            "has_breaking_changes": (
                normalized_plan.breaking_changes
            ),
            "requires_user_action": (
                normalized_plan.requires_user_action
            ),
            "required_user_actions": list(
                normalized_plan.required_user_actions
            ),
            "assumptions": list(
                normalized_plan.assumptions
            ),
            "files": converted_files,
            "file_changes": converted_files,
            "changes": converted_files,
            "steps": converted_steps,
            "plan_steps": converted_steps,
            "acceptance_criteria": list(
                normalized_plan.acceptance_criteria
            ),
            "test_plan": list(
                normalized_plan.test_plan
            ),
            "tests": list(normalized_plan.test_plan),
            "rollback_plan": list(
                normalized_plan.rollback_plan
            ),
            "warnings": list(
                normalized_plan.warnings
            ),
            "created_at": normalized_plan.created_at,
            "generated_at": normalized_plan.created_at,
            "generation_duration_seconds": (
                normalized_plan
                .generation_duration_seconds
            ),
            "duration_seconds": (
                normalized_plan
                .generation_duration_seconds
            ),
            "repaired": normalized_plan.repaired,
            "was_repaired": normalized_plan.repaired,
            "status": "planned",
        }

        return cls._validate_compatible_model(
            model_class=plan_model_class,
            payload=payload,
            model_description="ChangePlan",
        )

    async def create_change_plan(
        self,
        *,
        user_request: str,
        analysis: Any,
        task_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> BaseModel:
        """Generate and return the ChangePlan model defined in models.py."""

        normalized_plan = (
            await self.create_normalized_change_plan(
                user_request=user_request,
                analysis=analysis,
                task_id=task_id,
                timeout_seconds=timeout_seconds,
            )
        )

        return self.to_change_plan_model(
            normalized_plan
        )

    async def plan(
        self,
        *,
        user_request: str,
        analysis: Any,
        task_id: str | None = None,
        timeout_seconds: float | None = None,
        return_normalized: bool = False,
    ) -> BaseModel | NormalizedChangePlan:
        """Public shorthand for creating a repository change plan."""

        normalized_plan = (
            await self.create_normalized_change_plan(
                user_request=user_request,
                analysis=analysis,
                task_id=task_id,
                timeout_seconds=timeout_seconds,
            )
        )

        if return_normalized:
            return normalized_plan

        return self.to_change_plan_model(
            normalized_plan
        )


def create_planning_service(
    *,
    ollama_service: OllamaService,
    model: str = DEFAULT_PLANNING_MODEL,
    maximum_context_files: int = (
        DEFAULT_MAX_CONTEXT_FILES
    ),
    maximum_context_characters: int = (
        DEFAULT_MAX_CONTEXT_CHARACTERS
    ),
    maximum_file_summary_characters: int = (
        DEFAULT_MAX_FILE_SUMMARY_CHARACTERS
    ),
    maximum_user_request_characters: int = (
        DEFAULT_MAX_USER_REQUEST_CHARACTERS
    ),
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    maximum_repair_attempts: int = (
        DEFAULT_MAX_PLAN_REPAIR_ATTEMPTS
    ),
    temperature: float = DEFAULT_TEMPERATURE,
    top_p: float = DEFAULT_TOP_P,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
    maximum_output_tokens: int = (
        DEFAULT_MAX_OUTPUT_TOKENS
    ),
    input_token_safety_margin: int = DEFAULT_INPUT_TOKEN_SAFETY_MARGIN,
    fixed_prompt_overhead_tokens: int = (
        DEFAULT_FIXED_PROMPT_OVERHEAD_TOKENS
    ),
    maximum_context_input_tokens: int = (
        DEFAULT_MAX_CONTEXT_INPUT_TOKENS
    ),
    verify_model_before_request: bool = False,
    allow_new_files: bool = True,
    allow_delete_operations: bool = True,
    allow_rename_operations: bool = True,
    require_acceptance_criteria: bool = True,
    require_test_plan: bool = True,
    reject_protected_paths: bool = True,
) -> PlanningService:
    """Create a configured PlanningService instance."""

    configuration = PlanningConfiguration(
        model=model,
        maximum_context_files=maximum_context_files,
        maximum_context_characters=(
            maximum_context_characters
        ),
        maximum_file_summary_characters=(
            maximum_file_summary_characters
        ),
        maximum_user_request_characters=(
            maximum_user_request_characters
        ),
        timeout_seconds=timeout_seconds,
        maximum_repair_attempts=(
            maximum_repair_attempts
        ),
        temperature=temperature,
        top_p=top_p,
        context_window=context_window,
        maximum_output_tokens=(
            maximum_output_tokens
        ),
        input_token_safety_margin=input_token_safety_margin,
        fixed_prompt_overhead_tokens=(
            fixed_prompt_overhead_tokens
        ),
        maximum_context_input_tokens=(
            maximum_context_input_tokens
        ),
        verify_model_before_request=(
            verify_model_before_request
        ),
        allow_new_files=allow_new_files,
        allow_delete_operations=(
            allow_delete_operations
        ),
        allow_rename_operations=(
            allow_rename_operations
        ),
        require_acceptance_criteria=(
            require_acceptance_criteria
        ),
        require_test_plan=require_test_plan,
        reject_protected_paths=(
            reject_protected_paths
        ),
    )

    return PlanningService(
        ollama_service=ollama_service,
        configuration=configuration,
    )


async def create_repository_change_plan(
    *,
    ollama_service: OllamaService,
    user_request: str,
    analysis: Any,
    task_id: str | None = None,
    configuration: PlanningConfiguration | None = None,
) -> BaseModel:
    """Generate one ChangePlan model from repository analysis."""

    service = PlanningService(
        ollama_service=ollama_service,
        configuration=configuration,
    )

    return await service.create_change_plan(
        user_request=user_request,
        analysis=analysis,
        task_id=task_id,
    )


async def create_normalized_repository_change_plan(
    *,
    ollama_service: OllamaService,
    user_request: str,
    analysis: Any,
    task_id: str | None = None,
    configuration: PlanningConfiguration | None = None,
) -> NormalizedChangePlan:
    """Generate one normalized repository change plan."""

    service = PlanningService(
        ollama_service=ollama_service,
        configuration=configuration,
    )

    return await service.create_normalized_change_plan(
        user_request=user_request,
        analysis=analysis,
        task_id=task_id,
    )


def validate_repository_change_plan(
    *,
    ollama_service: OllamaService,
    plan: GeneratedChangePlan | Mapping[str, Any],
    user_request: str,
    analysis: Any,
    task_id: str | None = None,
    configuration: PlanningConfiguration | None = None,
) -> NormalizedChangePlan:
    """Validate a supplied plan against repository analysis."""

    service = PlanningService(
        ollama_service=ollama_service,
        configuration=configuration,
    )

    return service.validate_change_plan(
        plan=plan,
        user_request=user_request,
        analysis=analysis,
        task_id=task_id,
    )


__all__ = [
    "DEFAULT_CONTEXT_WINDOW",
    "DEFAULT_MAX_CONTEXT_CHARACTERS",
    "DEFAULT_MAX_CONTEXT_FILES",
    "DEFAULT_MAX_FILE_SUMMARY_CHARACTERS",
    "DEFAULT_MAX_OUTPUT_TOKENS",
    "DEFAULT_MAX_PLAN_REPAIR_ATTEMPTS",
    "DEFAULT_MAX_USER_REQUEST_CHARACTERS",
    "DEFAULT_PLANNING_MODEL",
    "DEFAULT_TEMPERATURE",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_TOP_P",
    "GeneratedChangePlan",
    "GeneratedFileChange",
    "GeneratedPlanStep",
    "NormalizedChangePlan",
    "NormalizedFileChange",
    "PlanningConfiguration",
    "PlanningConfigurationError",
    "PlanningContext",
    "PlanningContextError",
    "PlanningContextFile",
    "PlanningGenerationError",
    "PlanningModelCompatibilityError",
    "PlanningOperation",
    "PlanningPathError",
    "PlanningRequestError",
    "PlanningRiskLevel",
    "PlanningService",
    "PlanningServiceError",
    "PlanningValidationError",
    "create_normalized_repository_change_plan",
    "create_planning_service",
    "create_repository_change_plan",
    "validate_repository_change_plan",
]
