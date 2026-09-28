# Lumina Code Builder V3 Architecture

## Product Vision

Lumina Code Builder V3 is an autonomous AI software engineering system. The user should NOT need to know programming.

**Core Loop:**
```
REQUEST → UNDERSTAND → PLAN → BUILD → RUN → OBSERVE → TEST → DEBUG → REPAIR → VERIFY → DELIVER
```

---

## 1. V2 Component Analysis

### V2 Components to KEEP (Working Well)
| Component | File | Reason |
|-----------|------|--------|
| `Repository` | `repository.py` | Clean filesystem abstraction with path resolution |
| `AtomicChangeApplier` | `applier.py` | Transactional apply with backup/rollback |
| `Transaction Validation` | `transaction.py` | Strong plan↔generated change contract |
| `ValidationRunner` | `validation.py` | Simple command execution with timeout |
| `AutonomousBuildLoop` | `autonomous.py` | Policy/state machine for bounded repair loop |
| `FailureEvidence` / `AttemptResult` | `autonomous.py` | Structured evidence types |
| `DisposableWorkspaceService` | `workspace.py` | Isolated workspace for attempts |
| `VerifiedWorkspacePublisher` | `runtime.py` | Atomic publish of verified changes |
| `BrowserVerifier` / `WorkflowVerifier` | `browser.py` | Playwright-based browser verification |
| `SandboxRuntime` abstractions | `sandbox.py` | SWE-ReX/Docker/local runtimes |
| `ModelRouter` | `providers.py` | Multi-provider fallback chain |
| `JsonTaskStore` | `store.py` | Persistence layer |
| `CodeBuilderService` | `service.py` | Task lifecycle management |

### V2 Components to REFACTOR (Good Concept, Needs Enhancement)
| Component | File | Changes Needed |
|-----------|------|----------------|
| `OllamaClient` | `ollama.py` | Split into provider interface + routing; add structured output, streaming, capability discovery |
| `OllamaPlanner` | `ollama.py` | Separate planning protocol; add task decomposition |
| `OllamaChangeGenerator` | `ollama.py` | Replace monolithic prompt with streaming per-file generator; add schema-first generation |
| `ExecutionPipeline` | `pipeline.py` | Add build/test/browser stages; make streaming |
| `CommandExecutor` | `executor.py` | Integrate with sandbox runtime; add structured results |
| `WorkspaceAttemptRunner` | `runtime.py` | Use streaming generator; add incremental validation |

### V2 Components to REPLACE (Architectural Mismatch)
| Component | File | Replacement |
|-----------|------|-------------|
| Single-file generation | `ollama.py:575-631` | Streaming incremental generator |
| Prompt-based JSON recovery | `ollama.py:91-123` | Native JSON schema / tool calling |
| Hardcoded provider chain | `ollama.py:464-529` | Capability-aware model router |
| Monolithic `generate()` | `ollama.py:556-573` | Async generator yielding file changes |
| Context passing via prompt | `ollama.py:562-563` | Repository intelligence / context engine |

### NEW Components Required for V3
| Component | Purpose |
|-----------|---------|
| `Provider` protocol + implementations | Unified interface with capability discovery |
| `ModelRouter` with intelligent routing | Task→model assignment based on complexity |
| `ProjectIndexer` | Repository analysis, dependency graph, symbol index |
| `ContextEngine` | Targeted context retrieval for each task |
| `TaskDecomposer` | Break large requests into executable subtasks |
| `StreamingGenerator` | Async iterator yielding file changes |
| `BuildOrchestrator` | Multi-stage: generate → build → test → browser → verify |
| `EvidenceCollector` | Unified evidence from compiler, tests, browser, logs |
| `Diagnoser` | Root cause analysis from evidence |
| `RepairPlanner` | Minimal fix planning from diagnosis |
| `StateStore` | Persistent execution state for resume |
| `PreviewManager` | Running application preview URLs |

---

## 2. V3 Directory/Module Structure

```
backend/code_builder_v3/
├── __init__.py
├── models.py                 # Core data models (Pydantic)
├── protocols.py              # Provider, Generator, Sandbox, Indexer protocols
│
├── providers/                # Multi-provider abstraction
│   ├── __init__.py
│   ├── base.py               # Provider protocol + base classes
│   ├── capabilities.py       # Capability discovery (JSON schema, tools, streaming)
│   ├── router.py             # Intelligent model routing
│   ├── openrouter.py
│   ├── groq.py
│   ├── huggingface.py
│   ├── ollama.py
│   ├── openai_compatible.py
│   └── registry.py           # Provider registry & config
│
├── planning/                 # Autonomous planning
│   ├── __init__.py
│   ├── planner.py            # ProjectPlanner protocol + implementation
│   ├── decomposer.py         # TaskDecomposer for large requests
│   ├── analyzer.py           # Request analyzer (intent, scope, complexity)
│   └── schemas.py            # ProjectPlan, Task, FileOperation schemas
│
├── generation/               # Incremental code generation
│   ├── __init__.py
│   ├── generator.py          # StreamingGenerator protocol
│   ├── incremental.py        # Per-file streaming generator
│   ├── context.py            # ContextEngine for targeted retrieval
│   ├── schemas.py            # ProposedChange, GenerationProgress
│   └── validation.py         # Schema-first validation
│
├── repository/               # Repository intelligence
│   ├── __init__.py
│   ├── indexer.py            # ProjectIndexer (AST, deps, symbols)
│   ├── analyzer.py           # Framework/pattern detection
│   ├── context.py            # ContextEngine (retrieval + ranking)
│   ├── mapper.py             # Dependency graph mapper
│   └── watcher.py            # File change watcher for incremental index
│
├── execution/                # Build/test/run orchestration
│   ├── __init__.py
│   ├── orchestrator.py       # BuildOrchestrator (multi-stage pipeline)
│   ├── stages.py             # Stage definitions (gen, build, test, browser)
│   ├── sandbox.py            # SandboxRuntime integration
│   ├── commands.py           # CommandExecutor with structured results
│   ├── dependency.py         # DependencyManager (npm, pip, etc.)
│   └── preview.py            # PreviewManager for running apps
│
├── verification/             # Verification & evidence
│   ├── __init__.py
│   ├── browser.py            # BrowserVerifier (enhanced)
│   ├── workflows.py          # WorkflowVerifier (app-type specific)
│   ├── evidence.py           # EvidenceCollector (unified)
│   ├── visual.py             # VisualVerification (screenshots + vision)
│   └── criteria.py           # AcceptanceCriteria evaluation
│
├── repair/                   # Autonomous repair
│   ├── __init__.py
│   ├── loop.py               # AutonomousRepairLoop (enhanced)
│   ├── diagnoser.py          # Root cause diagnoser
│   ├── planner.py            # RepairPlanner
│   ├── patcher.py            # Minimal patch generator
│   └── validator.py          # Repair verification
│
├── state/                    # Persistence & resume
│   ├── __init__.py
│   ├── store.py              # StateStore (execution state, progress)
│   ├── checkpoints.py        # CheckpointManager (git-backed)
│   ├── resume.py             # ResumeController
│   └── events.py             # Event log for streaming UI
│
├── security/                 # Safety & sandbox
│   ├── __init__.py
│   ├── sandbox.py            # Sandbox policy & isolation
│   ├── secrets.py            # Secret detection/redaction
│   ├── commands.py           # Command allowlist/denylist
│   └── network.py            # Network policy
│
├── service.py                # CodeBuilderService (task lifecycle)
├── router.py                 # API router
└── factory.py                # Dependency injection factory
```

---

## 3. Execution Lifecycle: User Prompt → Verified Application

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        LUMINA CODE BUILDER V3 LIFECYCLE                       │
└─────────────────────────────────────────────────────────────────────────────┘

USER REQUEST
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. UNDERSTAND (RequestAnalyzer)                                             │
│    - Parse natural language intent                                          │
│    - Classify: new app / feature / bug fix / modification                   │
│    - Estimate complexity & required capabilities                            │
└─────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. INDEX (ProjectIndexer) - if existing repo                                │
│    - Scan repository structure                                              │
│    - Build dependency graph                                                 │
│    - Extract symbols, APIs, patterns                                        │
│    - Detect frameworks, conventions                                         │
└─────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. PLAN (ProjectPlanner + TaskDecomposer)                                   │
│    - Create structured ProjectPlan                                          │
│    - Decompose into ordered Tasks                                           │
│    - Assign model/provider per task (routing)                               │
│    - Define validation strategy per stage                                   │
│    - Present plan for approval (optional)                                   │
└─────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 4. BUILD (BuildOrchestrator - streaming, multi-stage)                       │
│                                                                             │
│    FOR EACH TASK (in dependency order):                                     │
│    ┌─────────────────────────────────────────────────────────────────────┐  │
│    │ 4a. GENERATE (StreamingGenerator)                                   │  │
│    │     - Retrieve targeted context (ContextEngine)                     │  │
│    │     - Stream file changes (async iterator)                          │  │
│    │     - Validate schema per file (JSON schema / tool calling)         │  │
│    │     - Persist progress (StateStore)                                 │  │
│    │     - On failure: checkpoint → retry / fallback                     │  │
│    └─────────────────────────────────────────────────────────────────────┘  │
│    │                         │                                             │  │
│    ▼                         ▼                                             │
│    ┌─────────────────────────────────────────────────────────────────────┐  │
│    │ 4b. APPLY (AtomicChangeApplier + CheckpointManager)                 │  │
│    │     - Git-backed checkpoint before changes                          │  │
│    │     - Apply incrementally                                           │  │
│    │     - Validate preconditions                                        │  │
│    └─────────────────────────────────────────────────────────────────────┘  │
│    │                         │                                             │  │
│    ▼                         ▼                                             │
│    ┌─────────────────────────────────────────────────────────────────────┐  │
│    │ 4c. BUILD (DependencyManager + CommandExecutor)                     │  │
│    │     - Install dependencies                                          │  │
│    │     - Run build (npm build, tsc, etc.)                              │  │
│    │     - Type checking / linting                                       │  │
│    │     - On failure → EVIDENCE → DIAGNOSE → REPAIR                     │  │
│    └─────────────────────────────────────────────────────────────────────┘  │
│    │                         │                                             │  │
│    ▼                         ▼                                             │
│    ┌─────────────────────────────────────────────────────────────────────┐  │
│    │ 4d. TEST (CommandExecutor + TestRunner)                             │  │
│    │     - Run unit/integration tests                                    │  │
│    │     - Collect test results as evidence                              │  │
│    │     - On failure → EVIDENCE → DIAGNOSE → REPAIR                     │  │
│    └─────────────────────────────────────────────────────────────────────┘  │
│    │                         │                                             │  │
│    ▼                         ▼                                             │
│    ┌─────────────────────────────────────────────────────────────────────┐  │
│    │ 4e. RUN (SandboxRuntime + PreviewManager)                           │  │
│    │     - Start dev server / backend                                    │  │
│    │     - Get preview URL                                               │  │
│    │     - Health check                                                  │  │
│    └─────────────────────────────────────────────────────────────────────┘  │
│    │                         │                                             │  │
│    ▼                         ▼                                             │
│    ┌─────────────────────────────────────────────────────────────────────┐  │
│    │ 4f. VERIFY (BrowserVerifier + WorkflowVerifier)                     │  │
│    │     - Open in real browser (Playwright)                             │  │
│    │     - Run workflow verification                                     │  │
│    │     - Capture console, network, screenshots                         │  │
│    │     - Visual verification (optional)                                │  │
│    │     - On failure → EVIDENCE → DIAGNOSE → REPAIR                     │  │
│    └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│    REPAIR LOOP (bounded, evidence-driven):                                  │
│    ┌─────────────────────────────────────────────────────────────────────┐  │
│    │ EvidenceCollector → Diagnoser → RepairPlanner → Patcher → Re-verify │  │
│    └─────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 5. DELIVER (VerifiedWorkspacePublisher + PreviewManager)                    │
│    - Atomic publish of all verified changes                                 │
│    - Running preview URL for user                                           │
│    - Structured completion evidence                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Provider/Model Abstraction Architecture

### Provider Protocol
```python
class Provider(Protocol):
    name: str
    
    async def generate_json(
        self, 
        prompt: str, 
        schema: dict,  # JSON Schema
        model: str | None = None,
        stream: bool = False
    ) -> AsyncIterator[dict] | dict: ...
    
    async def generate_text(
        self,
        prompt: str,
        model: str | None = None,
        stream: bool = False
    ) -> AsyncIterator[str] | str: ...
    
    def capabilities(self) -> ProviderCapabilities: ...
    
    def models(self) -> list[ModelInfo]: ...

@dataclass
class ProviderCapabilities:
    json_schema: bool = False      # Native structured output
    tool_calling: bool = False     # Function/tool calling
    streaming: bool = False        # SSE/token streaming
    max_context: int = 4096
    max_output: int = 4096
    supports_system_prompt: bool = True
    rate_limit_rpm: int | None = None
    rate_limit_tpm: int | None = None

@dataclass
class ModelInfo:
    id: str
    provider: str
    capabilities: ProviderCapabilities
    cost_per_1k_input: float
    cost_per_1k_output: float
    strength: ModelStrength  # FAST, BALANCED, STRONG, REASONING
    tags: list[str]  # ["coding", "reasoning", "large-context"]
```

### Intelligent Model Router
```python
class ModelRouter:
    def select_model(
        self,
        task_type: TaskType,      # PLANNING, CODING, DEBUGGING, ANALYSIS, SIMPLE_EDIT
        complexity: Complexity,   # SIMPLE, MODERATE, COMPLEX
        required_capabilities: list[Capability],
        context_size: int,
        available_providers: list[Provider]
    ) -> ModelSelection: ...
```

**Routing Policy:**
| Task Type | Preferred Strength | Fallback |
|-----------|-------------------|----------|
| Planning/Architecture | REASONING | STRONG |
| Code Generation | STRONG | BALANCED |
| Debugging/Repair | REASONING | STRONG |
| Large Context Analysis | LARGE_CONTEXT | STRONG |
| Simple Edits | FAST | BALANCED |
| Schema Validation | Any with json_schema | - |

---

## 5. Repository Intelligence / Context Architecture

### ProjectIndexer
```python
class ProjectIndexer:
    async def index(self, repo_root: Path) -> ProjectIndex: ...
    async def update(self, changed_files: list[Path]) -> None: ...
    
@dataclass
class ProjectIndex:
    structure: DirectoryTree
    dependencies: DependencyGraph
    symbols: SymbolIndex          # Classes, functions, exports
    frameworks: list[Framework]   # Detected: React, FastAPI, etc.
    patterns: PatternCatalog      # Coding patterns in repo
    configs: ConfigFiles          # package.json, pyproject.toml, etc.
```

### ContextEngine
```python
class ContextEngine:
    def retrieve(
        self,
        query: str,
        task_type: TaskType,
        max_tokens: int,
        index: ProjectIndex
    ) -> ContextBundle: ...
    
@dataclass
class ContextBundle:
    files: dict[str, str]           # path → content
    symbols: list[Symbol]           # Relevant symbols
    dependencies: list[Dependency]  # Relevant deps
    patterns: list[Pattern]         # Relevant patterns
    token_estimate: int
```

**Retrieval Strategy:**
1. **Direct references** - Files explicitly mentioned
2. **Dependency neighbors** - Import/export graph neighbors
3. **Symbol matches** - Functions/classes matching query
4. **Pattern examples** - Similar implementations in repo
5. **Config files** - Relevant configuration

---

## 6. Browser Verification Architecture

```python
class BrowserVerifier:
    async def verify(
        self,
        url: str,
        workflow: VerificationWorkflow,
        evidence_collector: EvidenceCollector
    ) -> VerificationResult: ...

@dataclass
class VerificationWorkflow:
    name: str
    steps: list[VerificationStep]
    acceptance_criteria: list[AcceptanceCriterion]

@dataclass
class VerificationStep:
    action: VerificationAction  # NAVIGATE, CLICK, FILL, ASSERT, SCREENSHOT
    selector: str | None
    value: str | None
    assertion: Assertion | None

class VisualVerifier:
    async def compare(
        self,
        baseline: Path | bytes,
        current: Path | bytes,
        threshold: float = 0.95
    ) -> VisualDiff: ...
    
    async def detect_issues(
        self,
        screenshot: Path | bytes
    ) -> list[VisualIssue]: ...
    # Issues: broken_layout, overlapping, blank_screen, missing_content, mobile_broken
```

---

## 7. Autonomous Repair Architecture

```python
class AutonomousRepairLoop:
    def __init__(
        self,
        evidence_collector: EvidenceCollector,
        diagnoser: Diagnoser,
        repair_planner: RepairPlanner,
        patcher: Patcher,
        validator: RepairValidator,
        max_iterations: int = 5
    ): ...

@dataclass
class Diagnoser:
    async def diagnose(
        self,
        evidence: EvidenceBundle,
        context: ContextBundle,
        index: ProjectIndex
    ) -> Diagnosis: ...

@dataclass
class Diagnosis:
    root_cause: str
    confidence: float
    affected_files: list[str]
    suggested_fixes: list[FixHint]

class RepairPlanner:
    async def plan(
        self,
        diagnosis: Diagnosis,
        original_request: str,
        index: ProjectIndex
    ) -> RepairPlan: ...

class Patcher:
    async def generate_patch(
        self,
        plan: RepairPlan,
        context: ContextBundle
    ) -> list[ProposedChange]: ...
```

**Repair Loop:**
```
FAILURE
   │
   ▼
EVIDENCE_COLLECTOR (compiler + tests + browser + logs)
   │
   ▼
DIAGNOSER (root cause + confidence)
   │
   ▼
REPAIR_PLANNER (minimal fix plan)
   │
   ▼
PATCHER (targeted changes)
   │
   ▼
RE-VERIFY (full pipeline)
   │
   ├── PASS → COMPLETE
   │
   └── FAIL (different error) → LOOP (max N)
   │
   └── FAIL (same error) → ESCALATE / FAIL
```

---

## 8. Persistence / Resume Architecture

```python
class StateStore:
    async def save_execution(self, execution: ExecutionState): ...
    async def load_execution(self, execution_id: str) -> ExecutionState: ...
    async def save_progress(self, progress: GenerationProgress): ...
    async def load_progress(self, execution_id: str) -> GenerationProgress: ...

@dataclass
class ExecutionState:
    id: str
    request: TaskRequest
    plan: ProjectPlan
    current_stage: Stage
    current_task: int
    completed_files: list[str]
    failed_file: str | None
    provider_state: dict  # Which provider/model per task
    evidence_history: list[EvidenceBundle]
    checkpoints: list[Checkpoint]

@dataclass
class GenerationProgress:
    total_files: int
    completed_files: dict[str, ProposedChange]
    current_file_index: int
    failed_file: str | None
    provider_used: str
    model_used: str
```

**Resume Capability:**
- On interruption: load `ExecutionState`, continue from `current_task` / `current_file_index`
- On provider failure: switch provider, resume from `failed_file`
- On repair loop: preserve `evidence_history`, continue from last attempt

---

## 9. Security / Sandbox Strategy

| Layer | Mechanism |
|-------|-----------|
| **Network** | Egress allowlist (package registries only); no arbitrary outbound |
| **Filesystem** | Workspace isolation; no host access outside workspace |
| **Commands** | Allowlist: `npm`, `pip`, `python`, `node`, build tools; denylist: `rm -rf`, `sudo`, `curl | sh` |
| **Secrets** | Redact from prompts/logs; inject via env at runtime only |
| **Git** | All changes on temp branch; commit on verify; rollback = reset |
| **Sandbox** | SWE-ReX (local/Docker/Modal/Fargate) for isolation; local subprocess fallback |

---

## 10. Migration Strategy: V2 → V3 (Non-Breaking)

### Phase 0: Compatibility Layer
- Create `code_builder_v3` package alongside `code_builder_v2`
- `V2Adapter` implements V3 protocols using V2 components
- Existing API (`/api/code-builder-v2/*`) unchanged

### Phase 1: Core Protocols & Providers
- Implement `Provider` protocol + implementations
- Implement `ModelRouter` with capability discovery
- Migrate `OllamaClient` → provider implementations
- **Test**: All V2 unit tests pass with V3 providers

### Phase 2: Generation & Context
- Implement `StreamingGenerator`, `ContextEngine`, `ProjectIndexer`
- Replace `OllamaChangeGenerator` with incremental streaming generator
- **Test**: Generate 10+ file app with resume capability

### Phase 3: Execution Orchestration
- Implement `BuildOrchestrator` with multi-stage pipeline
- Integrate `SandboxRuntime`, `DependencyManager`, `PreviewManager`
- **Test**: Full build → test → browser verification pipeline

### Phase 4: Verification & Repair
- Enhance `BrowserVerifier` with visual verification
- Implement `EvidenceCollector`, `Diagnoser`, `RepairPlanner`
- **Test**: Autonomous repair of injected defects

### Phase 5: State & Resume
- Implement `StateStore`, `CheckpointManager`, `ResumeController`
- **Test**: Interrupt/resume mid-generation; provider failover mid-generation

### Phase 6: Service & API
- Implement `CodeBuilderServiceV3` with new lifecycle
- Add `/api/code-builder-v3/*` endpoints
- **Test**: End-to-end V3 API with real providers

### Phase 7: Cutover
- Route new tasks to V3
- Deprecate V2 endpoints after validation period
- Remove V2 code

---

## 11. Implementation Phases (Dependency Order)

| Phase | Components | Depends On | Duration Estimate |
|-------|------------|------------|-------------------|
| 0 | Compatibility layer, V2Adapter | - | 1 week |
| 1 | Provider protocol, implementations, ModelRouter | 0 | 2 weeks |
| 2 | StreamingGenerator, ContextEngine, ProjectIndexer | 1 | 3 weeks |
| 3 | BuildOrchestrator, SandboxRuntime, DependencyManager, PreviewManager | 1, 2 | 3 weeks |
| 4 | BrowserVerifier (enhanced), EvidenceCollector, Diagnoser, RepairPlanner, Patcher | 2, 3 | 3 weeks |
| 5 | StateStore, CheckpointManager, ResumeController | 2, 3 | 2 weeks |
| 6 | CodeBuilderServiceV3, API router | 1-5 | 2 weeks |
| 7 | Cutover, deprecation, cleanup | 6 | 1 week |

**Total: ~17 weeks**

---

## 12. Acceptance Tests Per Phase

### Phase 0: Compatibility
- [ ] All 61 V2 tests pass via `V2Adapter`
- [ ] V2 API endpoints unchanged

### Phase 1: Providers
- [ ] Each provider implements `Provider` protocol
- [ ] Capability discovery works (JSON schema, streaming, tools)
- [ ] ModelRouter selects correct model for each task type
- [ ] Fallback chain works (Groq → HF → Ollama)
- [ ] 429 handling with Retry-After respected

### Phase 2: Generation
- [ ] StreamingGenerator yields file changes incrementally
- [ ] ContextEngine retrieves relevant context (< 50% of repo)
- [ ] ProjectIndexer builds index for 1000+ file repo in < 30s
- [ ] Incremental generation resumes from failed file
- [ ] Schema validation via native JSON schema (no prompt recovery)

### Phase 3: Orchestration
- [ ] BuildOrchestrator runs: generate → install → build → test → run → browser
- [ ] DependencyManager handles npm/pip/yarn
- [ ] PreviewManager returns accessible URL
- [ ] SandboxRuntime isolates execution (Docker/SWE-ReX)

### Phase 4: Verification & Repair
- [ ] BrowserVerifier captures console, network, screenshots
- [ ] VisualVerifier detects blank screen, broken layout
- [ ] EvidenceCollector unifies compiler + test + browser evidence
- [ ] Diagnoser identifies root cause from evidence (80%+ accuracy)
- [ ] RepairPlanner produces minimal fix
- [ ] Autonomous repair loop fixes injected defect

### Phase 5: State & Resume
- [ ] Generation pauses/resumes at file boundary
- [ ] Provider failover mid-generation preserves completed files
- [ ] Repair loop state persists across restarts
- [ ] Checkpoint rollback restores clean state

### Phase 6: Service & API
- [ ] V3 API creates task, streams progress events
- [ ] Task lifecycle: queued → planning → executing → verifying → completed
- [ ] Real-time progress via SSE/WebSocket

### Phase 7: Cutover
- [ ] V3 handles production workload for 1 week
- [ ] Zero regressions vs V2 on benchmark suite
- [ ] V2 endpoints deprecated with migration guide

---

## 13. Risks & Technical Blockers

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Provider JSON schema support varies** | High | Implement adapter layer; fallback to prompt-based for unsupported |
| **Large repo indexing performance** | High | Incremental AST parsing; background indexing; lazy loading |
| **Context window limits** | High | ContextEngine with ranked retrieval; hierarchical summarization |
| **Sandbox isolation complexity** | Medium | Start with SWE-ReX local; Docker as backup; document limits |
| **Visual verification false positives** | Medium | Threshold tuning; human-in-the-loop for ambiguous cases |
| **Repair loop infinite cycles** | Medium | Strict attempt limits; fingerprint deduplication; escalation |
| **Multi-provider cost management** | Medium | Cost tracking per task; budget enforcement in router |
| **Git-based transactions on Windows** | Low | Test on Windows; fallback to copy-based backup |
| **Streaming UI backpressure** | Low | Buffer events; configurable batch size |
| **Migration scope creep** | High | Strict phase gates; no new features during migration |

---

## 14. Next Steps

1. **Review this architecture** with stakeholders
2. **Create Phase 0 spike**: V2Adapter proving compatibility
3. **Define exact Provider protocol** with capability discovery
4. **Prototype ContextEngine** on sample repo
5. **Set up CI** for V3 package alongside V2

---

*Document created: 2026-09-28*
*Based on: V2 codebase analysis + V3 product requirements*