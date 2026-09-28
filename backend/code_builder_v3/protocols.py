"""V3 Protocol Definitions - Core interfaces for Lumina Code Builder V3.

These protocols define the contracts that all V3 components must implement.
V2 components are adapted to these protocols via V2Adapter.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Optional, Protocol
from uuid import uuid4


# ============================================================
# Core Data Models
# ============================================================

class TaskStatus(str, Enum):
    queued = "queued"
    planning = "planning"
    awaiting_approval = "awaiting_approval"
    executing = "executing"
    validating = "validating"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    rolled_back = "rolled_back"


class ModelStrength(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    STRONG = "strong"
    REASONING = "reasoning"


class Capability(str, Enum):
    JSON_SCHEMA = "json_schema"
    TOOL_CALLING = "tool_calling"
    STREAMING = "streaming"
    LARGE_CONTEXT = "large_context"


class TaskType(str, Enum):
    PLANNING = "planning"
    CODING = "coding"
    DEBUGGING = "debugging
    ANALYSIS = "analysis"
    SIMPLE_EDIT = "simple_edit"


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    json_schema: bool = False
    tool_calling: bool = False
    streaming: bool = False
    max_context: int = 4096
    max_output: int = 4096
    supports_system_prompt: bool = True
    rate_limit_rpm: int | None = None
    rate_limit_tpm: int | None = None


@dataclass(frozen=True, slots=True)
class ModelInfo:
    id: str
    provider: str
    capabilities: ProviderCapabilities
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    strength: ModelStrength = ModelStrength.BALANCED
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ModelSelection:
    provider_name: str
    model_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class TaskRequest:
    prompt: str
    model: str | None = None
    auto_apply: bool = False
    autonomous: bool = False
    max_attempts: int = 3
    timeout_seconds: int = 300


@dataclass(frozen=True, slots=True)
class PlannedChange:
    path: str
    operation: str  # create | modify | delete
    reason: str


@dataclass(frozen=True, slots=True)
class ChangePlan:
    summary: str
    changes: list[PlannedChange] = field(default_factory=list)
    validation_commands: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ProposedFileChange:
    path: str
    operation: str
    content: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    backup_id: str
    changed_paths: list[str] = field(default_factory=list)
    validation_commands: list[str] = field(default_factory=list)
    attempts: int = 1
    autonomous: bool = False


@dataclass(frozen=True, slots=True)
class TaskEvent:
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    phase: TaskStatus = TaskStatus.queued
    message: str = ""


@dataclass(slots=True)
class BuildTask:
    id: str = field(default_factory=lambda: str(uuid4()))
    request: TaskRequest = field(default_factory=TaskRequest)
    status: TaskStatus = TaskStatus.queued
    plan: ChangePlan | None = None
    execution: ExecutionReport | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    events: list[TaskEvent] = field(default_factory=list)

    def transition(self, status: TaskStatus, message: str) -> None:
        self.status = status
        self.updated_at = datetime.now(timezone.utc)
        self.events.append(TaskEvent(phase=status, message=message))


# ============================================================
# Provider Protocols
# ============================================================

class Provider(Protocol):
    """Base protocol for all AI model providers."""
    
    @property
    def name(self) -> str: ...
    
    def capabilities(self) -> ProviderCapabilities: ...
    
    def models(self) -> list[ModelInfo]: ...
    
    async def generate_json(
        self,
        prompt: str,
        schema: dict,
        model: str | None = None,
        stream: bool = False,
    ) -> AsyncIterator[dict] | dict: ...
    
    async def generate_text(
        self,
        prompt: str,
        model: str | None = None,
        stream: bool = False,
    ) -> AsyncIterator[str] | str: ...


class ModelRouter(Protocol):
    """Routes tasks to appropriate providers/models based on capabilities."""
    
    def select_model(
        self,
        task_type: TaskType,
        complexity: str,  # simple, moderate, complex
        required_capabilities: list[Capability],
        context_size: int,
        available_providers: list[Provider],
    ) -> ModelSelection: ...
    
    def get_provider(self, name: str) -> Provider | None: ...
    
    def list_providers(self) -> list[Provider]: ...


# ============================================================
# Planning Protocols
# ============================================================

class ProjectPlanner(Protocol):
    """Creates structured execution plans from natural language requests."""
    
    async def create_plan(self, request: TaskRequest) -> ChangePlan: ...
    
    async def decompose(self, request: TaskRequest) -> list[TaskRequest]: ...


class RequestAnalyzer(Protocol):
    """Analyzes natural language requests to understand intent and scope."""
    
    async def analyze(self, prompt: str) -> dict[str, Any]: ...
    
    async def classify(self, prompt: str) -> dict[str, Any]: ...
    
    async def estimate_complexity(self, prompt: str) -> str: ...


# ============================================================
# Generation Protocols
# ============================================================

class StreamingGenerator(Protocol):
    """Generates file changes incrementally as an async stream."""
    
    async def generate(
        self,
        request: TaskRequest,
        plan: ChangePlan,
        file_context: dict[str, str],
    ) -> AsyncIterator[ProposedFileChange]: ...


class ContextEngine(Protocol):
    """Retrieves targeted context for generation tasks."""
    
    async def retrieve(
        self,
        query: str,
        task_type: TaskType,
        max_tokens: int,
        project_index: "ProjectIndex",
    ) -> "ContextBundle": ...


@dataclass(frozen=True, slots=True)
class ContextBundle:
    files: dict[str, str] = field(default_factory=dict)
    symbols: list[Any] = field(default_factory=list)
    dependencies: list[Any] = field(default_factory=list)
    patterns: list[Any] = field(default_factory=list)
    token_estimate: int = 0


# ============================================================
# Repository Intelligence Protocols
# ============================================================

class ProjectIndexer(Protocol):
    """Builds and maintains a searchable index of the repository."""
    
    async def index(self, repo_root: Path) -> "ProjectIndex": ...
    
    async def update(self, changed_files: list[Path]) -> None: ...
    
    async def get_index(self) -> "ProjectIndex": ...


@dataclass(frozen=True, slots=True)
class ProjectIndex:
    structure: dict[str, Any] = field(default_factory=dict)
    dependencies: dict[str, Any] = field(default_factory=dict)
    symbols: dict[str, Any] = field(default_factory=dict)
    frameworks: list[str] = field(default_factory=list)
    patterns: dict[str, Any] = field(default_factory=dict)
    configs: dict[str, Any] = field(default_factory=dict)


# ============================================================
# Execution Protocols
# ============================================================

class BuildOrchestrator(Protocol):
    """Orchestrates the multi-stage build pipeline."""
    
    async def execute(
        self,
        request: TaskRequest,
        plan: ChangePlan,
        progress_callback: Optional[callable] = None,
    ) -> ExecutionReport: ...


class SandboxRuntime(Protocol):
    """Abstract sandbox runtime for isolated command execution."""
    
    async def create_session(self, workspace_root: Path, env: Optional[dict[str, str]] = None) -> "SandboxSession": ...
    
    async def run_command(
        self,
        session: "SandboxSession",
        command: str,
        timeout_seconds: int = 120,
        workdir: Optional[str] = None,
    ) -> "CommandResult": ...
    
    async def read_file(self, session: "SandboxSession", path: str) -> str: ...
    
    async def write_file(self, session: "SandboxSession", path: str, content: str) -> None: ...
    
    async def list_files(self, session: "SandboxSession", path: str = ".") -> list[str]: ...
    
    async def close_session(self, session: "SandboxSession") -> None: ...
    
    async def get_preview_url(self, session: "SandboxSession", port: int) -> str: ...


@dataclass(frozen=True, slots=True)
class SandboxSession:
    session_id: str
    workspace_root: Path
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float


class DependencyManager(Protocol):
    """Manages project dependencies across ecosystems."""
    
    async def detect(self, repo_root: Path) -> dict[str, Any]: ...
    
    async def install(self, repo_root: Path, packages: list[str]) -> CommandResult: ...
    
    async def update_config(self, repo_root: Path, changes: dict[str, Any]) -> None: ...
    
    async def diagnose_failure(self, result: CommandResult) -> list[str]: ...


class PreviewManager(Protocol):
    """Manages running application previews."""
    
    async def start_preview(self, repo_root: Path, config: dict[str, Any]) -> str: ...
    
    async def stop_preview(self, preview_id: str) -> None: ...
    
    async def get_status(self, preview_id: str) -> dict[str, Any]: ...


# ============================================================
# Verification Protocols
# ============================================================

class BrowserVerifier(Protocol):
    """Verifies applications in a real browser."""
    
    async def verify(
        self,
        url: str,
        workflow: "VerificationWorkflow",
        evidence_collector: "EvidenceCollector",
    ) -> "VerificationResult": ...


@dataclass(frozen=True, slots=True)
class VerificationWorkflow:
    name: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class VerificationResult:
    passed: bool
    evidence: "BrowserEvidence"
    workflow_results: dict[str, bool] = field(default_factory=dict)
    duration_seconds: float = 0.0
    error_message: str = ""


@dataclass(frozen=True, slots=True)
class BrowserEvidence:
    console_errors: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    network_errors: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    page_title: str = ""
    page_url: str = ""
    viewport: dict = field(default_factory=dict)
    
    def has_critical_errors(self) -> bool:
        return bool(self.console_errors or self.page_errors or self.network_errors)


class EvidenceCollector(Protocol):
    """Collects unified evidence from all verification sources."""
    
    async def collect_build_evidence(self, result: CommandResult) -> "EvidenceBundle": ...
    
    async def collect_test_evidence(self, result: CommandResult) -> "EvidenceBundle": ...
    
    async def collect_browser_evidence(self, evidence: BrowserEvidence) -> "EvidenceBundle": ...
    
    async def collect_runtime_evidence(self, logs: str) -> "EvidenceBundle": ...


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    summary: str
    source: str  # build, test, browser, runtime
    command: str | None = None
    stdout: str = ""
    stderr: str = ""
    console_errors: tuple[str, ...] = ()
    network_errors: tuple[str, ...] = ()
    screenshots: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================
# Repair Protocols
# ============================================================

class Diagnoser(Protocol):
    """Diagnoses root cause from evidence."""
    
    async def diagnose(
        self,
        evidence: EvidenceBundle,
        context: ContextBundle,
        project_index: ProjectIndex,
    ) -> "Diagnosis": ...


@dataclass(frozen=True, slots=True)
class Diagnosis:
    root_cause: str
    confidence: float
    affected_files: list[str]
    suggested_fixes: list[str]


class RepairPlanner(Protocol):
    """Plans minimal repairs from diagnosis."""
    
    async def plan(
        self,
        diagnosis: Diagnosis,
        original_request: str,
        project_index: ProjectIndex,
    ) -> "RepairPlan": ...


@dataclass(frozen=True, slots=True)
class RepairPlan:
    changes: list[ProposedFileChange]
    reason: str
    validation_commands: list[str] = field(default_factory=list)


class Patcher(Protocol):
    """Generates targeted patches for repairs."""
    
    async def generate_patch(
        self,
        plan: RepairPlan,
        context: ContextBundle,
    ) -> list[ProposedFileChange]: ...


class RepairValidator(Protocol):
    """Validates that a repair actually fixed the issue."""
    
    async def validate(
        self,
        repair_plan: RepairPlan,
        original_evidence: EvidenceBundle,
    ) -> bool: ...


# ============================================================
# State/Persistence Protocols
# ============================================================

class StateStore(Protocol):
    """Persists execution state for resume capability."""
    
    async def save_execution(self, execution: "ExecutionState") -> None: ...
    
    async def load_execution(self, execution_id: str) -> "ExecutionState": ...
    
    async def save_progress(self, progress: "GenerationProgress") -> None: ...
    
    async def load_progress(self, execution_id: str) -> "GenerationProgress": ...


@dataclass(frozen=True, slots=True)
class ExecutionState:
    id: str
    request: TaskRequest
    plan: ChangePlan
    current_stage: str
    current_task: int
    completed_files: list[str]
    failed_file: str | None
    provider_state: dict[str, Any]
    evidence_history: list[EvidenceBundle]
    checkpoints: list[str]


@dataclass(frozen=True, slots=True)
class GenerationProgress:
    total_files: int
    completed_files: dict[str, ProposedFileChange]
    current_file_index: int
    failed_file: str | None
    provider_used: str
    model_used: str


class CheckpointManager(Protocol):
    """Manages git-backed checkpoints for rollback."""
    
    async def create_checkpoint(self, repo_root: Path, label: str) -> str: ...
    
    async def rollback(self, repo_root: Path, checkpoint_id: str) -> None: ...
    
    async def list_checkpoints(self, repo_root: Path) -> list[str]: ...


class ResumeController(Protocol):
    """Controls resumption of interrupted executions."""
    
    async def can_resume(self, execution_id: str) -> bool: ...
    
    async def resume(self, execution_id: str) -> ExecutionState: ...


# ============================================================
# Service Protocol
# ============================================================

class CodeBuilderService(Protocol):
    """High-level service for task lifecycle management."""
    
    def create_task(self, request: TaskRequest) -> BuildTask: ...
    
    def get_task(self, task_id: str) -> BuildTask: ...
    
    def plan_task(self, task_id: str) -> BuildTask: ...
    
    async def execute_task(self, task_id: str) -> BuildTask: ...
    
    def cancel_task(self, task_id: str) -> BuildTask: ...
    
    def rollback_task(self, task_id: str) -> BuildTask: ...


# ============================================================
# Exception Types
# ============================================================

class V3Error(Exception):
    """Base exception for V3 errors."""
    pass


class ProviderError(V3Error):
    """Provider-related errors."""
    pass


class PlanningError(V3Error):
    """Planning-related errors."""
    pass


class GenerationError(V3Error):
    """Generation-related errors."""
    pass


class ExecutionError(V3Error):
    """Execution-related errors."""
    pass


class VerificationError(V3Error):
    """Verification-related errors."""
    pass


class RepairError(V3Error):
    """Repair-related errors."""
    pass


class StateError(V3Error):
    """State/persistence errors."""
    pass