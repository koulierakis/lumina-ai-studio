"""Autonomous repair loop with Agent-Computer Interface (ACI) for Lumina Code Builder.

Implements the core repair cycle:
1. Execute code in sandbox
2. Run browser verification
3. Capture structured evidence
4. Diagnose failure using LLM
5. Generate minimal repair
6. Apply and re-verify
7. Repeat until pass or max attempts
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from .browser import VerificationResult, verify_application
from .providers import ModelRouter, ProviderError
from .sandbox import CommandResult, SandboxRuntime, SandboxSession, create_sandbox_runtime


class RepairPhase(str, Enum):
    INITIALIZING = "initializing"
    BUILDING = "building"
    STARTING_APP = "starting_app"
    VERIFYING = "verifying"
    DIAGNOSING = "diagnosing"
    REPAIRING = "repairing"
    RE_VERIFYING = "re_verifying"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RepairEvidence:
    """Combined evidence from sandbox and browser."""

    phase: RepairPhase
    attempt: int
    sandbox_result: CommandResult | None = None
    browser_result: VerificationResult | None = None
    summary: str = ""

    @property
    def fingerprint(self) -> str:
        """Unique fingerprint for deduplication."""
        payload = f"{self.phase.value}:{self.summary}"
        if self.sandbox_result:
            payload += f":{self.sandbox_result.stderr[-5000:]}"
        if self.browser_result and self.browser_result.evidence:
            payload += f":{self.browser_result.evidence.console_errors}"
            payload += f":{self.browser_result.evidence.page_errors}"
        return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "attempt": self.attempt,
            "sandbox_result": {
                "command": self.sandbox_result.command if self.sandbox_result else None,
                "returncode": self.sandbox_result.returncode if self.sandbox_result else None,
                "stdout": self.sandbox_result.stdout[-2000:] if self.sandbox_result else "",
                "stderr": self.sandbox_result.stderr[-2000:] if self.sandbox_result else "",
                "duration": self.sandbox_result.duration_seconds if self.sandbox_result else 0,
            } if self.sandbox_result else None,
            "browser_result": self.browser_result.to_dict() if self.browser_result else None,
            "summary": self.summary,
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True, slots=True)
class RepairInstruction:
    """Structured repair instruction from diagnoser."""

    instruction: str
    relevant_files: tuple[str, ...] = ()
    suggested_changes: dict[str, str] = field(default_factory=dict)  # path -> new content


@dataclass(frozen=True, slots=True)
class RepairEvent:
    """Event in the repair timeline."""

    phase: RepairPhase
    attempt: int
    timestamp: float
    message: str
    duration_seconds: float = 0.0
    provider: str = ""
    model: str = ""


@dataclass(frozen=True, slots=True)
class RepairResult:
    """Final result of autonomous repair."""

    successful: bool
    attempts: int
    events: tuple[RepairEvent, ...]
    final_evidence: RepairEvidence | None = None
    stop_reason: str = ""
    changed_files: tuple[str, ...] = ()
    total_duration_seconds: float = 0.0


class BuildStep(Protocol):
    """Protocol for build steps in sandbox."""

    async def execute(self, session: SandboxSession, runtime: SandboxRuntime) -> CommandResult: ...


@dataclass(slots=True)
class SandboxBuildStep:
    """Build step that runs commands in sandbox."""

    commands: list[str]
    timeout_seconds: int = 120

    async def execute(self, session: SandboxSession, runtime: SandboxRuntime) -> CommandResult:
        for cmd in self.commands:
            result = await runtime.run_command(session, cmd, timeout_seconds=self.timeout_seconds)
            if result.returncode != 0:
                return result
        return result


@dataclass(slots=True)
class AppStartStep:
    """Start the application server."""

    command: str
    port: int
    ready_check: str = ""  # curl command to check readiness
    startup_timeout: int = 30

    async def execute(self, session: SandboxSession, runtime: SandboxRuntime) -> CommandResult:
        # Start server in background
        proc = await asyncio.create_subprocess_shell(
            self.command,
            cwd=session.workspace_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Wait for readiness
        start = time.time()
        while time.time() - start < self.startup_timeout:
            if self.ready_check:
                result = await runtime.run_command(session, self.ready_check, timeout_seconds=5)
                if result.returncode == 0:
                    return CommandResult(
                        command=self.command,
                        returncode=0,
                        stdout="Server started",
                        stderr="",
                        duration_seconds=time.time() - start,
                    )
            else:
                # Default: try to connect to port
                result = await runtime.run_command(session, f"curl -s http://127.0.0.1:{self.port}", timeout_seconds=5)
                if result.returncode == 0:
                    return CommandResult(
                        command=self.command,
                        returncode=0,
                        stdout="Server started",
                        stderr="",
                        duration_seconds=time.time() - start,
                    )
            await asyncio.sleep(0.5)

        proc.terminate()
        return CommandResult(
            command=self.command,
            returncode=-1,
            stdout="",
            stderr=f"Server failed to start on port {self.port} within {self.startup_timeout}s",
            duration_seconds=time.time() - start,
        )


@dataclass(slots=True)
class BrowserVerifyStep:
    """Browser verification step."""

    app_type: str = "todo"
    headless: bool = True

    async def execute(self, session: SandboxSession, runtime: SandboxRuntime) -> VerificationResult:
        url = await runtime.get_preview_url(session, 3000)  # Default port, could be parameterized
        return await verify_application(url, app_type=self.app_type, headless=self.headless)


class ACIDiagnoser:
    """Agent-Computer Interface diagnoser.

    Uses LLM to analyze structured evidence and produce minimal repair.
    """

    def __init__(self, router: ModelRouter, model: str | None = None):
        self.router = router
        self.model = model

    def diagnose(self, evidence: RepairEvidence, original_prompt: str, app_context: dict[str, Any]) -> RepairInstruction:
        """Analyze evidence and produce repair instruction."""

        prompt = self._build_diagnosis_prompt(evidence, original_prompt, app_context)

        try:
            data = self.router.generate_json(prompt, self.model)
        except ProviderError as e:
            return RepairInstruction(
                instruction=f"Diagnosis failed: {e}",
                relevant_files=(),
            )

        instruction = str(data.get("instruction", "")).strip()
        relevant_files = tuple(str(p) for p in data.get("relevant_files", []) if isinstance(p, str))
        suggested_changes = data.get("suggested_changes", {})
        if not isinstance(suggested_changes, dict):
            suggested_changes = {}

        return RepairInstruction(
            instruction=instruction,
            relevant_files=relevant_files,
            suggested_changes=suggested_changes,
        )

    def _build_diagnosis_prompt(self, evidence: RepairEvidence, original_prompt: str, app_context: dict[str, Any]) -> str:
        """Build diagnosis prompt for LLM."""

        files_list = "\n".join(f"- {f}" for f in app_context.get("files", [])) or "No files listed"

        return f"""You are an expert software engineer diagnosing a failing application.

ORIGINAL REQUEST:
{original_prompt}

APPLICATION CONTEXT:
- Type: {app_context.get('app_type', 'unknown')}
- Files: {files_list}
- Framework: {app_context.get('framework', 'vanilla')}

FAILURE EVIDENCE (Attempt {evidence.attempt}):
Phase: {evidence.phase.value}
Summary: {evidence.summary}

SANDBOX EVIDENCE:
{self._format_sandbox_evidence(evidence.sandbox_result)}

BROWSER EVIDENCE:
{self._format_browser_evidence(evidence.browser_result)}

TASK:
Analyze the failure and provide a MINIMAL, TARGETED repair.

Return ONLY JSON:
{{
  "instruction": "Specific repair instruction for the builder",
  "relevant_files": ["file1.js", "file2.html"],
  "suggested_changes": {{
    "file1.js": "complete corrected file content",
    "file2.html": "complete corrected file content"
  }}
}}

RULES:
- Target ONLY the root cause
- Return COMPLETE file contents for any changes (not diffs)
- Prefer single-file fixes
- Do not rewrite unrelated files
- If browser console shows specific error, fix that exact line
- If validation command fails, fix the command or the code it tests
""".strip()

    def _format_sandbox_evidence(self, result: CommandResult | None) -> str:
        if not result:
            return "No sandbox evidence"
        return f"""Command: {result.command}
Exit code: {result.returncode}
Stdout: {result.stdout[-3000:]}
Stderr: {result.stderr[-3000:]}
Duration: {result.duration_seconds:.1f}s"""

    def _format_browser_evidence(self, result: VerificationResult | None) -> str:
        if not result or not result.evidence:
            return "No browser evidence"
        e = result.evidence
        return f"""Page: {e.page_title} ({e.page_url})
Console errors: {e.console_errors}
Page errors: {e.page_errors}
Network errors: {e.network_errors}
Workflow results: {result.workflow_results}
Failed checks: {[k for k, v in result.workflow_results.items() if not v]}"""


class SandboxApplier:
    """Apply repairs in the sandbox."""

    def __init__(self, runtime: SandboxRuntime):
        self.runtime = runtime

    async def apply(self, session: SandboxSession, instruction: RepairInstruction) -> tuple[bool, list[str]]:
        """Apply repair instruction to sandbox."""
        changed = []

        # Apply suggested changes
        for path, content in instruction.suggested_changes.items():
            try:
                await self.runtime.write_file(session, path, content)
                changed.append(path)
            except Exception as e:
                return False, [f"Failed to write {path}: {e}"]

        return True, changed


class AutonomousRepairLoop:
    """Main autonomous repair orchestration."""

    def __init__(
        self,
        router: ModelRouter,
        sandbox: SandboxRuntime,
        max_attempts: int = 5,
        max_repeated_failures: int = 2,
        model: str | None = None,
    ):
        self.router = router
        self.sandbox = sandbox
        self.max_attempts = max_attempts
        self.max_repeated_failures = max_repeated_failures
        self.model = model

        self.diagnoser = ACIDiagnoser(router, model)
        self.applier = SandboxApplier(sandbox)

        self.events: list[RepairEvent] = []
        self.fingerprints: dict[str, int] = {}

    def _add_event(self, phase: RepairPhase, attempt: int, message: str, duration: float = 0.0, provider: str = "", model: str = ""):
        self.events.append(RepairEvent(
            phase=phase,
            attempt=attempt,
            timestamp=time.time(),
            message=message,
            duration_seconds=duration,
            provider=provider,
            model=model,
        ))

    async def execute(
        self,
        workspace_root: Path,
        original_prompt: str,
        build_steps: list[BuildStep],
        start_step: AppStartStep,
        verify_step: BrowserVerifyStep,
        app_context: dict[str, Any],
        env: dict[str, str] | None = None,
    ) -> RepairResult:
        """Execute the full autonomous repair loop."""
        start_time = time.time()
        self.events.clear()
        self.fingerprints.clear()

        self._add_event(RepairPhase.INITIALIZING, 0, "Creating disposable sandbox workspace")

        session = await self.sandbox.create_session(workspace_root, env)
        self._add_event(RepairPhase.INITIALIZING, 0, f"Sandbox session created: {session.session_id}")

        try:
            previous_evidence: RepairEvidence | None = None

            for attempt in range(1, self.max_attempts + 1):
                phase = RepairPhase.BUILDING if attempt == 1 else RepairPhase.REPAIRING
                self._add_event(phase, attempt, f"Starting attempt {attempt}/{self.max_attempts}")

                # Run build steps
                build_ok = True
                for step in build_steps:
                    step_start = time.time()
                    result = await step.execute(session, self.sandbox)
                    step_duration = time.time() - step_start
                    self._add_event(
                        phase, attempt,
                        f"Build step: {step.__class__.__name__}",
                        duration=step_duration,
                    )
                    if result.returncode != 0:
                        build_ok = False
                        evidence = RepairEvidence(
                            phase=phase,
                            attempt=attempt,
                            sandbox_result=result,
                            summary=f"Build failed: {result.stderr[-500:]}",
                        )
                        previous_evidence = evidence
                        break

                if not build_ok:
                    # Check for repeated failure
                    if self._check_repeated_failure(previous_evidence):
                        return self._fail_result(attempt, "Repeated identical failure", start_time)

                    # Diagnose and repair
                    if attempt < self.max_attempts:
                        repair = await self._diagnose_and_repair(previous_evidence, original_prompt, app_context, attempt)
                        if not repair:
                            return self._fail_result(attempt, "Diagnosis returned empty repair", start_time)
                        continue
                    else:
                        return self._fail_result(attempt, "Max attempts reached", start_time)

                # Start application
                self._add_event(RepairPhase.STARTING_APP, attempt, "Starting application server")
                start_result = await start_step.execute(session, self.sandbox)
                if start_result.returncode != 0:
                    evidence = RepairEvidence(
                        phase=RepairPhase.STARTING_APP,
                        attempt=attempt,
                        sandbox_result=start_result,
                        summary=f"App failed to start: {start_result.stderr[-500:]}",
                    )
                    previous_evidence = evidence
                    if self._check_repeated_failure(evidence):
                        return self._fail_result(attempt, "Repeated start failure", start_time)
                    if attempt < self.max_attempts:
                        repair = await self._diagnose_and_repair(evidence, original_prompt, app_context, attempt)
                        if not repair:
                            return self._fail_result(attempt, "Diagnosis returned empty repair", start_time)
                        continue
                    return self._fail_result(attempt, "Max attempts reached", start_time)

                # Verify in browser
                self._add_event(RepairPhase.VERIFYING, attempt, "Running browser verification")
                verify_start = time.time()
                browser_result = await verify_step.execute(session, self.sandbox)
                verify_duration = time.time() - verify_start

                self._add_event(
                    RepairPhase.VERIFYING, attempt,
                    f"Browser verification: {'PASSED' if browser_result.passed else 'FAILED'}",
                    duration=verify_duration,
                )

                evidence = RepairEvidence(
                    phase=RepairPhase.VERIFYING,
                    attempt=attempt,
                    sandbox_result=start_result,
                    browser_result=browser_result,
                    summary="Browser verification passed" if browser_result.passed else browser_result.error_message,
                )

                if browser_result.passed:
                    self._add_event(RepairPhase.COMPLETED, attempt, "All verifications passed")
                    return RepairResult(
                        successful=True,
                        attempts=attempt,
                        events=tuple(self.events),
                        final_evidence=evidence,
                        changed_files=tuple(set().union(*[set()])) if False else tuple(),
                        total_duration_seconds=time.time() - start_time,
                    )

                # Verification failed - diagnose
                previous_evidence = evidence
                if self._check_repeated_failure(evidence):
                    return self._fail_result(attempt, "Repeated identical failure", start_time)

                if attempt < self.max_attempts:
                    repair = await self._diagnose_and_repair(evidence, original_prompt, app_context, attempt)
                    if not repair:
                        return self._fail_result(attempt, "Diagnosis returned empty repair", start_time)
                    continue

            return self._fail_result(self.max_attempts, "Max attempts reached", start_time)

        finally:
            await self.sandbox.close_session(session)

    async def _diagnose_and_repair(
        self,
        evidence: RepairEvidence,
        original_prompt: str,
        app_context: dict[str, Any],
        attempt: int,
    ) -> bool:
        """Diagnose failure and apply repair."""
        self._add_event(RepairPhase.DIAGNOSING, attempt, "Diagnosing failure with LLM")

        instruction = self.diagnoser.diagnose(evidence, original_prompt, app_context)

        if not instruction.instruction.strip():
            return False

        self._add_event(RepairPhase.REPAIRING, attempt, f"Applying repair: {instruction.instruction[:100]}")

        # Apply to sandbox
        # TODO: obtain the live SandboxSession from the repair loop; the applier's
        # runtime handle is not a session, so this placeholder must not bind it.
        # For now, return True to indicate repair was generated
        return True

    def _check_repeated_failure(self, evidence: RepairEvidence | None) -> bool:
        if not evidence:
            return False
        fp = evidence.fingerprint
        count = self.fingerprints.get(fp, 0) + 1
        self.fingerprints[fp] = count
        return count >= self.max_repeated_failures

    def _fail_result(self, attempt: int, reason: str, start_time: float) -> RepairResult:
        self._add_event(RepairPhase.FAILED, attempt, reason)
        return RepairResult(
            successful=False,
            attempts=attempt,
            events=tuple(self.events),
            final_evidence=None,
            stop_reason=reason,
            total_duration_seconds=time.time() - start_time,
        )


# Placeholder - need to integrate properly
async def run_autonomous_repair(
    workspace_root: Path,
    prompt: str,
    build_commands: list[str],
    start_command: str,
    port: int,
    app_type: str = "todo",
    max_attempts: int = 5,
    router: ModelRouter | None = None,
    sandbox: SandboxRuntime | None = None,
) -> RepairResult:
    """Convenience function to run autonomous repair."""

    if router is None:
        router = ModelRouter()
    if sandbox is None:
        sandbox = create_sandbox_runtime()

    build_steps = [SandboxBuildStep(commands=build_commands)]
    start_step = AppStartStep(command=start_command, port=port)
    verify_step = BrowserVerifyStep(app_type=app_type)

    app_context = {
        "app_type": app_type,
        "framework": "vanilla",
        "files": ["index.html"],  # Would be detected
    }

    loop = AutonomousRepairLoop(router, sandbox, max_attempts=max_attempts)
    return await loop.execute(workspace_root, prompt, build_steps, start_step, verify_step, app_context)
