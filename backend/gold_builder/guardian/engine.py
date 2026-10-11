"""Guardian engine: heartbeat, phase tracking, stale scan, and recovery.

Deterministic by construction. Every decision is derived from persisted job
state and environment configuration; no LLM provider is ever consulted to
decide whether or how to recover.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from functools import partial
from typing import Awaitable, Callable, Optional

from ..engine.checkpoint import OwnershipConfigError, PersistenceError
from ..engine.checkpoint import _read_local as read_local_checkpoint
from ..engine.checkpoint import load_job as default_load_job
from ..engine.checkpoint import resolve_ownership_mode
from ..engine.checkpoint import save_job as default_save_job
from ..engine.checkpoint import save_job_conditional as default_conditional_save
from ..engine.checkpoint import save_job_critical as default_critical_save
from ..engine.lifecycle import transition
from ..models import BuildEvidence, GuardianRecovery, Job, JobStatus
from .events import guardian_event
from .policy import (
    ACTIVE_STATUSES,
    RECOVERABLE_STATUSES,
    heartbeat_age_seconds,
    is_stale,
    recovery_action_for,
    stale_threshold_seconds,
)
from .provider_gate import llm_providers_available, provider_snapshot

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
_VALID_STATUS_VALUES = {s.value for s in JobStatus}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Guardian:
    """Internal watchdog/recovery coordinator for one engine process."""

    def __init__(
        self,
        db,
        *,
        save_job_fn: Optional[Callable[[object, Job], Awaitable[None]]] = None,
        load_job_fn: Optional[Callable[[object, str], Awaitable[Optional[Job]]]] = None,
        conditional_save_fn: Optional[Callable[..., Awaitable[object]]] = None,
        critical_save_fn: Optional[Callable[[object, Job], Awaitable[None]]] = None,
        scan_interval_s: Optional[float] = None,
        autostart: bool = True,
        ownership_mode: Optional[str] = None,
    ) -> None:
        self._db = db
        self._save = save_job_fn or default_save_job
        self._load = load_job_fn or default_load_job
        # Explicit ownership mode. Distributed requires a shared CAS backend for
        # every ownership claim; single_host allows the guarded host-local file
        # lock. Resolved once, deterministically, at construction. A production
        # deployment that cannot be proven safe raises OwnershipConfigError
        # (fail closed) instead of silently falling back to host-local ownership.
        try:
            self._ownership_mode = resolve_ownership_mode(ownership_mode, db)
        except OwnershipConfigError:
            logger.error(
                "unsafe ownership configuration; refusing to start Guardian "
                "(set GB_GUARDIAN_OWNERSHIP_MODE explicitly in production)"
            )
            raise
        # Fail-closed persistence for ownership/state transitions. Tests inject
        # failure here to prove the Guardian never continues execution after a
        # claim that could not be durably recorded. The resolved ownership mode is
        # bound so a caller-injected fake (which does not accept ``mode``) is
        # unaffected.
        self._critical_save = critical_save_fn or (
            save_job_fn if save_job_fn is not None else partial(default_critical_save, mode=self._ownership_mode)
        )
        self._conditional_save = conditional_save_fn or partial(
            default_conditional_save, mode=self._ownership_mode
        )
        try:
            default_interval = float(os.environ.get("GB_GUARDIAN_SCAN_SECONDS", "30"))
        except ValueError:
            default_interval = 30.0
        self._interval = scan_interval_s or max(5.0, default_interval)
        self._runners: dict[str, tuple[asyncio.Task, int]] = {}
        self._stop = asyncio.Event()
        self._monitor: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._autostart = autostart
        self._started = False

    # ------------------------------------------------------------------ state
    async def _persist(self, job: Job, *, critical: bool = False) -> None:
        """Persist job state.

        Ordinary progress telemetry is best-effort. Ownership/state transitions
        pass ``critical=True``: a write failure then raises
        :class:`PersistenceError` so the caller fails closed instead of
        continuing execution on an unrecorded transition.
        """
        job.updated_at = _now_iso()
        if critical:
            await self._critical_save(self._db, job)
            return
        try:
            await self._save(self._db, job)
        except Exception:
            # Telemetry must never crash the engine because a checkpoint failed.
            pass

    def record_heartbeat(self, job: Job) -> None:
        """Refresh the real execution heartbeat for the current phase."""
        now = _now_iso()
        phase = job.status.value if isinstance(job.status, JobStatus) else str(job.status)
        if getattr(job, "active_phase", None) != phase:
            job.active_phase = phase
            job.active_phase_started_at = now
        job.heartbeat_at = now
        job.updated_at = now

    def begin_phase(self, job: Job, phase) -> None:
        """Mark the start of a new execution phase (resets the stale clock)."""
        value = phase.value if isinstance(phase, JobStatus) else str(phase)
        now = _now_iso()
        job.active_phase = value
        job.active_phase_started_at = now
        job.heartbeat_at = now
        job.updated_at = now

    def runner_for(self, job_id: str) -> Optional[asyncio.Task]:
        entry = self._runners.get(job_id)
        return entry[0] if entry else None

    @property
    def ownership_mode(self) -> str:
        """The resolved ownership authority for this Guardian process."""
        return self._ownership_mode

    def register_runner(self, job_id: str, task: asyncio.Task, generation: int) -> None:
        self._runners[job_id] = (task, generation)

    def unregister_runner(self, job_id: str, task: asyncio.Task) -> None:
        entry = self._runners.get(job_id)
        if entry and entry[0] is task:
            self._runners.pop(job_id, None)

    def _cancel_runner(self, job_id: str) -> bool:
        entry = self._runners.get(job_id)
        if not entry:
            return False
        task, _ = entry
        if task.done():
            return False
        task.cancel()
        return True

    async def claim_recovery(self, job: Job, *, expected_generation: int, source: str) -> bool:
        """Atomically claim recovery ownership, or refuse a duplicate.

        Ownership is taken with a compare-and-set write: the persisted job is
        advanced to ``execution_generation = expected_generation + 1`` only when
        the persisted generation (and recovery attempts) are still no greater
        than what this caller observed. Two processes/workers that race on the
        same generation therefore cannot both win — the loser observes the newer
        generation and skips.

        The claim fails closed: if the conditional write cannot be durably
        recorded the transition did not happen, ``False`` is returned, and the
        caller must not start execution. A new generation is committed as
        ``RECOVERING`` so that a crash immediately after a successful claim is
        recoverable on restart.
        """
        async with self._lock:
            fresh = None
            try:
                fresh = await self._load(self._db, job.id)
            except Exception:
                fresh = None
            if fresh is not None:
                if fresh.execution_generation != expected_generation:
                    job.execution_generation = fresh.execution_generation
                    return False
                if fresh.status in TERMINAL_STATUSES or fresh.status == JobStatus.PAUSED:
                    job.status = fresh.status
                    return False
                if fresh.recovery_attempts > job.recovery_attempts:
                    job.recovery_attempts = fresh.recovery_attempts
                    return False
                expected_attempts = fresh.recovery_attempts
            else:
                # No durable record loaded. In distributed mode the shared
                # document is the only ownership authority; a missing record is
                # never a licence to claim locally. Fail closed so the caller can
                # surface/recover the missing durable state instead of running.
                if self._ownership_mode == "distributed":
                    return False
                # single_host: the local checkpoint is authoritative, so an
                # unverifiable in-memory generation must still not be trusted for
                # an ownership claim.
                expected_attempts = job.recovery_attempts

            # Snapshot mutable ownership state so a failed claim leaves the
            # caller's job object exactly as it was (no phantom generation).
            prior = (
                job.execution_generation, job.recovery_attempts, job.status,
                job.recovery_source, job.recovered_at, job.active_phase,
                job.active_phase_started_at, job.heartbeat_at, job.updated_at,
            )
            job.execution_generation = expected_generation + 1
            job.recovery_attempts = expected_attempts + 1
            transition(job, JobStatus.RECOVERING, context="guardian:claim")
            job.recovery_source = source
            job.recovered_at = _now_iso()
            self.begin_phase(job, JobStatus.RECOVERING)

            def _restore() -> None:
                (
                    job.execution_generation, job.recovery_attempts, job.status,
                    job.recovery_source, job.recovered_at, job.active_phase,
                    job.active_phase_started_at, job.heartbeat_at, job.updated_at,
                ) = prior

            try:
                result = await self._conditional_save(
                    self._db, job,
                    expected_generation=expected_generation,
                    expected_attempts=expected_attempts,
                )
            except Exception:
                # Persistence infrastructure failed during the claim: fail closed.
                _restore()
                return False

            if not bool(getattr(result, "applied", False)):
                _restore()
                # A competing writer owns the newer generation. Re-read the
                # *authoritative* local checkpoint so this loser cannot later
                # overwrite it via an ordinary telemetry write.
                try:
                    local = await asyncio.to_thread(read_local_checkpoint, job.id)
                except Exception:
                    local = None
                if local is not None and local.execution_generation >= job.execution_generation:
                    job.execution_generation = local.execution_generation
                    job.recovery_attempts = local.recovery_attempts
                    if local.status in TERMINAL_STATUSES or local.status == JobStatus.PAUSED:
                        job.status = local.status
                try:
                    live = await self._load(self._db, job.id)
                except Exception:
                    live = None
                if live is not None and live.execution_generation >= job.execution_generation:
                    job.execution_generation = live.execution_generation
                    job.recovery_attempts = live.recovery_attempts
                    if live.status in TERMINAL_STATUSES or live.status == JobStatus.PAUSED:
                        job.status = live.status
                return False
            return True

    # ---------------------------------------------------------------- recovery
    async def recover_job(
        self,
        job: Job,
        *,
        reason: str,
        action: Optional[str] = None,
        stale_phase: str = "",
        generation_before: Optional[int] = None,
        source: str = "watchdog",
    ) -> bool:
        """Recover one job deterministically, bounded by max_recovery_attempts."""
        if job.status in TERMINAL_STATUSES or job.status == JobStatus.PAUSED:
            return False

        if job.recovery_attempts >= max(0, job.max_recovery_attempts):
            transition(job, JobStatus.FAILED, context="guardian:exhausted")
            job.error = (
                f"Guardian: recovery attempts exhausted ({job.recovery_attempts}/"
                f"{job.max_recovery_attempts}) after {reason}. Manual restart required."
            )
            guardian_event(
                job, "recovery_exhausted", phase=stale_phase or "",
                message=job.error,
                data={"reason": reason, "attempts": job.recovery_attempts},
            )
            try:
                await self._persist(job, critical=True)
            except PersistenceError:
                # The terminal transition could not be durably recorded. Surface
                # it so the caller can retry rather than assume the job is parked.
                guardian_event(
                    job, "recovery_persist_failed",
                    message="Failed to persist exhausted-recovery state; will retry.",
                )
                return False
            return False

        generation_before = (
            job.execution_generation if generation_before is None else generation_before
        )
        # Decide the action from the PRE-recovery state: claim_recovery marks the
        # job RECOVERING, which would otherwise mask planning-vs-execution.
        chosen = action or recovery_action_for(job)
        if chosen == "restart":
            chosen = "resume_execution" if job.plan is not None else "replan"
        if chosen not in {"replan", "resume_execution"}:
            chosen = "resume_execution" if job.plan is not None else "replan"

        if not await self.claim_recovery(
            job, expected_generation=generation_before, source=source
        ):
            # If the claim was refused because persistence failed closed, the
            # persisted generation still equals what we observed. Do not write a
            # spurious duplicate-recovery record over the un-persisted claim.
            if job.execution_generation == generation_before:
                guardian_event(
                    job, "recovery_claim_failed_closed", phase=stale_phase,
                    message="Recovery claim could not be durably recorded; not starting execution.",
                    data={"reason": reason, "generation": generation_before},
                )
                try:
                    await self._persist(job)
                except Exception:
                    pass
                return False
            rec = GuardianRecovery(
                attempt=job.recovery_attempts + 1,
                reason=reason,
                stale_phase=stale_phase,
                action=chosen,
                outcome="skipped_duplicate",
                duplicate_prevented=True,
                generation_before=generation_before,
                generation_after=job.execution_generation,
            )
            job.recovery_history.append(rec)
            guardian_event(
                job, "duplicate_recovery_prevented", phase=stale_phase,
                message="A newer execution generation already owns this job; recovery skipped.",
                data={"generation": job.execution_generation, "reason": reason},
            )
            await self._persist(job)
            return False

        # recovery_attempts was already advanced atomically inside claim_recovery.
        rec = GuardianRecovery(
            attempt=job.recovery_attempts,
            reason=reason,
            stale_phase=stale_phase,
            action=chosen,
            outcome="in_progress",
            generation_before=generation_before,
            generation_after=job.execution_generation,
        )
        job.recovery_history.append(rec)
        job.last_recovery_reason = reason
        guardian_event(
            job, "recovery_started", phase=stale_phase,
            message=f"Guardian recovering ({reason}) via {chosen}",
            data={
                "reason": reason,
                "action": chosen,
                "attempt": job.recovery_attempts,
                "generation": job.execution_generation,
            },
        )
        try:
            await self._persist(job, critical=True)
        except PersistenceError:
            # The claim was recorded but the attempt/history transition was not.
            # Abandon before launching execution: the next scan will retry.
            guardian_event(
                job, "recovery_persist_failed", phase=stale_phase,
                message="Failed to persist recovery start; not launching execution.",
            )
            return False

        # Never leave two live runners for the same job.
        self._cancel_runner(job.id)

        if chosen == "replan":
            await self._recover_planning(job, rec)
        else:
            await self._recover_execution(job, rec)
        return True

    async def _recover_planning(self, job: Job, rec: GuardianRecovery) -> None:
        """Planning-family recovery: discard the partial plan and re-plan."""
        job.plan = None
        job.files = []
        job.gates = []
        job.verification = None
        job.build_evidence = BuildEvidence()
        job.repair_attempts = 0
        job.error = None
        guardian_event(
            job, "recovery_replan", message="Restarting from planning with a fresh plan."
        )
        await self._persist(job)
        await self._launch_restart(job, rec)

    async def _recover_execution(self, job: Job, rec: GuardianRecovery) -> None:
        """Execution-family recovery: safe checkpoint, then resume from plan."""
        try:
            from ..engine.snapshots import snapshot

            snap = snapshot(job.id, label="guardian-recovery")
            job.last_checkpoint_snapshot = snap.id
            guardian_event(
                job, "recovery_checkpoint", message=f"Checkpoint {snap.id} captured before resume.",
                data={"snapshot": snap.id},
            )
        except Exception:
            guardian_event(
                job, "recovery_checkpoint", message="Checkpoint unavailable; resuming from persisted state.",
                data={"snapshot": None},
            )
        job.error = None
        await self._persist(job)
        await self._launch_resume(job, rec)

    # ------------------------------------------------------------------ launch
    def _provider_config(self, job: Job):
        cfg = job.provider_config or {}
        gates_data = cfg.get("quality_gates")
        gates = None
        if gates_data:
            from ..models import QualityGates
            try:
                gates = QualityGates(**gates_data)
            except Exception:
                gates = None
        return cfg, gates

    async def _launch_restart(self, job: Job, rec: GuardianRecovery) -> None:
        cfg, gates = self._provider_config(job)
        from ..engine.orchestrator import run_existing_repo_job, run_job

        generation = job.execution_generation

        async def runner() -> Job:
            if job.mode == "existing-repo":
                return await run_existing_repo_job(
                    job, self._db, source=job.source,
                    preferred_provider=cfg.get("llm_provider"),
                    quality_gates=gates,
                    push_changes=bool(cfg.get("push_changes")),
                )
            return await run_job(
                job, self._db,
                preferred_provider=cfg.get("llm_provider"),
                stack_id=cfg.get("stack_id"),
                with_media=bool(cfg.get("with_media", True)),
                quality_gates=gates,
            )

        await self._spawn(job, runner, rec, generation)

    async def _launch_resume(self, job: Job, rec: GuardianRecovery) -> None:
        cfg, gates = self._provider_config(job)
        from ..engine.orchestrator import resume_job

        generation = job.execution_generation

        async def runner() -> Job:
            return await resume_job(
                job, self._db,
                preferred_provider=cfg.get("llm_provider"),
                quality_gates=gates,
            )

        await self._spawn(job, runner, rec, generation)

    async def _spawn(self, job, runner, rec: GuardianRecovery, generation: int) -> None:
        async def guarded() -> None:
            try:
                await runner()
                rec.outcome = "completed"
                if generation == job.execution_generation and job.status not in TERMINAL_STATUSES:
                    # runner() is expected to set a terminal state; if it did
                    # not, surface it rather than silently leaving the job.
                    guardian_event(
                        job, "recovery_runner_returned_nonterminal",
                        message=f"Runner returned with status {job.status.value}.",
                    )
                    await self._persist(job)
            except asyncio.CancelledError:
                rec.outcome = "cancelled"
                raise
            except Exception as exc:  # noqa: BLE001
                rec.outcome = "failed"
                guardian_event(
                    job, "recovery_runner_error",
                    message=f"Recovery runner failed: {type(exc).__name__}",
                )
                await self._persist(job)
            finally:
                entry = self._runners.get(job.id)
                if entry and entry[1] == generation:
                    self._runners.pop(job.id, None)

        task = asyncio.create_task(guarded())
        self.register_runner(job.id, task, generation)

    # -------------------------------------------------------------- pause/resume
    async def pause_job(self, job: Job, *, reason: str = "provider_outage") -> bool:
        """Pause an active job during a provider outage, preserving its phase."""
        if job.status in TERMINAL_STATUSES or job.status == JobStatus.PAUSED:
            return False
        job.paused_from_status = (
            job.status.value if isinstance(job.status, JobStatus) else str(job.status)
        )
        transition(job, JobStatus.PAUSED, context="guardian:pause")
        job.provider_paused = True
        job.error = None
        self.begin_phase(job, JobStatus.PAUSED)
        guardian_event(
            job, "provider_paused", phase=job.active_phase or "",
            message="Paused: no LLM provider is currently available.",
            data={"reason": reason, **provider_snapshot()},
        )
        try:
            await self._persist(job, critical=True)
        except PersistenceError:
            # The pause could not be durably recorded: keep the job active rather
            # than reporting a paused state that will not survive a restart.
            guardian_event(
                job, "pause_persist_failed", phase=job.active_phase or "",
                message="Failed to persist paused state; job remains active.",
                data={"reason": reason},
            )
            return False
        return True

    async def resume_paused_job(self, job: Job) -> bool:
        """Resume a provider-paused job once a provider is available again."""
        if job.status != JobStatus.PAUSED:
            return False
        if not llm_providers_available():
            return False
        target_value = job.paused_from_status or ""
        restored = (
            JobStatus(target_value)
            if target_value in _VALID_STATUS_VALUES
            and JobStatus(target_value) not in TERMINAL_STATUSES
            and JobStatus(target_value) != JobStatus.PAUSED
            else None
        )
        if restored is None:
            restored = JobStatus.PLANNING if job.plan is None else JobStatus.GENERATING
        transition(job, restored, context="guardian:resume")
        job.provider_paused = False
        job.paused_from_status = None
        self.begin_phase(job, restored)
        guardian_event(
            job, "provider_resumed", phase=restored.value,
            message=f"Resuming from {restored.value}: provider available again.",
            data=provider_snapshot(),
        )
        try:
            await self._persist(job, critical=True)
        except PersistenceError:
            guardian_event(
                job, "resume_persist_failed", phase=restored.value,
                message="Failed to persist resume transition; not launching execution.",
            )
            return False

        rec = GuardianRecovery(
            attempt=job.recovery_attempts,
            reason="provider_outage_recovered",
            action="resume_execution" if job.plan is not None else "replan",
            outcome="in_progress",
            generation_before=job.execution_generation,
            generation_after=job.execution_generation,
        )
        job.recovery_history.append(rec)
        self._cancel_runner(job.id)
        if job.plan is None:
            await self._launch_restart(job, rec)
        else:
            await self._launch_resume(job, rec)
        return True

    # -------------------------------------------------------------------- scan
    async def startup_scan(self) -> list[str]:
        """Recover unfinished jobs left active by a previous process.

        Only *stale* unfinished jobs are recovered. A job whose heartbeat is
        still fresh may be owned by a live worker (another process, or a
        duplicate startup scanner in the same deploy); recovering it here would
        start a second concurrent runner. A crashed owner stops heartbeating, so
        its job becomes stale and is recovered on a later pass.
        """
        recovered: list[str] = []
        for job in await self._unfinished_jobs():
            if job.status in TERMINAL_STATUSES or job.status == JobStatus.PAUSED:
                continue
            if job.status not in RECOVERABLE_STATUSES:
                continue
            if not is_stale(job):
                continue
            action = recovery_action_for(job)
            guardian_event(
                job, "startup_scan_detected",
                message=f"Unfinished job found in {job.status.value}; recovering.",
                data={"action": action, "generation": job.execution_generation},
            )
            ok = await self.recover_job(
                job,
                reason="startup_scan",
                action=action,
                stale_phase=job.active_phase or job.status.value,
                source="startup_scan",
            )
            if ok:
                recovered.append(job.id)
        return recovered

    async def scan_once(self) -> list[str]:
        """One watchdog pass: resume provider-paused jobs, recover stale jobs."""
        acted: list[str] = []
        for job in await self._unfinished_jobs():
            if job.status == JobStatus.PAUSED:
                if getattr(job, "provider_paused", False) and llm_providers_available():
                    if await self.resume_paused_job(job):
                        acted.append(job.id)
                continue
            if job.status not in RECOVERABLE_STATUSES:
                continue
            if not is_stale(job):
                continue
            age = int(heartbeat_age_seconds(job))
            phase = job.active_phase or job.status.value
            guardian_event(
                job, "stale_detected", phase=phase,
                message=(
                    f"No heartbeat for {age}s during {phase} "
                    f"(threshold {int(stale_threshold_seconds(phase))}s)."
                ),
                data={"age_s": age, "phase": phase,
                      "threshold_s": int(stale_threshold_seconds(phase))},
            )
            ok = await self.recover_job(
                job, reason="stale_execution", stale_phase=phase, source="watchdog",
            )
            if ok:
                acted.append(job.id)
        return acted

    async def _unfinished_jobs(self) -> list[Job]:
        try:
            from ..engine.checkpoint import list_jobs

            jobs = await list_jobs(self._db, limit=200)
        except Exception:
            return []
        return [
            j for j in jobs
            if j.status in ACTIVE_STATUSES or j.status == JobStatus.PAUSED
        ]

    # ------------------------------------------------------------------ daemon
    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stop.clear()
        self._monitor = asyncio.create_task(self._run_loop())

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
                return
            except asyncio.TimeoutError:
                pass
            if self._stop.is_set():
                return
            try:
                await self.scan_once()
            except Exception:
                continue

    async def stop(self) -> None:
        self._stop.set()
        monitor = self._monitor
        if monitor:
            monitor.cancel()
            try:
                await monitor
            except (asyncio.CancelledError, Exception):
                pass
        self._monitor = None
        self._started = False
