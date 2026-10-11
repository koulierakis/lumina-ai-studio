"""End-to-end orchestrator with quality gates, snapshots, preview lifecycle,
usage tracking and structured diagnosis.

New-app lifecycle:
    plan → generate → media → install → build → typecheck → lint → test →
    start → verify → (diagnose → snapshot → repair → rebuild → reverify)* →
    export → preview
"""
from __future__ import annotations

import asyncio
import traceback
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import hashlib
import difflib
import shutil

from motor.motor_asyncio import AsyncIOMotorDatabase

from .. import workspace
from ..progress import mark, stage, traced
from ..models import (
    BuildEvidence,
    GeneratedFile,
    Job,
    JobStatus,
    LogEvent,
    Plan,
    QualityGates,
    RepairAttempt,
    RepairPlan,
    VerificationResult,
    VerificationStep,
)
from .checkpoint import save_job
from .diagnosis import DiagnosticContext, diagnose
from .executor import run_pipeline, start_stack_server
from .exporter import export_zip
from .generator import generate_file
from .inspector import clone_or_copy, inspect, summarize_for_prompt
from .lifecycle import completion_authority, transition
from .media import generate_media
from .planner import build_patch_plan, build_plan
from .semantic_acceptance import read_only_request
from .preview import manager as preview_manager
from .quality_gates import all_passed, default_gates, evaluate
from .repair_policy import repair_improved, validate_modified_sources, validate_source_syntax
from .npm_conflict import format_conflicts, is_eresolve, parse_eresolve, propose_manifest_peer_repair
from .repo_diff import diff, hash_tree
from .snapshots import snapshot as make_snapshot
from .stacks import get_stack
from .verifier import verify_url
from .verification_planner import plan_verification_scenario
from .repo_intelligence import build_repo_map, get_focused_cross_file_context
from .review import (
    derive_strict_review,
    record_code_author_from_router,
    requires_independent_review,
    review_is_stale,
    review_passed,
    review_verdict,
    run_review_pipeline,
)



_DEPENDENCY_MANIFESTS = (
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "pyproject.toml", "poetry.lock", "Pipfile", "Pipfile.lock",
    "requirements.txt", "requirements-dev.txt",
)


def _materialize_job_inputs(job: Job, project: Path) -> None:
    """Copy staged user attachments into the isolated project workspace."""
    if not getattr(job, "attachments", None):
        return
    staged_root = workspace.job_dir(job.id) / "inputs"
    project_inputs = workspace.resolve_within(project, "inputs")
    project_inputs.mkdir(parents=True, exist_ok=True)
    for attachment in job.attachments:
        source = workspace.resolve_within(staged_root, Path(attachment.path).name)
        target = workspace.resolve_within(project_inputs, Path(attachment.path).name)
        if source.is_file():
            shutil.copy2(source, target)
    # Reference uploads are job inputs, not repository source. Keep them usable
    # by the builder while preventing an existing-repo push from committing them.
    git_dir = project / ".git"
    if git_dir.is_dir():
        exclude = git_dir / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        current = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if "/inputs/" not in {line.strip() for line in current.splitlines()}:
            separator = "" if not current or current.endswith("\n") else "\n"
            exclude.write_text(current + separator + "/inputs/\n", encoding="utf-8")


def _dependency_fingerprint(project: Path) -> str:
    """Stable digest of dependency manifests used to decide whether install can be reused."""
    h = hashlib.sha256()
    found = False
    for rel in _DEPENDENCY_MANIFESTS:
        path = project / rel
        if path.is_file():
            found = True
            h.update(rel.encode("utf-8"))
            h.update(b"\0")
            h.update(path.read_bytes())
            h.update(b"\0")
    return h.hexdigest() if found else ""


async def _log(job: Job, db: AsyncIOMotorDatabase, phase: str, message: str,
               level: str = "info", data: dict | None = None) -> None:
    job.logs.append(LogEvent(phase=phase, message=message, level=level, data=data))
    job.updated_at = datetime.now(timezone.utc).isoformat()
    await save_job(db, job)


def _code_change_data(path: str, before: str, after: str) -> dict:
    """Compact unified diff payload for the live execution viewer."""
    lines = list(difflib.unified_diff(
        before.splitlines(), after.splitlines(),
        fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="",
    ))
    max_lines = 500
    truncated = len(lines) > max_lines
    if truncated:
        lines = lines[:max_lines] + ["... diff truncated in live viewer ..."]
    return {
        "kind": "code_change", "path": path, "diff": "\\n".join(lines),
        "truncated": truncated,
    }


async def _provider_event_logger(job: Job, db: AsyncIOMotorDatabase, event: str, metadata: dict) -> None:
    provider = metadata.get("provider", "provider")
    labels = {
        "PROVIDER REQUEST START": f"Contacting {provider}…",
        "PROVIDER REQUEST TIMEOUT": f"{provider} timed out; trying fallback if available.",
        "PROVIDER RATE LIMIT": f"{provider} rate limited; switching provider.",
        "PROVIDER RATE LIMIT FALLBACK": f"{provider} is cooling down; trying next provider.",
        "PROVIDER FALLBACK": f"Switching away from {provider}.",
        "PROVIDER RESPONSE": f"{provider} responded successfully.",
        "PROVIDER COOLDOWN SKIP": f"Skipping {provider} while it is cooling down.",
        "PROVIDER REQUEST ERROR": f"{provider} failed; trying fallback if available.",
    }
    await _log(job, db, "provider", labels.get(event, event), data={"event": event, **metadata})


def _progress(job: Job, pct: int) -> None:
    job.progress = max(job.progress, min(100, pct))


async def _run_media_stage(job: Job, plan: Plan, project: Path, db: AsyncIOMotorDatabase) -> None:
    if not (plan.image_specs or plan.video_specs):
        return
    transition(job, JobStatus.MEDIA, context="orchestrator:media")
    _progress(job, 68)
    await _log(
        job,
        db,
        "media",
        f"Executing media plan: {len(plan.image_specs)} image(s), {len(plan.video_specs)} video(s)",
    )
    files, assets = await generate_media(
        project,
        [s.model_dump() for s in plan.image_specs],
        [s.model_dump() for s in plan.video_specs],
    )
    job.files.extend(files)
    job.media_assets.extend(assets)
    await _log(
        job,
        db,
        "media",
        f"Media completed: {len(assets)} asset(s)",
        data={
            "assets": [
                {
                    "id": asset.id,
                    "type": asset.media_type,
                    "operation": asset.operation,
                    "path": asset.path,
                    "provider": asset.provider,
                    "model": asset.model,
                }
                for asset in assets
            ]
        },
    )


async def _decide_completion(job: Job, db: AsyncIOMotorDatabase, *,
                             log: bool = True) -> Job:
    """Final authority: COMPLETE requires deterministic gates AND review pass.

    AI approval alone is never sufficient, and a blocking review finding can
    never end in COMPLETED. This is intentionally a small, pure decision over
    persisted state so it can be verified and mutation-tested directly.
    """
    gates_ok = all_passed(job.gates)
    review_ok = review_passed(job)
    if not review_ok:
        job.status = JobStatus.FAILED
        review = job.review
        blockers = [f.message for f in (review.unresolved_blockers if review else [])]
        if review and review.external_provider_exhaustion:
            job.error = (
                "review failed: independent review unavailable "
                "(configured live providers externally blocked or rate-limited)"
            )
        elif review and review.independent_review_unavailable and requires_independent_review(job):
            job.error = (
                "review failed: independent review unavailable "
                f"({review.unavailable_reason or 'no independent provider'})"
            )
        elif blockers:
            job.error = "review failed with unresolved blockers: " + "; ".join(blockers[:5])
        elif review and review_is_stale(job):
            job.error = (
                "review failed: review approval is stale for the current code "
                f"(code_generation={review.code_generation}, "
                f"reviewed_generation={review.reviewed_generation})"
            )
        else:
            job.error = "review failed: review layer did not complete"
        if log:
            await _log(job, db, "review", job.error, level="error",
                       data={"event": "REVIEW BLOCKER FOUND", "blockers": blockers[:10]})
    else:
        job.status = JobStatus.COMPLETED if gates_ok else JobStatus.FAILED
        if not gates_ok:
            failing = [g.name for g in job.gates
                       if g.enabled and g.status.upper() == "FAIL"]
            job.error = f"quality gates failed: {failing}"
        else:
            job.error = None
    return job


async def _finalize_read_only_audit(
    job: Job,
    db: AsyncIOMotorDatabase,
    *,
    reason: str,
    log_message: str,
) -> Job:
    """Sole authority for a non-building read-only / audit terminal state.

    A zero-task or explicitly read-only request has no browser-verifiable
    behaviour, so it bypasses the code-generation completion gate — but it must
    NOT masquerade as a code-generation result. We persist it as a non-false
    terminal: the gates are replaced with an explicit audit PASS and the job is
    marked COMPLETED *only* through :func:`finalize_job`, so there is exactly one
    completion authority and the live UI / final report can tell an audit from a
    build.

    A genuine mutation request (READ_ONLY vs MUTATING) is never routed here for
    a zero-task plan; that path is a completion failure, not an audit.
    """
    from ..models import GateReport

    job.gates = [GateReport(name="read_only_audit", enabled=True, status="PASS")]
    await _log(job, db, "audit", log_message)
    _progress(job, 100)
    return await finalize_job(job, db, read_only_audit=True, reason=reason)


async def finalize_job(
    job: Job,
    db: AsyncIOMotorDatabase,
    *,
    read_only_audit: bool = False,
    requires_review: bool = True,
    reason: str | None = None,
    log: bool = True,
) -> Job:
    """The ONLY authority allowed to set a terminal COMPLETED status.

    Every lifecycle path (initial run, existing-repo run, repair, manual
    re-verification, API verify) must end here. This centralises completion so
    the engine cannot report COMPLETED from several places with different rules,
    which was the root cause of zero-task false completions and gate-bypassing
    paths. It:

    - requires a plan (a completion without a plan is unverifiable),
    - awards COMPLETED only for a governed read-only audit, or when deterministic
      gates pass and the review layer is passed when the job engaged it,
    - derives FAILED with a precise reason otherwise.

    ``requires_review=False`` preserves the pre-review behaviour for legacy jobs
    that never engaged the review layer; it is an explicit policy input, not a
    precomputed verdict.
    """
    # Only inside this authority may a terminal status be written (see
    # engine.lifecycle). This is the single completion authority: every other
    # path is rejected by the lifecycle table, so COMPLETED cannot be declared
    # from a stray writer and a terminal job cannot be resurrected.
    with completion_authority():
        if read_only_audit:
            job.status = JobStatus.COMPLETED
            job.error = None
        elif job.plan is None:
            job.status = JobStatus.FAILED
            job.error = reason or "cannot finalize a job without a plan"
        elif not requires_review:
            job.status = JobStatus.COMPLETED if all_passed(job.gates) else JobStatus.FAILED
            if job.status == JobStatus.FAILED:
                failures = [g.name for g in job.gates if g.blocking]
                job.error = f"quality gates failed: {failures}"
            else:
                job.error = None
        else:
            await _decide_completion(job, db, log=log)
    return job


async def _finalize_run(
    job: Job,
    plan: Plan,
    project: Path,
    artifacts: Path,
    db: AsyncIOMotorDatabase,
    *,
    mode: str = "new",
    work_branch: Optional[str] = None,
    before_hashes: Optional[dict] = None,
    push_changes: bool = False,
) -> Job:
    """Shared completion: repo diff, export, gates, git commit/push, preview."""
    if mode == "existing-repo":
        after_hashes = hash_tree(project)
        job.repo_changes = diff(before_hashes or {}, after_hashes)
        await _log(job, db, "diff",
                   f"created={len(job.repo_changes.created)} "
                   f"modified={len(job.repo_changes.modified)} "
                   f"deleted={len(job.repo_changes.deleted)} "
                   f"unchanged={len(job.repo_changes.unchanged)}")

    zip_path = artifacts / f"{plan.app_name}.zip"
    try:
        export_zip(project, zip_path)
        await _log(job, db, "export", f"Exported ZIP to {zip_path}")
    except Exception as e:  # noqa: BLE001
        await _log(job, db, "export", f"ZIP export failed: {e}", level="error")

    # Single completion authority: the initial build path finalizes through the
    # same gate as every other lifecycle path.
    if job.plan is None:
        job.plan = plan
    await finalize_job(job, db)
    completed = job.status == JobStatus.COMPLETED

    if completed and mode == "existing-repo":
        from .snapshots import commit_if_git, push_current_branch
        from ..models import VersionRecord
        commit_sha = commit_if_git(project, f"Gold Builder: {job.request[:72]}")
        if commit_sha:
            changed = sorted(set(
                job.repo_changes.created + job.repo_changes.modified + job.repo_changes.deleted
            ))
            branch = work_branch
            pushed = False
            if push_changes:
                pushed_branch = push_current_branch(project)
                pushed = bool(pushed_branch)
                if pushed:
                    branch = pushed_branch
                    await _log(job, db, "git", f"Pushed verified branch {branch} to origin")
                else:
                    await _log(job, db, "git", "Verified commit created, but remote push failed or GitHub credentials are unavailable", level="warn")
            job.version_history.append(VersionRecord(
                checkpoint_id=f"git-{commit_sha[:12]}",
                user_request=job.request,
                timestamp=datetime.now(timezone.utc).isoformat(),
                files_changed=changed,
                validation_result={"gates_passed": True, "browser_passed": bool(job.verification and job.verification.passed)},
                git_commit_sha=commit_sha,
                git_branch=branch,
                git_pushed=pushed,
            ))
            await _log(job, db, "git", f"Committed verified changes locally at {commit_sha[:12]}")

    if completed:
        try:
            info = preview_manager.status(job.id)
            if info is None:
                info = await preview_manager.start(job.id, get_stack(plan.stack_id))
            job.preview = info
            if mode != "existing-repo":
                await _log(job, db, "preview",
                           f"Preview running at {info.internal_url} "
                           f"(proxy {info.proxy_url})")
        except Exception as e:  # noqa: BLE001
            if mode != "existing-repo":
                await _log(job, db, "preview", f"preview start failed: {e}",
                           level="warn")

    _progress(job, 100)
    await save_job(db, job)
    return job


async def _run_review_stage(
    job: Job,
    plan: Plan,
    project: Path,
    artifacts: Path,
    db: AsyncIOMotorDatabase,
    preferred_provider: Optional[str],
    *,
    mode: str = "new",
    baseline_evidence: Optional[BuildEvidence] = None,
    reuse_baseline_install: bool = False,
) -> None:
    """Run the mandatory self-review + independent-review pipeline.

    Strict-review policy is derived deterministically and persisted so a restart
    reproduces the same decision. Review evidence is stored on ``job.review``.
    """
    if job.repo_changes is not None:
        changed = (job.repo_changes.created + job.repo_changes.modified
                   + job.repo_changes.deleted)
    else:
        changed = [f.path for f in job.files]
    explicit = (job.provider_config or {}).get("strict_review")
    strict, reasons = derive_strict_review(
        mode=mode,
        plan=plan,
        changed_files=changed,
        request=job.request,
        failed_verification=bool(job.verification and not job.verification.passed),
        repaired=bool(job.repair_attempts),
        explicit=explicit,
    )
    job.strict_review = strict
    configured_required = (job.provider_config or {}).get("require_independent_review")
    if strict and not job.require_independent_review:
        # Strict mode requires independent review by default; an explicit
        # operator opt-out (False) is honoured.
        job.require_independent_review = True if configured_required is None else bool(configured_required)
    if configured_required:
        job.require_independent_review = True
    if job.review is not None:
        job.review.strict = strict
        job.review.strict_reasons = reasons
    await _log(
        job, db, "review",
        f"Review policy: strict={strict} reasons={reasons} "
        f"independent_required={requires_independent_review(job)}",
        data={"event": "REVIEW POLICY", "strict": strict, "reasons": reasons,
              "independent_required": requires_independent_review(job)},
    )

    async def provider_event(event, metadata):
        await _provider_event_logger(job, db, event, metadata)

    await run_review_pipeline(
        job, plan, project, db,
        event_cb=provider_event,
        preferred_provider=preferred_provider,
        baseline_evidence=baseline_evidence,
        reuse_baseline_install=reuse_baseline_install,
    )


async def resume_job(
    job: Job,
    db: AsyncIOMotorDatabase,
    preferred_provider: Optional[str] = None,
    quality_gates: Optional[QualityGates] = None,
) -> Job:
    """Resume a job from its persisted plan and workspace.

    Deterministic and LLM-free for the decision to resume; generation/build/
    verify still use the normal provider layer. Used by the Guardian for
    execution-family and restart recovery.
    """
    if job.plan is None:
        return await run_job(
            job, db, preferred_provider=preferred_provider,
            stack_id=(job.provider_config or {}).get("stack_id"),
            with_media=bool((job.provider_config or {}).get("with_media", True)),
            quality_gates=quality_gates,
        )
    plan = job.plan
    project = workspace.project_dir(job.id)
    artifacts = workspace.artifacts_dir(job.id)
    job.workspace_path = str(project)
    job.build_evidence = job.build_evidence or BuildEvidence()
    _materialize_job_inputs(job, project)

    try:
        mode = job.mode
        work_branch = None
        before_hashes = None
        if mode == "existing-repo":
            from .snapshots import prepare_work_branch
            work_branch = prepare_work_branch(project, job.id)
            before_hashes = hash_tree(project)

        transition(job, JobStatus.GENERATING, context="orchestrator:generating")
        await _run_generation_tasks(job, plan, project, db, preferred_provider)
        await _run_media_stage(job, plan, project, db)

        result = await _build_and_verify_with_gates(
            job, plan, project, artifacts, db, preferred_provider,
        )
        result = await _execute_repair_reverify_loop(
            job, plan, project, artifacts, db, result, preferred_provider,
        )
        await _run_review_stage(
            job, plan, project, artifacts, db, preferred_provider, mode=mode,
        )
        return await _finalize_run(
            job, plan, project, artifacts, db,
            mode=mode, work_branch=work_branch, before_hashes=before_hashes,
            push_changes=bool((job.provider_config or {}).get("push_changes")),
        )
    except asyncio.CancelledError:
        transition(job, JobStatus.CANCELLED, context="orchestrator:cancelled")
        job.error = "Cancelled"
        await save_job(db, job)
        raise
    except Exception as e:  # noqa: BLE001
        transition(job, JobStatus.FAILED, context="orchestrator:unhandled")
        job.error = f"{type(e).__name__}: {e}"
        await _log(job, db, "error", job.error, level="error",
                   data={"trace": traceback.format_exc()[-2000:]})
        await save_job(db, job)
        return job


@traced("GENERATION")
async def _run_generation_tasks(
    job: Job, plan: Plan, project: Path, db: AsyncIOMotorDatabase,
    preferred_provider: Optional[str],
    repo_map: Optional[RepoContextMap] = None,
) -> None:
    from .repo_intelligence import build_repo_map, get_focused_cross_file_context

    if repo_map is None and any(t.kind == "patch" for t in plan.tasks):
        repo_map = build_repo_map(project)

    gen_tasks = [t for t in plan.tasks if t.kind in ("generate", "patch") and t.file_path]
    total = max(1, len(gen_tasks))
    for i, task in enumerate(gen_tasks, start=1):
        # Guardian recovery resumes from persisted state. Tasks already
        # completed by the interrupted run are preserved rather than re-run,
        # so recovery does not redo finished work or fail on a task that had
        # already succeeded before the crash.
        if task.status == "done" and task.file_path:
            p = project / task.file_path
            if p.exists() and p.is_file():
                mark("GENERATION TASK PRESERVED", job_id=job.id, task=i,
                     total=total, path=task.file_path)
                await _log(job, db, "generate",
                           f"[{i}/{total}] preserved {task.file_path}",
                           data={"preserved": True})
                _progress(job, 20 + int(45 * i / total))
                continue
            task.status = "pending"
        task.status = "running"
        task.started_at = datetime.now(timezone.utc).isoformat()
        task.attempts += 1
        kind_label = "patch" if task.kind == "patch" else "generate"
        mark("GENERATION TASK START", job_id=job.id, task=i, total=total, path=task.file_path)
        await _log(job, db, kind_label, f"[{i}/{total}] {task.file_path}")
        try:
            if task.kind == "patch":
                existing_content = ""
                p = project / task.file_path
                if p.exists():
                    try:
                        existing_content = p.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        existing_content = ""

                cross_file_context = ""
                if repo_map:
                    cross_file_context = get_focused_cross_file_context(
                        repo_map, project, task.file_path,
                        query_or_reason=task.description or plan.description,
                    )

                gf = await _generate_patch(
                    plan, task, existing_content, job.files,
                    preferred_provider=preferred_provider, job_id=job.id,
                    cross_file_context=cross_file_context,
                    original_request=job.request,
                )
            else:
                gf = await generate_file(
                    plan, task, job.files,
                    preferred_provider=preferred_provider,
                    original_request=job.request, job_id=job.id,
                )
            before_content = existing_content if task.kind == "patch" else ""
            workspace.safe_write(project, gf.path, gf.content)
            # Record the code-writing authority so a reviewer can never be the
            # provider that authored the latest change.
            record_code_author_from_router(job, "generation")
            mark("FILES WRITTEN", job_id=job.id, path=gf.path, task=i, total=total)
            await _log(job, db, kind_label, f"Wrote {gf.path}",
                       data=_code_change_data(gf.path, before_content, gf.content))
            replaced = False
            for idx, f in enumerate(job.files):
                if f.path == gf.path:
                    job.files[idx] = gf
                    replaced = True
                    break
            if not replaced:
                job.files.append(gf)
            task.status = "done"
            task.finished_at = datetime.now(timezone.utc).isoformat()
            mark("GENERATION TASK COMPLETE", job_id=job.id, task=i, path=task.file_path)
        except Exception as e:  # noqa: BLE001
            task.status = "failed"
            task.last_error = str(e)
            await _log(job, db, kind_label,
                       f"Task {task.file_path} failed: {e}", level="error")
            raise
        _progress(job, 20 + int(45 * i / total))
        await save_job(db, job)


# Providers surface truncation via finish_reason: OpenAI/Gemini/Groq/
# openai-compatible use "length"; Anthropic maps stop_reason "max_tokens".
_TRUNCATION_FINISH_REASONS = {"length", "max_tokens"}

# Anchored refusal/commentary prefixes. A real source file never begins with
# these, so they reliably flag prose/error output that must not overwrite a
# file. Anchoring at the start keeps false positives negligible.
_PROSE_PREFIXES = (
    "i'm sorry", "i am sorry", "sorry,", "i cannot", "i can't", "i can not",
    "i apologize", "i apologise", "as an ai", "unfortunately", "error:",
    "here is", "here's", "sure,", "certainly,", "i'm unable", "i am unable",
)


def _acceptance_requirements_section(plan) -> str:
    """Render the plan's acceptance requirements so a correction honours them."""
    reqs = getattr(plan, "requirements", None) or []
    lines = [
        f"- {getattr(r, 'text', '').strip()}"
        for r in reqs
        if getattr(r, "text", "").strip()
    ]
    if not lines:
        return ""
    return (
        "ACCEPTANCE REQUIREMENTS (all must still hold after the change):\n"
        + "\n".join(lines)
        + "\n\n"
    )


def _full_file_correction_is_usable(
    corrected_text: str,
    existing_content: str,
    finish_reason: Optional[str],
    *,
    enforce_size_floor: bool = False,
) -> bool:
    """Guard a full-file body before it can overwrite an existing source file.

    Rejects (so the caller preserves the original):
      * empty / whitespace-only output,
      * provider-signalled truncation (finish_reason length/max_tokens),
      * prose / refusal / commentary (anchored prefix check),
      * when ``enforce_size_floor`` — a body that collapses a non-trivial file
        to under half its size, which is almost always a truncated or
        degenerate correction rather than a legitimate edit.
    """
    body = (corrected_text or "").strip()
    if not body:
        return False
    if finish_reason and finish_reason.strip().lower() in _TRUNCATION_FINISH_REASONS:
        return False
    if body.lower().startswith(_PROSE_PREFIXES):
        original_start = (existing_content or "").strip().lower()
        if not original_start.startswith(body[:min(len(body), 16)].lower()):
            return False
    if enforce_size_floor:
        existing_body = (existing_content or "").strip()
        if len(existing_body) >= 40 and len(body) < len(existing_body) * 0.5:
            return False
    return True


def _unwrap_standalone_fence(text: str) -> str:
    """Unwrap only a whole-response code fence; otherwise keep bytes unchanged."""
    import re
    match = re.fullmatch(r"```[a-zA-Z0-9_-]*\r?\n([\s\S]*?)\r?\n```[ \t]*\r?\n?", text or "")
    if match:
        return match.group(1)
    return text or ""

def _is_diff_response(text: str) -> bool:
    """Only a standalone unified diff is a patch, not a Markdown example."""
    from .patch_diff import looks_like_unified_diff
    stripped = (text or "").strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1]).strip()
    if not stripped or "```" in stripped:
        return False
    first = stripped.splitlines()[0]
    return first.startswith(("diff --git ", "--- ", "@@ -")) and looks_like_unified_diff(stripped)

async def _generate_patch(
    plan: Plan, task, existing_content: str, all_files,
    preferred_provider: Optional[str], job_id: str,
    cross_file_context: Optional[str] = None,
    original_request: str = "",
) -> GeneratedFile:
    """Generate file contents, applying diffs against an existing file.

    Request one full-file correction if a diff cannot be applied. Raise
    ValueError if that correction or a direct full-file response is unusable,
    so the caller preserves the original file.
    """
    from ..providers.base import CompletionRequest, Message
    from ..providers.router import router as prouter
    from .generator import GENERATOR_SYSTEM, _strip_fences
    from .patch_diff import apply_model_patch, looks_like_unified_diff

    context_section = ""
    if cross_file_context and cross_file_context.strip():
        context_section = (
            f"RELEVANT CROSS-FILE ARCHITECTURAL CONTEXT:\n"
            f"{cross_file_context.strip()}\n\n"
        )

    # A terse task.description can lose intent; carry the authoritative user
    # request and acceptance requirements so neither the patch nor the bounded
    # correction optimises for an abbreviation.
    request_section = ""
    if original_request and original_request.strip():
        request_section = (
            f"ORIGINAL USER REQUEST (authoritative intent):\n"
            f"{original_request.strip()}\n\n"
        )
    acceptance_section = _acceptance_requirements_section(plan)

    has_existing = bool(existing_content)
    if has_existing:
        output_contract = (
            "Return a UNIFIED DIFF that applies to the CURRENT FILE CONTENTS below. "
            "Use exact @@ hunk headers and include enough unchanged context lines for "
            "the hunk to locate uniquely. Change only what the task requires. "
            "Return the diff only — no fences, no commentary. "
            "If a diff is not possible, return the FULL corrected file instead."
        )
    else:
        output_contract = (
            "Return the FULL corrected file contents only. No fences, no commentary."
        )

    prompt = (
        f"PATCH TASK for file: {task.file_path}\n"
        f"Change requested: {task.description}\n"
        f"App: {plan.app_name}\n"
        f"Overall plan description: {plan.description}\n\n"
        f"{request_section}"
        f"{acceptance_section}"
        f"{context_section}"
        f"CURRENT FILE CONTENTS (may be empty if file does not exist yet):\n"
        f"{existing_content or '(file does not exist)'}\n\n"
        f"{output_contract} "
        f"Preserve everything unrelated to the change."
    )
    req = CompletionRequest(
        messages=[Message(role="user", content=prompt)],
        system=GENERATOR_SYSTEM, max_tokens=12000, temperature=0.15,
    )
    resp = await prouter.complete(req, preferred_id=preferred_provider,
                                  job_id=job_id)
    text = _unwrap_standalone_fence(resp.text)
    if has_existing:
        applied = None
        if _is_diff_response(resp.text):
            applied = apply_model_patch(existing_content, resp.text)
        elif _is_diff_response(text):
            applied = apply_model_patch(existing_content, text)
        if applied is not None:
            return GeneratedFile(path=task.file_path, content=applied)
        if _is_diff_response(resp.text) or _is_diff_response(text):
            # The model returned a unified diff that does not apply cleanly.
            # Rather than refusing outright (which kills otherwise-valid
            # follow-up edits), make exactly ONE bounded full-file correction
            # request: re-ask for the COMPLETE corrected file under a strict
            # full-file contract. We still never write a partially-applied
            # patch — if the correction is unusable the original is preserved.
            correction_resp = await _request_full_file_correction(
                plan, task, existing_content, context_section,
                request_section, acceptance_section,
                preferred_provider, job_id,
            )
            correction = correction_resp.text
            corrected_text = _unwrap_standalone_fence(correction)
            if _is_diff_response(corrected_text):
                if (correction_resp.finish_reason or "").strip().lower() in _TRUNCATION_FINISH_REASONS:
                    raise ValueError(
                        f"Patch for {task.file_path} does not apply; bounded "
                        f"full-file correction failed. Original file preserved."
                    )
                # A diff came back again; only accept it if it applies cleanly.
                reapplied = apply_model_patch(existing_content, correction)
                if reapplied is None:
                    reapplied = apply_model_patch(existing_content, corrected_text)
                if reapplied is not None:
                    return GeneratedFile(path=task.file_path, content=reapplied)
                raise ValueError(
                    f"Patch for {task.file_path} does not apply; bounded "
                    f"full-file correction failed. Original file preserved."
                )
            if not _full_file_correction_is_usable(
                corrected_text, existing_content,
                correction_resp.finish_reason, enforce_size_floor=True,
            ):
                # Empty, truncated (provider-signalled or degenerate), or
                # prose/error output must never overwrite an existing file.
                raise ValueError(
                    f"Patch for {task.file_path} does not apply; bounded "
                    f"full-file correction failed. Original file preserved."
                )
            return GeneratedFile(path=task.file_path, content=corrected_text)
        # The model returned a direct full-file body (not a diff) for an
        # existing file. Apply the same safety guard so prose, an error
        # message, or a truncated body can never overwrite the original.
        if not _full_file_correction_is_usable(
            text, existing_content, resp.finish_reason,
            enforce_size_floor=True,
        ):
            raise ValueError(
                f"Patch for {task.file_path}: model returned unusable content "
                f"(truncated or non-source). Original file preserved."
            )
    return GeneratedFile(path=task.file_path, content=text)


async def _request_full_file_correction(
    plan: Plan, task, existing_content: str, context_section: str,
    request_section: str, acceptance_section: str,
    preferred_provider: Optional[str], job_id: str,
):
    """One bounded re-request for the COMPLETE corrected file.

    Used only when the model's unified diff did not apply. We never write a
    partially-applied patch, so instead of refusing outright we give the model
    exactly one chance to return the whole file under a strict full-file
    contract that also carries the original request and acceptance
    requirements. Returns the full CompletionResponse so the caller can inspect
    ``finish_reason`` (truncation) in addition to the text.
    """
    from ..providers.base import CompletionRequest, Message
    from ..providers.router import router as prouter
    from .generator import GENERATOR_SYSTEM

    prompt = (
        f"FULL-FILE CORRECTION for file: {task.file_path}\n"
        f"Your previous unified diff did NOT apply to the current file. "
        f"Return the COMPLETE corrected file contents only — no diff, no "
        f"fences, no commentary. Do not truncate; output the entire file.\n"
        f"Change requested: {task.description}\n"
        f"App: {plan.app_name}\n\n"
        f"{request_section}"
        f"{acceptance_section}"
        f"{context_section}"
        f"CURRENT FILE CONTENTS:\n{existing_content or '(file does not exist)'}\n\n"
        f"Return the full corrected file. Preserve everything unrelated to the "
        f"change and satisfy every acceptance requirement listed above."
    )
    req = CompletionRequest(
        messages=[Message(role="user", content=prompt)],
        system=GENERATOR_SYSTEM, max_tokens=12000, temperature=0.1,
    )
    return await prouter.complete(
        req, preferred_id=preferred_provider, job_id=job_id
    )


async def _execute_repair_reverify_loop(
    job: Job,
    plan: Plan,
    project: Path,
    artifacts: Path,
    db: AsyncIOMotorDatabase,
    result: Optional[VerificationResult],
    preferred_provider: Optional[str],
    baseline_evidence: Optional[BuildEvidence] = None,
) -> Optional[VerificationResult]:
    """Canonical failure -> diagnose -> snapshot -> repair -> reverify -> accept or rollback loop."""
    while not all_passed(job.gates) and job.repair_attempts < job.max_repair_attempts:
        job.repair_attempts += 1
        gates_before = deepcopy(job.gates)
        files_before = deepcopy(job.files)
        evidence_before = deepcopy(job.build_evidence)
        result_before = result
        failing_gates_before = [g.name for g in gates_before if g.status.upper() == "FAIL"]

        attempt = await _diagnose_and_repair(
            job, plan, project, artifacts, db, result, preferred_provider,
        )
        attempt.original_failures = failing_gates_before

        def _rollback_workspace(reason: str) -> None:
            attempt.accepted = False
            attempt.rolled_back = True
            attempt.rollback_reason = reason
            if attempt.snapshot_before:
                restore_snapshot(job.id, attempt.snapshot_before)
            job.files = files_before
            job.gates = gates_before
            job.build_evidence = evidence_before

        if not attempt.diagnosis or not attempt.diagnosis.affected_files:
            attempt.accepted = False
            attempt.rollback_reason = "No actionable modifications suggested by diagnosis"
            job.repair_history.append(attempt)
            await save_job(db, job)
            break

        syntax_err = validate_modified_sources(project, attempt.files_modified)
        if syntax_err:
            _rollback_workspace(f"Invalid syntax introduced by repair: {syntax_err}")
            await _log(job, db, "repair", attempt.rollback_reason, level="warn")
            job.repair_history.append(attempt)
            await save_job(db, job)
            result = result_before
            continue

        # Re-build, run quality gates, start server, and re-verify
        async with stage("REBUILD", job_id=job.id, attempt=job.repair_attempts):
            new_result = await _build_and_verify_with_gates(
                job, plan, project, artifacts, db, preferred_provider,
                baseline_evidence=baseline_evidence,
            )
        failing_gates_after = [g.name for g in job.gates if g.status.upper() == "FAIL"]
        attempt.post_repair_failures = failing_gates_after

        improved, reason = repair_improved(
            gates_before, job.gates, result_before, new_result,
        )
        if all_passed(job.gates):
            improved = True
            reason = "all quality gates passed"

        if not improved:
            _rollback_workspace(reason)
            await _log(
                job, db, "repair",
                f"Repair attempt {attempt.attempt} rejected ({reason}). "
                f"Restored snapshot {attempt.snapshot_before}",
                level="warn",
            )
            job.repair_history.append(attempt)
            await save_job(db, job)
            result = result_before
            continue

        attempt.accepted = True
        attempt.rolled_back = False
        await _log(
            job, db, "repair",
            f"Repair attempt {attempt.attempt} accepted ({reason})",
        )

        job.repair_history.append(attempt)
        await save_job(db, job)
        result = new_result
        if all_passed(job.gates):
            attempt.resolved = True
            break

    return result


@traced("REVERIFY")
async def reverify_job(
    job: Job,
    db: AsyncIOMotorDatabase,
    scenario: List[dict],
    preferred_provider: Optional[str] = None,
) -> Optional[VerificationResult]:
    """Run a supplied acceptance contract against an existing job workspace.

    This is the public lifecycle entry point used after an external or
    controlled source change.  It intentionally performs the normal build,
    runtime startup, browser verification, and gate evaluation, but does not
    repair anything.  Callers can therefore observe and persist the blocked
    state before asking :func:`repair_failed_job` to enter the canonical
    diagnosis/repair loop.
    """
    if not job.plan:
        raise ValueError("cannot reverify a job without a plan")
    project = Path(job.workspace_path or str(workspace.project_dir(job.id)))
    workspace.validate_within_workspace(project)
    job.plan.verification_scenario = [
        step if isinstance(step, VerificationStep) else VerificationStep(**step)
        for step in scenario
    ]
    result = await _build_and_verify_with_gates(
        job, job.plan, project, workspace.artifacts_dir(job.id), db,
        preferred_provider,
    )
    # Single completion authority. A manual re-verification may complete the job
    # only when gates pass and the review layer that was engaged has no
    # unresolved blocking findings; legacy jobs without review keep the
    # pre-review behaviour.
    await finalize_job(job, db, requires_review=job.review is not None)
    await save_job(db, job)
    return result


async def repair_failed_job(
    job: Job,
    db: AsyncIOMotorDatabase,
    preferred_provider: Optional[str] = None,
) -> Job:
    """Diagnose, source-repair, rebuild, and reverify a blocked job.

    The exact ``Plan.verification_scenario`` persisted by ``reverify_job`` is
    reused on every attempt.  Completion is awarded only after all gates pass.
    """
    if not job.plan:
        raise ValueError("cannot repair a job without a plan")
    if all_passed(job.gates):
        raise ValueError("repair requires a job with a failing quality gate")
    project = Path(job.workspace_path or str(workspace.project_dir(job.id)))
    workspace.validate_within_workspace(project)
    result = await _execute_repair_reverify_loop(
        job, job.plan, project, workspace.artifacts_dir(job.id), db,
        job.verification, preferred_provider,
    )
    job.verification = result
    # Deterministic gates alone are not sufficient: a repair must never award
    # completion while the review layer has unresolved blocking findings.
    # Jobs without review evidence (legacy) keep the pre-review behaviour.
    review_ok = job.review is None or review_passed(job)
    if all_passed(job.gates) and review_ok:
        # Git side-effects only for a genuinely completed repair; the terminal
        # status itself is decided by finalize_job below.
        if job.mode == "existing-repo":
            from .snapshots import commit_if_git, push_current_branch
            commit_sha = commit_if_git(project, f"Gold Builder repair: {job.request[:64]}")
            if commit_sha:
                branch = None
                try:
                    import subprocess
                    branch = subprocess.run(
                        ["git", "branch", "--show-current"], cwd=project,
                        capture_output=True, text=True,
                    ).stdout.strip() or None
                except Exception:
                    branch = None
                pushed = False
                if bool((job.provider_config or {}).get("push_changes")):
                    pushed_branch = push_current_branch(project)
                    pushed = bool(pushed_branch)
                    if pushed_branch:
                        branch = pushed_branch
                changed = sorted(set(
                    path
                    for attempt in job.repair_history
                    for path in attempt.files_modified
                ))
                job.version_history.append(VersionRecord(
                    checkpoint_id=f"git-{commit_sha[:12]}",
                    user_request=f"Repair: {job.request}",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    files_changed=changed,
                    validation_result={
                        "gates_passed": True,
                        "browser_passed": bool(job.verification and job.verification.passed),
                    },
                    git_commit_sha=commit_sha,
                    git_branch=branch,
                    git_pushed=pushed,
                ))
                await _log(job, db, "git", f"Committed verified repair at {commit_sha[:12]}")
    # Renormalise through the single completion authority. When the review layer
    # was never engaged (legacy), review is explicitly not required.
    await finalize_job(job, db, requires_review=job.review is not None)
    await save_job(db, job)
    return job


async def run_job(
    job: Job,
    db: AsyncIOMotorDatabase,
    preferred_provider: Optional[str] = None,
    stack_id: Optional[str] = None,
    with_media: bool = True,
    quality_gates: Optional[QualityGates] = None,
) -> Job:
    project = workspace.project_dir(job.id)
    artifacts = workspace.artifacts_dir(job.id)
    job.workspace_path = str(project)
    job.build_evidence = job.build_evidence or BuildEvidence()
    _materialize_job_inputs(job, project)

    try:
        # ---- PLAN ----
        transition(job, JobStatus.PLANNING, context="orchestrator:planning")
        _progress(job, 5)
        await _log(job, db, "plan", f"Planning app: {job.request!r} stack={stack_id or 'auto'}")
        async def provider_event(event, metadata):
            await _provider_event_logger(job, db, event, metadata)
        plan = await build_plan(
            job.request,
            stack_id=stack_id,
            with_media=with_media,
            preferred_provider=preferred_provider,
            provider_event=provider_event,
        )
        if quality_gates:
            plan.quality_gates = quality_gates
        else:
            plan.quality_gates = default_gates(get_stack(plan.stack_id))
        job.plan = plan
        _progress(job, 18)
        await _log(job, db, "plan",
                   f"Plan: {plan.app_name} stack={plan.stack_id} "
                   f"tasks={len(plan.tasks)} images={len(plan.image_specs)} videos={len(plan.video_specs)}",
                   data={"stack_id": plan.stack_id})

        # ---- GENERATE ----
        transition(job, JobStatus.GENERATING, context="orchestrator:generating")
        await _run_generation_tasks(job, plan, project, db, preferred_provider)

        # ---- MEDIA ----
        await _run_media_stage(job, plan, project, db)

        # ---- BUILD + VERIFY + REPAIR LOOP ----
        result = await _build_and_verify_with_gates(
            job, plan, project, artifacts, db, preferred_provider,
        )

        result = await _execute_repair_reverify_loop(
            job, plan, project, artifacts, db, result, preferred_provider,
        )

        await _run_review_stage(
            job, plan, project, artifacts, db, preferred_provider, mode="new",
        )

        return await _finalize_run(job, plan, project, artifacts, db, mode="new")

    except asyncio.CancelledError:
        transition(job, JobStatus.CANCELLED, context="orchestrator:cancelled")
        job.error = "Cancelled"
        await save_job(db, job)
        raise
    except Exception as e:  # noqa: BLE001
        transition(job, JobStatus.FAILED, context="orchestrator:unhandled")
        job.error = f"{type(e).__name__}: {e}"
        await _log(job, db, "error", job.error, level="error",
                   data={"trace": traceback.format_exc()[-2000:]})
        await save_job(db, job)
        return job


async def run_existing_repo_job(
    job: Job,
    db: AsyncIOMotorDatabase,
    source: str,
    preferred_provider: Optional[str] = None,
    quality_gates: Optional[QualityGates] = None,
    push_changes: bool = False,
) -> Job:
    project = workspace.project_dir(job.id)
    artifacts = workspace.artifacts_dir(job.id)
    job.workspace_path = str(project)
    job.mode = "existing-repo"
    job.source = source
    job.build_evidence = BuildEvidence()

    try:
        # ---- INSPECT ----
        transition(job, JobStatus.INSPECTING, context="orchestrator:inspecting")
        _progress(job, 5)
        await _log(job, db, "inspect", f"Cloning/copying source: {source}")
        await clone_or_copy(source, project)
        _materialize_job_inputs(job, project)
        from .snapshots import prepare_work_branch
        work_branch = prepare_work_branch(project, job.id)
        if work_branch:
            await _log(job, db, "git", f"Working on isolated branch {work_branch}")
        before_hashes = hash_tree(project)
        inspected_count = 0
        async def inspection_progress(path: str) -> None:
            nonlocal inspected_count
            inspected_count += 1
            # Keep the live stream useful without flooding persistence on huge repos.
            if inspected_count <= 25 or inspected_count % 20 == 0:
                await _log(job, db, "inspect-file", f"Reading {path}", data={"path": path, "count": inspected_count})
        repo = await inspect(project, on_file=inspection_progress)
        summary = summarize_for_prompt(repo)
        await _log(job, db, "inspect",
                   f"Detected stack={repo.stack_id}, files={len(repo.file_tree)}",
                   data={"stack_id": repo.stack_id})
        _progress(job, 18)

        # ---- PLAN (patch) ----
        transition(job, JobStatus.PLANNING, context="orchestrator:planning")
        async def provider_event(event, metadata):
            await _provider_event_logger(job, db, event, metadata)
        plan = await build_patch_plan(job.request, summary,
                                      preferred_provider=preferred_provider,
                                      provider_event=provider_event)
        if plan.stack_id != repo.stack_id:
            await _log(
                job, db, "inspect",
                f"Using inspected stack {repo.stack_id} instead of planner guess {plan.stack_id}",
                level="info",
            )
            plan.stack_id = repo.stack_id
        if quality_gates:
            plan.quality_gates = quality_gates
        else:
            plan.quality_gates = default_gates(get_stack(plan.stack_id))
        job.plan = plan
        await _log(job, db, "plan",
                   f"Patch plan: {len(plan.tasks)} tasks stack={plan.stack_id}")
        _progress(job, 28)

        # A read-only / audit request has no browser-verifiable behaviour, so it
        # terminates through the governed read-only finalizer (one completion
        # authority) instead of the code-generation gate.
        if read_only_request(job.request):
            discarded = bool(plan.tasks)
            plan.tasks = []
            log_message = (
                "Read-only audit request: planner tasks discarded; no source changes applied."
                if discarded
                else "Read-only audit completed; no source changes were requested or planned."
            )
            return await _finalize_read_only_audit(
                job, db, reason="read_only_audit", log_message=log_message,
            )

        # A mutating request whose planner produced no tasks is a completion
        # FAILURE, never a success. Awarding COMPLETED here was the zero-task
        # false-completion bug: the user asked for a change and nothing changed.
        if not plan.tasks:
            await _log(
                job, db, "plan",
                "Planner produced no tasks for a mutating request; refusing to "
                "report completion.",
                level="error",
            )
            transition(job, JobStatus.FAILED, context="orchestrator:zero_task")
            job.error = "planner produced no tasks for a mutating request; no changes were planned"
            _progress(job, 100)
            await save_job(db, job)
            return job

        # ---- PRE-CHANGE BASELINE ----
        # Existing repositories can already contain unrelated pipeline/runtime errors.
        # Capture those before any source edit so later verification blocks only
        # regressions introduced by Gold Builder while preserving strict
        # requirement/browser assertions for the requested change.
        baseline_evidence = BuildEvidence()
        try:
            stack = get_stack(plan.stack_id)
            baseline_ready = True
            if stack.install_pipeline:
                baseline_evidence.install = await run_pipeline(
                    "baseline-install", stack.install_pipeline, project, timeout=420
                )
                baseline_ready = bool(baseline_evidence.install and baseline_evidence.install[-1].rc == 0)
            if stack.build_pipeline:
                baseline_evidence.build = await run_pipeline(
                    "baseline-build", stack.build_pipeline, project, timeout=420
                )
                if baseline_ready:
                    baseline_ready = bool(baseline_evidence.build and baseline_evidence.build[-1].rc == 0)
            if stack.typecheck_pipeline:
                baseline_evidence.typecheck = await run_pipeline(
                    "baseline-typecheck", stack.typecheck_pipeline, project, timeout=300
                )
            if stack.lint_pipeline:
                baseline_evidence.lint = await run_pipeline(
                    "baseline-lint", stack.lint_pipeline, project, timeout=300
                )
            if stack.test_pipeline:
                baseline_evidence.test = await run_pipeline(
                    "baseline-test", stack.test_pipeline, project, timeout=300
                )
            await _log(
                job, db, "baseline",
                "Captured pre-change pipeline baseline",
                data={
                    "build_rc": (baseline_evidence.build[-1].rc if baseline_evidence.build else None),
                    "typecheck_rc": (baseline_evidence.typecheck[-1].rc if baseline_evidence.typecheck else None),
                    "lint_rc": (baseline_evidence.lint[-1].rc if baseline_evidence.lint else None),
                    "test_rc": (baseline_evidence.test[-1].rc if baseline_evidence.test else None),
                },
            )
            if baseline_ready:
                baseline_server = await start_stack_server(stack, project, artifacts)
                try:
                    job.baseline_verification = await verify_url(
                        baseline_server.url,
                        artifacts / "baseline",
                        scenario=[{"action": "wait", "args": {"ms": 100}}],
                        project_dir=project,
                        app_requirements="",
                    )
                    await _log(
                        job, db, "baseline",
                        "Captured pre-change runtime baseline",
                        data={
                            "network_errors": job.baseline_verification.network_errors,
                            "console_errors": job.baseline_verification.console_errors,
                            "page_errors": job.baseline_verification.page_errors,
                        },
                    )
                finally:
                    await baseline_server.stop()
        except Exception as baseline_exc:  # noqa: BLE001
            job.baseline_verification = None
            await _log(
                job, db, "baseline",
                f"Pre-change runtime baseline unavailable: {baseline_exc}",
                level="warn",
            )

        # ---- REPO INTELLIGENCE & APPLY PATCHES ----
        dependency_fingerprint_before = _dependency_fingerprint(project)
        repo_map = build_repo_map(project)
        transition(job, JobStatus.GENERATING, context="orchestrator:generating")
        await _run_generation_tasks(job, plan, project, db, preferred_provider, repo_map=repo_map)
        await _run_media_stage(job, plan, project, db)
        dependency_fingerprint_after = _dependency_fingerprint(project)
        reuse_baseline_install = bool(
            dependency_fingerprint_before
            and dependency_fingerprint_before == dependency_fingerprint_after
            and baseline_evidence.install
            and baseline_evidence.install[-1].rc == 0
        )
        if reuse_baseline_install:
            await _log(
                job, db, "install",
                "Dependency manifests unchanged; reusing successful pre-change install.",
            )

        # ---- BUILD + VERIFY + REPAIR ----
        result = await _build_and_verify_with_gates(
            job, plan, project, artifacts, db, preferred_provider,
            baseline_evidence=baseline_evidence,
            reuse_baseline_install=reuse_baseline_install,
        )

        result = await _execute_repair_reverify_loop(
            job, plan, project, artifacts, db, result, preferred_provider,
            baseline_evidence=baseline_evidence,
        )

        await _run_review_stage(
            job, plan, project, artifacts, db, preferred_provider,
            mode="existing-repo", baseline_evidence=baseline_evidence,
            reuse_baseline_install=reuse_baseline_install,
        )

        return await _finalize_run(
            job, plan, project, artifacts, db,
            mode="existing-repo", work_branch=work_branch,
            before_hashes=before_hashes, push_changes=push_changes,
        )

    except asyncio.CancelledError:
        transition(job, JobStatus.CANCELLED, context="orchestrator:cancelled")
        job.error = "Cancelled"
        await save_job(db, job)
        raise
    except Exception as e:  # noqa: BLE001
        transition(job, JobStatus.FAILED, context="orchestrator:unhandled")
        job.error = f"{type(e).__name__}: {e}"
        await _log(job, db, "error", job.error, level="error",
                   data={"trace": traceback.format_exc()[-2000:]})
        await save_job(db, job)
        return job


async def _build_and_verify_with_gates(
    job, plan, project, artifacts, db, preferred_provider,
    baseline_evidence: Optional[BuildEvidence] = None,
    reuse_baseline_install: bool = False,
) -> Optional[VerificationResult]:
    stack = get_stack(plan.stack_id)
    ev = job.build_evidence or BuildEvidence()
    verification: Optional[VerificationResult] = None

    async def _run(phase_status, phase_label, pipeline, attr, timeout):
        if not pipeline:
            return True
        transition(job, phase_status, context="orchestrator:pipeline_phase")
        await _log(job, db, phase_label, f"Running {phase_label} pipeline",
                   data={"kind": "command_start", "commands": pipeline, "timeout_s": timeout})
        async with stage(phase_label.upper(), job_id=job.id, timeout_s=timeout):
            results = await run_pipeline(phase_label, pipeline, project, timeout=timeout)
        mark(phase_label.upper() + " RESULT", job_id=job.id, passed=not results or results[-1].rc == 0)
        setattr(ev, attr, results)
        for r in results:
            msg = f"{' '.join(r.cmd)} rc={r.rc}"
            if r.rc and r.output_tail:
                msg = f"{msg}\n{r.output_tail}"
            await _log(job, db, phase_label, msg,
                       level="error" if r.rc else "info",
                       data={"kind": "command_result", "command": r.cmd, "rc": r.rc,
                             "output": r.output_tail or ""})
        job.build_evidence = ev
        await save_job(db, job)
        return not results or results[-1].rc == 0

    _progress(job, 72)
    if reuse_baseline_install and baseline_evidence and baseline_evidence.install:
        ev.install = list(baseline_evidence.install)
        job.build_evidence = ev
        install_ok = bool(ev.install and ev.install[-1].rc == 0)
        await _log(
            job, db, "install",
            "Skipped duplicate install because dependency manifests are unchanged.",
        )
        await save_job(db, job)
    else:
        install_ok = await _run(JobStatus.INSTALLING, "install",
                                stack.install_pipeline, "install", 420)
    if install_ok:
        _progress(job, 78)
        build_ok = await _run(JobStatus.BUILDING, "build",
                              stack.build_pipeline, "build", 420)
        if build_ok:
            await _run(JobStatus.TYPECHECKING, "typecheck",
                       stack.typecheck_pipeline, "typecheck", 300)
            await _run(JobStatus.LINTING, "lint",
                       stack.lint_pipeline, "lint", 300)
            await _run(JobStatus.TESTING, "test",
                       stack.test_pipeline, "test", 300)

    # verify only if install + build both passed (else pointless)
    from .quality_gates import _baseline_matches
    install_ok_for_runtime = (
        not stack.install_pipeline or (ev.install and ev.install[-1].rc == 0)
    )
    build_ok_for_runtime = (
        not stack.build_pipeline
        or (ev.build and ev.build[-1].rc == 0)
        or _baseline_matches(ev.build, baseline_evidence.build if baseline_evidence else [])
    )
    ok_so_far = install_ok_for_runtime and build_ok_for_runtime
    if ok_so_far:
        transition(job, JobStatus.STARTING, context="orchestrator:starting")
        _progress(job, 88)
        startup_ok = False
        try:
            mark("SERVER START", job_id=job.id)
            server = await start_stack_server(stack, project, artifacts)
            mark("SERVER READY", job_id=job.id)
            startup_ok = True
        except Exception as e:  # noqa: BLE001
            mark("SERVER ERROR", job_id=job.id, error_type=type(e).__name__)
            startup_ok = False
            verification = VerificationResult(
                passed=False, error=f"server failed to start: {e}",
                console_errors=[str(e)],
            )
        else:
            retained = False
            try:
                transition(job, JobStatus.VERIFYING, context="orchestrator:verifying")
                _progress(job, 93)
                # Analyze application and build application-specific scenario.
                # Persist the exact contract so manual re-verification and repair
                # execute the same acceptance criteria.
                try:
                    scenario = ([s.model_dump() for s in plan.verification_scenario]
                                if plan.verification_scenario else
                                plan_verification_scenario(project_dir=project, plan=plan,
                                    app_requirements=job.request))
                    if scenario:
                        plan.verification_scenario = [
                            s if isinstance(s, VerificationStep) else VerificationStep(**s)
                            for s in scenario
                        ]
                    await _log(job, db, "verify_plan",
                               f"Generated application-specific verification scenario ({len(scenario or [])} steps)",
                               data={"scenario": scenario or []})
                except Exception as ex_sc:
                    scenario = None
                    await _log(job, db, "verify_plan", f"Verification planning fallback: {ex_sc}", level="warn")

                async with stage("REVERIFY" if job.repair_attempts else "VERIFY", job_id=job.id):
                    verification = await verify_url(
                        server.url,
                        artifacts,
                        scenario=scenario,
                        project_dir=project,
                        plan=plan,
                        app_requirements=job.request,
                        runtime_baseline=(job.baseline_verification if job.mode == "existing-repo" else None),
                    )
                job.verification = verification
                await _log(job, db, "verify",
                           f"passed={verification.passed} "
                           f"status={verification.http_status}",
                           data=verification.model_dump())

                # Keep the exact server that was verified. This guarantees Live
                # Preview refers to the same runtime/browser evidence. A later
                # repair pass replaces this preview atomically.
                info = await preview_manager.adopt(job.id, stack, server)
                job.preview = info
                retained = True
            finally:
                if not retained:
                    await server.stop()

    # Evaluate gates
    job.gates = evaluate(
        ev, verification, plan.quality_gates, stack=stack,
        startup_ok=locals().get("startup_ok", None),
        baseline_ev=baseline_evidence,
    )
    for g in job.gates:
        await _log(job, db, "gate",
                   f"{g.name}: {g.status} (enabled={g.enabled}, blocking={g.blocking})",
                   level="error" if g.blocking else "info")
    await save_job(db, job)
    return verification


async def _diagnose_and_repair(
    job, plan, project, artifacts, db, verification, preferred_provider,
) -> RepairAttempt:
    transition(job, JobStatus.DIAGNOSING, context="orchestrator:diagnosing")
    await _log(job, db, "diagnose",
               f"Attempt {job.repair_attempts}/{job.max_repair_attempts}")

    # Build diagnostic context from evidence
    ev = job.build_evidence or BuildEvidence()
    failing_stage = "verify"
    stdout_tail = ""
    for phase_name, results in (
        ("install", ev.install), ("build", ev.build),
        ("typecheck", ev.typecheck), ("lint", ev.lint),
        ("test", ev.test),
    ):
        if results and results[-1].rc != 0:
            failing_stage = phase_name
            stdout_tail = results[-1].output_tail
            break

    dependency_conflicts_block = ""
    if failing_stage == "install" and is_eresolve(stdout_tail):
        dependency_conflicts_block = format_conflicts(parse_eresolve(stdout_tail))

    console_errors = list(verification.console_errors) if verification else []
    network_errors = list(verification.network_errors) if verification else []
    failed_step = None
    if verification and verification.steps:
        for s in verification.steps:
            if not s.ok:
                failed_step = f"{s.action}({s.args}): {s.error}"
                break

    file_paths = [f.path for f in job.files]
    # Read evidence from disk rather than trusting generation-time copies.
    # This matters for runtime regressions and controlled defects introduced
    # after the original generation completed.
    snippets = {}
    for f in job.files[:8]:
        try:
            content = workspace.safe_read_text(project, f.path)
        except (FileNotFoundError, OSError, ValueError):
            content = f.content
        if len(content) > 16000:
            content = (content[:8000] + "\n[Context excerpt: middle omitted; original file is complete]\n"
                       + content[-8000:])
        snippets[f.path] = content

    repo_map = build_repo_map(project)

    ctx = DiagnosticContext(
        plan=plan, stage=failing_stage, original_request=job.request,
        stdout_tail=stdout_tail, stderr_tail="",
        console_errors=console_errors, network_errors=network_errors,
        failed_step=failed_step,
        file_paths=file_paths, file_snippets=snippets,
        repo_map=repo_map,
        dependency_conflicts=dependency_conflicts_block,
    )

    # Snapshot before making changes
    snap = make_snapshot(job.id, label=f"before-repair-{job.repair_attempts}")
    job.snapshots.append(snap)

    attempt = RepairAttempt(
        attempt=job.repair_attempts, stage=failing_stage,
        snapshot_before=snap.id,
    )

    # Try a deterministic package.json correction first when npm gives an
    # actionable direct peer range. The existing rebuild/gate policy remains
    # authoritative and rolls this back if it does not measurably improve.
    if dependency_conflicts_block and job.repair_attempts == 1:
        import json
        package_json = project / "package.json"
        try:
            manifest = json.loads(package_json.read_text(encoding="utf-8"))
            repaired_manifest, manifest_changes = propose_manifest_peer_repair(
                manifest, parse_eresolve(stdout_tail),
            )
        except (OSError, ValueError, TypeError):
            repaired_manifest, manifest_changes = {}, []
        if manifest_changes:
            serialized_manifest = json.dumps(
                repaired_manifest, indent=2, ensure_ascii=False,
            ) + "\n"
            before_manifest = package_json.read_text(encoding="utf-8")
            workspace.safe_write(project, "package.json", serialized_manifest)
            await _log(job, db, "repair", "Updated package.json",
                       data=_code_change_data("package.json", before_manifest, serialized_manifest))
            replacement = GeneratedFile(path="package.json", content=serialized_manifest)
            for idx, generated in enumerate(job.files):
                if generated.path == "package.json":
                    job.files[idx] = replacement
                    break
            else:
                job.files.append(replacement)
            attempt.diagnosis = RepairPlan(
                root_cause="npm ERESOLVE direct peer-dependency conflict",
                affected_files=["package.json"],
                modifications=[{"path": "package.json", "reason": "; ".join(manifest_changes)}],
            )
            attempt.files_modified = ["package.json"]
            await _log(
                job, db, "repair",
                "Applied deterministic npm peer repair: " + "; ".join(manifest_changes),
            )
            return attempt

    try:
        plan_repair = await diagnose(ctx, preferred_provider=preferred_provider)
        attempt.diagnosis = plan_repair
        await _log(job, db, "diagnose",
                   f"root_cause: {plan_repair.root_cause[:200]}",
                   data={"affected_files": plan_repair.affected_files})
    except Exception as e:  # noqa: BLE001
        await _log(job, db, "diagnose", f"diagnosis failed: {e}", level="error")
        return attempt

    # Apply modifications file-by-file
    transition(job, JobStatus.REPAIRING, context="orchestrator:repairing")
    mark("REPAIR START", job_id=job.id, attempt=job.repair_attempts)
    from ..providers.base import CompletionRequest, Message
    from ..providers.router import router as prouter
    from .generator import GENERATOR_SYSTEM, _strip_fences

    for mod in plan_repair.modifications[:6]:
        target = mod.get("path")
        reason = mod.get("reason", plan_repair.root_cause)
        if not target:
            continue
        # Read existing content
        try:
            existing = workspace.safe_read_text(project, target)
        except FileNotFoundError:
            existing = ""
        except Exception:  # noqa: BLE001
            existing = ""

        from .repo_intelligence import get_focused_cross_file_context
        cross_ctx = get_focused_cross_file_context(repo_map, project, target, query_or_reason=reason)
        ctx_section = f"RELEVANT CROSS-FILE CONTEXT:\n{cross_ctx}\n\n" if cross_ctx.strip() else ""

        acceptance_contract = ""
        if plan.verification_scenario:
            acceptance_contract = (
                "FULL ACCEPTANCE CONTRACT — preserve/fix the application so ALL "
                "steps can pass, not just the first failed step:\n"
                + "\n".join(f"- {s.action}: {s.args}" for s in plan.verification_scenario)
                + "\n\n"
            )
        prompt = (
            f"ORIGINAL USER REQUEST:\n{job.request}\n\n"
            f"OBSERVED FAILURE:\n{failed_step or stdout_tail}\n\n"
            f"REPAIR TASK — root cause: {plan_repair.root_cause}\n"
            f"file: {target}\n"
            f"change: {reason}\n\n"
            f"{acceptance_contract}"
            f"{ctx_section}"
            f"CURRENT FILE:\n{existing or '(file does not exist)'}\n\n"
            f"Return the FULL corrected file contents only. No fences. "
            f"Repair the root cause comprehensively while preserving working behaviour."
        )
        req = CompletionRequest(
            messages=[Message(role="user", content=prompt)],
            system=GENERATOR_SYSTEM, max_tokens=12000, temperature=0.15,
        )
        try:
            resp = await prouter.complete(req, preferred_id=preferred_provider,
                                          job_id=job.id)
            content = _strip_fences(resp.text)
            syntax_err = validate_source_syntax(target, content)
            if syntax_err:
                await _log(job, db, "repair",
                           f"rejected invalid syntax for {target}: {syntax_err}",
                           level="warn")
                continue
            workspace.safe_write(project, target, content)
            record_code_author_from_router(job, "verification_repair")
            mark("FILES WRITTEN", job_id=job.id, path=target, phase="repair")
            await _log(job, db, "repair", f"Updated {target}",
                       data=_code_change_data(target, existing, content))
            # update tracked files
            found = False
            for idx, f in enumerate(job.files):
                if f.path == target:
                    job.files[idx] = GeneratedFile(path=target, content=content)
                    found = True
                    break
            if not found:
                job.files.append(GeneratedFile(path=target, content=content))
            attempt.files_modified.append(target)
        except Exception as e:  # noqa: BLE001
            await _log(job, db, "repair",
                       f"failed to repair {target}: {e}", level="error")

    mark("REPAIR COMPLETE", job_id=job.id, files_modified=len(attempt.files_modified))
    await _log(job, db, "repair",
               f"modified {len(attempt.files_modified)} file(s)",
               data={"files": attempt.files_modified})
    return attempt


from .repo_intelligence import build_repo_map, select_relevant_context
from .snapshots import restore as restore_snapshot, commit_if_git
from ..models import VersionRecord

async def iterate_job(
    job: Job,
    continuation_request: str,
    db: AsyncIOMotorDatabase,
    preferred_provider: Optional[str] = None,
) -> Job:
    """Continue an existing generated project with new requirements preserving existing workspace."""
    project = Path(job.workspace_path or str(workspace.project_dir(job.id)))
    # Strict boundary check
    workspace.validate_within_workspace(project)
    artifacts = workspace.artifacts_dir(job.id)

    # 1. Take a checkpoint snapshot before modification
    snap = make_snapshot(job.id, label=f"pre-iteration-{len(job.version_history) + 1}")
    job.snapshots.append(snap)
    
    # 2. Repository intelligence mapping
    repo_map = build_repo_map(project)
    relevant_files = select_relevant_context(repo_map, project, continuation_request)

    await _log(job, db, "iterate", f"Continuing project: {continuation_request!r}", data={"relevant_files": list(relevant_files.keys())})
    
    # 3. Plan modifications
    before_hashes = hash_tree(project)
    repo = await inspect(project)
    summary = summarize_for_prompt(repo)
    
    plan = await build_patch_plan(continuation_request, summary, preferred_provider=preferred_provider)
    if plan.stack_id == "html-static" and repo.stack_id != "html-static":
        plan.stack_id = repo.stack_id
    plan.quality_gates = default_gates(get_stack(plan.stack_id))
    job.plan = plan

    # 4. Apply changes
    await _run_generation_tasks(job, plan, project, db, preferred_provider, repo_map=repo_map)
    await _run_media_stage(job, plan, project, db)

    # 5. Build and verify
    result = await _build_and_verify_with_gates(job, plan, project, artifacts, db, preferred_provider)

    # 6. Repair loop if gates failed; rollback if worse
    initial_passed = sum(1 for g in job.gates if g.status == "passed")
    result = await _execute_repair_reverify_loop(job, plan, project, artifacts, db, result, preferred_provider)

    # 6b. Mandatory review pipeline before an iteration is considered complete.
    await _run_review_stage(
        job, plan, project, artifacts, db, preferred_provider, mode=job.mode,
    )

    after_hashes = hash_tree(project)
    changes = diff(before_hashes, after_hashes)
    changed_file_names = list(changes.modified.keys()) + list(changes.created.keys())
    
    # Git commit if available
    git_sha = commit_if_git(project, f"Iteration: {continuation_request}")

    # Record version history
    v_rec = VersionRecord(
        checkpoint_id=snap.id,
        user_request=continuation_request,
        timestamp=datetime.now(timezone.utc).isoformat(),
        files_changed=changed_file_names,
        validation_result={
            "passed": all_passed(job.gates) and review_passed(job),
            "gates": [g.model_dump() for g in job.gates],
            "review": review_verdict(job) if job.review else "not_run",
        },
        git_commit_sha=git_sha,
    )
    job.version_history.append(v_rec)

    # 6c. Final authority: deterministic gates AND review pass. An iteration
    # that fails review must never be recorded as a completed version.
    await finalize_job(job, db)

    # 7. Restart preview if running
    try:
        await preview_manager.stop(job.id)
        info = await preview_manager.start(job.id, get_stack(plan.stack_id))
        job.preview = info
        await _log(job, db, "preview", f"Preview restarted at {info.internal_url}")
    except Exception as e:
        await _log(job, db, "preview", f"Preview restart notice: {e}", level="info")

    await save_job(db, job)
    return job
