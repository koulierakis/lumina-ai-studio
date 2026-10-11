"""Data models for Gold Builder AI engine."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional, Dict
import uuid

from pydantic import BaseModel, Field, ConfigDict


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())



class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"

class JobStatus(str, Enum):
    PENDING = "pending"
    UNDERSTANDING = "understanding"
    INSPECTING = "inspecting"
    PLANNING = "planning"
    GENERATING = "generating"
    MEDIA = "media"
    INSTALLING = "installing"
    BUILDING = "building"
    TYPECHECKING = "typechecking"
    LINTING = "linting"
    TESTING = "testing"
    STARTING = "starting"
    VERIFYING = "verifying"
    DIAGNOSING = "diagnosing"
    REPAIRING = "repairing"
    RECOVERING = "recovering"
    SELF_REVIEWING = "self_reviewing"
    INDEPENDENT_REVIEW = "independent_review"
    REVIEW_REPAIR = "review_repair"
    FINAL_VERIFYING = "final_verifying"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_new_id)
    name: str
    description: str = ""
    kind: str = "generate"
    depends_on: List[str] = Field(default_factory=list)
    status: str = "pending"
    file_path: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    attempts: int = 0
    last_error: Optional[str] = None


class ImageSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str
    prompt: str
    alt: str = ""
    operation: str = "generate"  # generate | edit
    input_image_path: Optional[str] = None
    reference_images: List[str] = Field(default_factory=list)
    negative_prompt: Optional[str] = None
    size: str = "1024x1024"
    width: Optional[int] = None
    height: Optional[int] = None
    aspect_ratio: Optional[str] = None
    quality: Optional[str] = None
    style: Optional[str] = None
    seed: Optional[int] = None
    number_of_outputs: int = 1
    output_format: str = "png"
    sequence_id: Optional[str] = None
    frame_index: Optional[int] = None
    reference_asset_ids: List[str] = Field(default_factory=list)
    subject_consistency_requested: bool = False


class VideoSpec(BaseModel):
    """Requested video artefact. Providers may support only a subset of operations."""
    model_config = ConfigDict(extra="ignore")
    path: str
    prompt: str
    operation: str = "generate"  # generate | animate | transform
    seconds: float = 4.0
    size: str = "1024x576"
    aspect_ratio: Optional[str] = None
    quality: Optional[str] = None
    seed: Optional[int] = None
    input_image_path: Optional[str] = None
    input_video_path: Optional[str] = None
    reference_images: List[str] = Field(default_factory=list)
    negative_prompt: Optional[str] = None
    output_format: str = "mp4"
    fps: Optional[int] = Field(default=None, ge=1, le=120)
    sequence_id: Optional[str] = None
    reference_asset_ids: List[str] = Field(default_factory=list)
    subject_consistency_requested: bool = False


class AttachmentInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_new_id)
    name: str
    path: str
    mime: str = "application/octet-stream"
    size_bytes: int = 0


class MediaAsset(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_new_id)
    media_type: str
    operation: str
    status: str = "completed"
    provider: str
    model: str
    path: str
    mime: str
    prompt: str = ""
    source_paths: List[str] = Field(default_factory=list)
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    created_at: str = Field(default_factory=_now_iso)
    error: Optional[str] = None
    retry_count: int = 0
    provider_attempts: List[Dict[str, Any]] = Field(default_factory=list)
    sequence_id: Optional[str] = None
    frame_index: Optional[int] = None
    reference_asset_ids: List[str] = Field(default_factory=list)
    subject_consistency_requested: bool = False
    provider_consistency_capability: Optional[str] = None


class VerificationStep(BaseModel):
    model_config = ConfigDict(extra="ignore")
    action: str  # open|reload|click|fill|select|submit|wait|set_viewport|assert_*|screenshot
    args: Dict[str, Any] = Field(default_factory=dict)
    requirement_id: Optional[str] = None


class AcceptanceRequirement(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    text: str
    kind: str = "functional"
    verifiable: bool = True


class VerificationStepResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    index: int
    action: str
    ok: bool
    error: Optional[str] = None
    screenshot_path: Optional[str] = None
    args: Dict[str, Any] = Field(default_factory=dict)


class VerificationScenarioResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    passed: bool
    steps: List[VerificationStepResult] = Field(default_factory=list)
    title: Optional[str] = None
    http_status: Optional[int] = None
    console_errors: List[str] = Field(default_factory=list)
    network_errors: List[str] = Field(default_factory=list)
    screenshot_path: Optional[str] = None
    rendered_text_snippet: Optional[str] = None
    error: Optional[str] = None


class QualityGates(BaseModel):
    """Per-plan gate enablement. Setting a gate to False makes it purely
    informational — its failure never blocks completion."""
    model_config = ConfigDict(extra="ignore")
    install: bool = True
    build: bool = True
    typecheck: bool = True
    lint: bool = True
    test: bool = True
    startup: bool = True
    verify: bool = True
    workflows: bool = True


class GateReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    enabled: bool
    status: str  # passed | failed | not_applicable
    blocking: bool = False
    detail: Optional[str] = None


class Plan(BaseModel):
    model_config = ConfigDict(extra="ignore")
    app_name: str
    description: str
    stack_id: str = "html-static"
    stack: Dict[str, str] = Field(default_factory=dict)
    tasks: List[Task] = Field(default_factory=list)
    entrypoints: Dict[str, str] = Field(default_factory=dict)
    verify_url: Optional[str] = None
    required_env: List[str] = Field(default_factory=list)
    image_specs: List[ImageSpec] = Field(default_factory=list)
    video_specs: List[VideoSpec] = Field(default_factory=list)
    requirements: List[AcceptanceRequirement] = Field(default_factory=list)
    verification_scenario: List[VerificationStep] = Field(default_factory=list)
    acceptance_contract_authoritative: bool = False
    quality_gates: QualityGates = Field(default_factory=QualityGates)


class GeneratedFile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str
    content: str
    binary: bool = False


class LogEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ts: str = Field(default_factory=_now_iso)
    level: str = "info"
    phase: str = ""
    message: str = ""
    data: Optional[Dict[str, Any]] = None


class CommandResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    label: str
    cmd: List[str]
    cwd: str = "."
    rc: int
    output_tail: str = ""
    started_at: str = Field(default_factory=_now_iso)
    duration_s: float = 0.0


class BuildEvidence(BaseModel):
    model_config = ConfigDict(extra="ignore")
    install: List[CommandResult] = Field(default_factory=list)
    build: List[CommandResult] = Field(default_factory=list)
    typecheck: List[CommandResult] = Field(default_factory=list)
    lint: List[CommandResult] = Field(default_factory=list)
    test: List[CommandResult] = Field(default_factory=list)


class VerificationResult(BaseModel):
    """Legacy shape kept for backwards compatibility with callers of the
    older verifier. The structured runner returns VerificationScenarioResult
    which is mapped into this on-write."""
    model_config = ConfigDict(extra="ignore")
    passed: bool
    http_status: Optional[int] = None
    title: Optional[str] = None
    console_errors: List[str] = Field(default_factory=list)
    page_errors: List[str] = Field(default_factory=list)
    network_errors: List[str] = Field(default_factory=list)
    screenshot_path: Optional[str] = None
    rendered_text_snippet: Optional[str] = None
    rendered_text: Optional[str] = None
    error: Optional[str] = None
    interactions: List[Dict[str, Any]] = Field(default_factory=list)
    media_loaded: List[str] = Field(default_factory=list)
    media_broken: List[str] = Field(default_factory=list)
    steps: List[VerificationStepResult] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)
    semantic_required: bool = False
    semantic_passed: Optional[bool] = None


class PreviewInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    job_id: str
    running: bool
    port: Optional[int] = None
    internal_url: Optional[str] = None
    proxy_url: Optional[str] = None
    stack_id: Optional[str] = None
    started_at: Optional[str] = None


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    label: str
    path: str
    created_at: str
    size_bytes: int = 0


class RepairPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")
    root_cause: str
    affected_files: List[str] = Field(default_factory=list)
    modifications: List[Dict[str, Any]] = Field(default_factory=list)


class RepairAttempt(BaseModel):
    model_config = ConfigDict(extra="ignore")
    attempt: int
    stage: str
    diagnosis: Optional[RepairPlan] = None
    files_modified: List[str] = Field(default_factory=list)
    snapshot_before: Optional[str] = None  # snapshot id
    original_failures: List[str] = Field(default_factory=list)
    post_repair_failures: List[str] = Field(default_factory=list)
    accepted: bool = False
    rolled_back: bool = False
    rollback_reason: Optional[str] = None
    resolved: bool = False


class RepoChangeSet(BaseModel):
    model_config = ConfigDict(extra="ignore")
    created: List[str] = Field(default_factory=list)
    modified: List[str] = Field(default_factory=list)
    deleted: List[str] = Field(default_factory=list)
    unchanged: List[str] = Field(default_factory=list)


class UsageMetrics(BaseModel):
    model_config = ConfigDict(extra="ignore")
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    by_provider: Dict[str, int] = Field(default_factory=dict)
    by_model: Dict[str, int] = Field(default_factory=dict)


class UsageBudget(BaseModel):
    model_config = ConfigDict(extra="ignore")
    max_calls: Optional[int] = None
    max_total_tokens: Optional[int] = None
    max_prompt_tokens: Optional[int] = None
    max_completion_tokens: Optional[int] = None


class CapabilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


class Capability(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    status: CapabilityStatus
    detail: Optional[str] = None
    providers: List[str] = Field(default_factory=list)




class ProviderRole(str, Enum):
    PLANNER = "planner"
    CODER = "coder"
    DEBUGGER = "debugger"
    VERIFIER_REASONER = "verifier_reasoner"


class VersionRecord(BaseModel):
    checkpoint_id: str
    user_request: str
    timestamp: str
    files_changed: List[str] = Field(default_factory=list)
    validation_result: Dict[str, Any] = Field(default_factory=dict)
    git_commit_sha: Optional[str] = None
    git_branch: Optional[str] = None
    git_pushed: bool = False


class GuardianEvent(BaseModel):
    """Structured, secret-free record of a Guardian decision or action."""
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_new_id)
    ts: str = Field(default_factory=_now_iso)
    kind: str
    phase: str = ""
    message: str = ""
    data: Optional[Dict[str, Any]] = None


class GuardianRecovery(BaseModel):
    """One bounded recovery decision for a job (deterministic, LLM-free)."""
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_new_id)
    ts: str = Field(default_factory=_now_iso)
    attempt: int
    reason: str
    stale_phase: str = ""
    action: str
    outcome: str = "pending"
    duplicate_prevented: bool = False
    generation_before: int = 0
    generation_after: int = 0
    detail: Optional[Dict[str, Any]] = None


class ReviewFinding(BaseModel):
    """One structured review observation.

    ``severity`` is normalised to blocking | non_blocking. A blocking finding is
    an acceptance blocker: it can never end in COMPLETED until resolved.
    """
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_new_id)
    severity: str = "non_blocking"  # blocking | non_blocking
    category: str = "other"
    requirement_id: Optional[str] = None
    file: Optional[str] = None
    message: str = ""
    evidence: Optional[str] = None
    source: str = ""  # self | independent

    @property
    def is_blocking(self) -> bool:
        return str(self.severity or "").strip().lower() == "blocking"


class SelfReviewResult(BaseModel):
    """Structured result of the implementer's own review pass.

    Self-review is advisory: it may request a repair but can never mark the job
    COMPLETE on its own.
    """
    model_config = ConfigDict(extra="ignore")
    status: str = "needs_repair"  # pass | fail | needs_repair | error
    findings: List[ReviewFinding] = Field(default_factory=list)
    requirements_checked: List[str] = Field(default_factory=list)
    files_reviewed: List[str] = Field(default_factory=list)
    confidence: Optional[float] = None
    recommended_repairs: List[str] = Field(default_factory=list)
    provider: Optional[str] = None
    model: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    attempts: int = 0
    malformed: bool = False

    def blocking_findings(self) -> List[ReviewFinding]:
        return [f for f in self.findings if f.is_blocking]


class IndependentReviewResult(BaseModel):
    """Structured result of the independent reviewer pass."""
    model_config = ConfigDict(extra="ignore")
    status: str = "needs_repair"  # approve | reject | needs_repair | error
    blocking_findings: List[ReviewFinding] = Field(default_factory=list)
    non_blocking_findings: List[ReviewFinding] = Field(default_factory=list)
    requirements_with_insufficient_evidence: List[str] = Field(default_factory=list)
    reviewed_diff: bool = False
    provider: Optional[str] = None
    model: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    attempts: int = 0
    malformed: bool = False
    fallback_used: bool = False

    def all_findings(self) -> List[ReviewFinding]:
        return list(self.blocking_findings) + list(self.non_blocking_findings)


class ReviewEvidence(BaseModel):
    """Persisted review-layer state, including provider independence proof."""
    model_config = ConfigDict(extra="ignore")
    strict: bool = False
    strict_reasons: List[str] = Field(default_factory=list)
    required: bool = False
    implementation_provider: Optional[str] = None
    implementation_model: Optional[str] = None
    self_review: Optional[SelfReviewResult] = None
    independent_review: Optional[IndependentReviewResult] = None
    self_review_status: Optional[str] = None
    self_review_findings: List[ReviewFinding] = Field(default_factory=list)
    reviewer_provider: Optional[str] = None
    reviewer_model: Optional[str] = None
    independent_review_status: Optional[str] = None
    independent_review_findings: List[ReviewFinding] = Field(default_factory=list)
    review_attempt_count: int = 0
    repair_attempt_count: int = 0
    self_repair_count: int = 0
    independent_repair_count: int = 0
    max_self_review_repairs: int = 2
    max_independent_review_repairs: int = 2
    unresolved_blockers: List[ReviewFinding] = Field(default_factory=list)
    independent_review_unavailable: bool = False
    unavailable_reason: Optional[str] = None
    # True only when every configured provider is externally blocked or cooling
    # down (auth/quota/rate-limit), i.e. a live availability boundary rather than
    # a missing independent authority. A missing authority stays fail-closed.
    external_provider_exhaustion: bool = False
    # ---- Latest code-writing authority (BLOCKER 2) ----
    # Updated after EVERY LLM patch/write, including review-driven repairs. A
    # reviewer must never review a patch it authored, so the original
    # implementation provider alone is not a sufficient exclusion once another
    # provider has modified the code.
    last_code_author_provider: Optional[str] = None
    last_code_author_model: Optional[str] = None
    last_code_author_stage: Optional[str] = None
    last_code_author_at: Optional[str] = None
    # ---- Code/review generation linkage (completion invariant) ----
    # code_generation increments on every code write. A review approval is only
    # valid for the generation it inspected, so any later write makes a prior
    # approval stale until the code is re-reviewed.
    code_generation: int = 0
    self_review_generation: int = 0
    independent_review_generation: int = 0
    reviewed_generation: int = 0
    # Independence strength actually achieved by the selected reviewer.
    cross_vendor_review: bool = False
    same_vendor_degraded: bool = False
    review_started_at: Optional[str] = None
    review_completed_at: Optional[str] = None
    last_deterministic_gates_passed: bool = False


class Job(BaseModel):
    version_history: List[VersionRecord] = Field(default_factory=list)
    role_routing: Dict[str, str] = Field(default_factory=dict)
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_new_id)
    mode: str = "new"
    source: Optional[str] = None
    request: str
    workspace_path: str = ""
    status: JobStatus = JobStatus.PENDING
    progress: int = 0
    plan: Optional[Plan] = None
    files: List[GeneratedFile] = Field(default_factory=list)
    media_assets: List[MediaAsset] = Field(default_factory=list)
    attachments: List[AttachmentInfo] = Field(default_factory=list)
    logs: List[LogEvent] = Field(default_factory=list)
    build_evidence: Optional[BuildEvidence] = None
    verification: Optional[VerificationResult] = None
    baseline_verification: Optional[VerificationResult] = None
    production_url: Optional[str] = None
    production_verification: Optional[VerificationResult] = None
    production_verified_at: Optional[str] = None
    gates: List[GateReport] = Field(default_factory=list)
    preview: Optional[PreviewInfo] = None
    snapshots: List[Snapshot] = Field(default_factory=list)
    repair_history: List[RepairAttempt] = Field(default_factory=list)
    repair_attempts: int = 0
    max_repair_attempts: int = 3
    repo_changes: Optional[RepoChangeSet] = None
    usage: UsageMetrics = Field(default_factory=UsageMetrics)
    budget: Optional[UsageBudget] = None
    provider_config: Dict[str, Any] = Field(default_factory=dict)
    # ---- Guardian / recovery state (persisted with the job) ----
    heartbeat_at: Optional[str] = None
    active_phase: Optional[str] = None
    active_phase_started_at: Optional[str] = None
    execution_generation: int = 0
    recovery_attempts: int = 0
    max_recovery_attempts: int = 3
    last_recovery_reason: Optional[str] = None
    paused_from_status: Optional[str] = None
    provider_paused: bool = False
    guardian_events: List[GuardianEvent] = Field(default_factory=list)
    recovery_history: List[GuardianRecovery] = Field(default_factory=list)
    last_checkpoint_snapshot: Optional[str] = None
    recovery_source: Optional[str] = None
    recovered_at: Optional[str] = None
    # ---- Review layer state (persisted with the job) ----
    review: Optional[ReviewEvidence] = None
    strict_review: bool = False
    require_independent_review: bool = False
    max_self_review_repairs: int = 2
    max_independent_review_repairs: int = 2
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)
    error: Optional[str] = None


class MediaImageRequest(BaseModel):
    prompt: str
    output_path: str = "generated/image.png"
    operation: str = "generate"
    input_image_path: Optional[str] = None
    reference_images: List[str] = Field(default_factory=list)
    negative_prompt: Optional[str] = None
    size: str = "1024x1024"
    width: Optional[int] = None
    height: Optional[int] = None
    aspect_ratio: Optional[str] = None
    quality: Optional[str] = None
    style: Optional[str] = None
    seed: Optional[int] = None
    number_of_outputs: int = Field(default=1, ge=1, le=4)
    output_format: str = "png"
    sequence_id: Optional[str] = None
    frame_index: Optional[int] = None
    reference_asset_ids: List[str] = Field(default_factory=list)
    subject_consistency_requested: bool = False


class MediaVideoRequest(BaseModel):
    prompt: str
    output_path: str = "generated/video.mp4"
    operation: str = "generate"
    input_image_path: Optional[str] = None
    input_video_path: Optional[str] = None
    reference_images: List[str] = Field(default_factory=list)
    negative_prompt: Optional[str] = None
    sequence_id: Optional[str] = None
    reference_asset_ids: List[str] = Field(default_factory=list)
    subject_consistency_requested: bool = False
    seconds: float = Field(default=4.0, gt=0, le=60)
    size: str = "1024x576"
    aspect_ratio: Optional[str] = None
    quality: Optional[str] = None
    seed: Optional[int] = None
    output_format: str = "mp4"
    fps: Optional[int] = Field(default=None, ge=1, le=120)


class ProviderInfo(BaseModel):
    id: str
    label: str
    kind: str
    provider: str
    model: str
    available: bool
    priority: int = 100
    notes: Optional[str] = None
    status: Optional[str] = None
    cooldown_remaining_s: float = 0.0
    capabilities: List[str] = Field(default_factory=list)
    last_failure: Optional[str] = None


class StackInfo(BaseModel):
    id: str
    label: str


class CreateJobRequest(BaseModel):
    request: str
    app_name: Optional[str] = None
    verify: bool = True
    max_repair_attempts: int = 3
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    stack_id: Optional[str] = None
    with_media: bool = True
    quality_gates: Optional[QualityGates] = None
    budget: Optional[UsageBudget] = None
    strict_review: Optional[bool] = None
    require_independent_review: Optional[bool] = None
    max_self_review_repairs: int = 2
    max_independent_review_repairs: int = 2


class CreateExistingRepoJobRequest(BaseModel):
    request: str
    source: str
    max_repair_attempts: int = 3
    push_changes: bool = False
    llm_provider: Optional[str] = None
    quality_gates: Optional[QualityGates] = None
    budget: Optional[UsageBudget] = None
    strict_review: Optional[bool] = None
    require_independent_review: Optional[bool] = None
    max_self_review_repairs: int = 2
    max_independent_review_repairs: int = 2
