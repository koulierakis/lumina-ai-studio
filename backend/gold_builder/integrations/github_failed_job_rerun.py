"""Strict controller for one narrowly-scoped GitHub Actions write.

The only permitted write is:
POST /repos/koulierakis/gold-builder-engine/actions/jobs/{job_id}/rerun

PostgreSQL is authoritative for the retry budget.  If it is unavailable the
controller fails closed; there is deliberately no local/in-memory fallback.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import requests

ALLOWED_REPOSITORY = "koulierakis/gold-builder-engine"
MAX_AUTOMATIC_RERUNS = 2
EXHAUSTED = "AUTO_RERUN_EXHAUSTED — DIAGNOSIS_REQUIRED"
_API = "https://api.github.com"
_RERUN_RE = re.compile(r"^/repos/koulierakis/gold-builder-engine/actions/jobs/([0-9]+)/rerun$")
_TABLE = "gold_builder_github_reruns"


class RerunPolicyError(RuntimeError):
    pass


class DurableStorageUnavailable(RerunPolicyError):
    pass


@dataclass(frozen=True)
class FailureEvidence:
    repository: str
    commit_sha: str
    workflow_run_id: int
    job_id: int
    workflow_name: str
    job_name: str
    failed_step: str
    error_text: str
    reason: str


@dataclass
class RerunDecision:
    state: str
    fingerprint: str
    attempt_number: Optional[int] = None
    diagnostic_envelope: Optional[dict[str, Any]] = None
    github_result: Optional[dict[str, Any]] = None


def _database_url() -> str:
    return (os.environ.get("JOB_DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()


def _normalize_error(value: str) -> str:
    value = value.lower()
    value = re.sub(r"\b\d{4}-\d\d-\d\d[t ][0-9:.+z-]+\b", "<timestamp>", value)
    value = re.sub(r"/home/runner/work/[^\s:]+", "<runner-path>", value)
    value = re.sub(r"\b(?:run|job|attempt)[-_ ]?id[:= ]+\d+\b", "<volatile-id>", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:8000]


def failure_fingerprint(e: FailureEvidence) -> str:
    payload = {
        "repository": e.repository,
        "commit_sha": e.commit_sha.lower(),
        "workflow_name": e.workflow_name.strip(),
        "job_name": e.job_name.strip(),
        "failed_step": e.failed_step.strip(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _assert_allowed_write(method: str, path: str, job_id: int) -> None:
    match = _RERUN_RE.fullmatch(path)
    if method.upper() != "POST" or not match or int(match.group(1)) != int(job_id):
        raise RerunPolicyError("GitHub write endpoint is not allowlisted")


def _headers(token: str) -> dict[str, str]:
    if not token:
        raise RerunPolicyError("GitHub token unavailable")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get_json(path: str, token: str, http=requests) -> dict[str, Any]:
    r = http.get(_API + path, headers=_headers(token), timeout=20)
    if not r.ok:
        raise RerunPolicyError(f"GitHub read failed: {r.status_code}")
    return r.json()


def _verify_preflight(e: FailureEvidence, token: str, http=requests) -> None:
    if e.repository != ALLOWED_REPOSITORY:
        raise RerunPolicyError("repository not allowlisted")
    run = _get_json(f"/repos/{ALLOWED_REPOSITORY}/actions/runs/{e.workflow_run_id}", token, http)
    if str(run.get("head_sha", "")).lower() != e.commit_sha.lower():
        raise RerunPolicyError("commit SHA mismatch")
    if e.workflow_name and run.get("name") != e.workflow_name:
        raise RerunPolicyError("workflow identity mismatch")
    jobs = _get_json(f"/repos/{ALLOWED_REPOSITORY}/actions/runs/{e.workflow_run_id}/jobs?filter=latest&per_page=100", token, http)
    job = next((j for j in jobs.get("jobs", []) if int(j.get("id", -1)) == int(e.job_id)), None)
    if not job:
        raise RerunPolicyError("job does not belong to verified workflow run")
    if job.get("status") != "completed" or job.get("conclusion") != "failure":
        raise RerunPolicyError("job is not completed with conclusion=failure")
    if e.job_name and job.get("name") != e.job_name:
        raise RerunPolicyError("job identity mismatch")
    failed_steps = [s.get("name") for s in job.get("steps", []) if s.get("conclusion") == "failure"]
    if e.failed_step and e.failed_step not in failed_steps:
        raise RerunPolicyError("failed-step identity mismatch")


def _init_ledger(cur) -> None:
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            failure_fingerprint TEXT NOT NULL,
            attempt_number INTEGER NOT NULL CHECK (attempt_number BETWEEN 1 AND 2),
            repository TEXT NOT NULL,
            commit_sha TEXT NOT NULL,
            workflow_run_id BIGINT NOT NULL,
            job_id BIGINT NOT NULL,
            reason TEXT NOT NULL,
            state TEXT NOT NULL,
            requested_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ NULL,
            github_result JSONB NULL,
            PRIMARY KEY (failure_fingerprint, attempt_number)
        )
    """)


def _reserve_attempt(url: str, e: FailureEvidence, fingerprint: str) -> Optional[int]:
    try:
        import psycopg
        with psycopg.connect(url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                _init_ledger(cur)
                # Transaction-scoped advisory lock serializes all workers for this failure.
                cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (fingerprint,))
                cur.execute(
                    f"SELECT COALESCE(MAX(attempt_number), 0) FROM {_TABLE} WHERE failure_fingerprint=%s",
                    (fingerprint,),
                )
                used = int(cur.fetchone()[0])
                if used >= MAX_AUTOMATIC_RERUNS:
                    conn.commit()
                    return None
                attempt = used + 1
                cur.execute(
                    f"""INSERT INTO {_TABLE}
                    (failure_fingerprint, attempt_number, repository, commit_sha,
                     workflow_run_id, job_id, reason, state, requested_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (fingerprint, attempt, e.repository, e.commit_sha, e.workflow_run_id,
                     e.job_id, e.reason, "RESERVED", datetime.now(timezone.utc)),
                )
            conn.commit()
        return attempt
    except Exception as exc:
        raise DurableStorageUnavailable("durable PostgreSQL rerun ledger unavailable") from exc


def _finish_attempt(url: str, fingerprint: str, attempt: int, state: str, result: dict[str, Any]) -> None:
    try:
        import psycopg
        with psycopg.connect(url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""UPDATE {_TABLE} SET state=%s, completed_at=%s, github_result=%s::jsonb
                        WHERE failure_fingerprint=%s AND attempt_number=%s""",
                    (state, datetime.now(timezone.utc), json.dumps(result), fingerprint, attempt),
                )
            conn.commit()
    except Exception as exc:
        raise DurableStorageUnavailable("could not durably record rerun result") from exc


def diagnostic_envelope(e: FailureEvidence, fingerprint: str, state: str) -> dict[str, Any]:
    return {
        "kind": "github_actions_failure",
        "state": state,
        "repository": e.repository,
        "commit_sha": e.commit_sha,
        "workflow_run_id": e.workflow_run_id,
        "job_id": e.job_id,
        "workflow_name": e.workflow_name,
        "job_name": e.job_name,
        "failed_step": e.failed_step,
        "normalized_error": _normalize_error(e.error_text),
        "failure_fingerprint": fingerprint,
        "automatic_rerun_limit": MAX_AUTOMATIC_RERUNS,
        "next_action": "diagnose_repair" if state == EXHAUSTED else "verify_rerun",
    }


def rerun_failed_job(
    evidence: FailureEvidence,
    *,
    github_token: str,
    database_url: Optional[str] = None,
    http=requests,
    reserve_attempt: Callable[[str, FailureEvidence, str], Optional[int]] = _reserve_attempt,
    finish_attempt: Callable[[str, str, int, str, dict[str, Any]], None] = _finish_attempt,
) -> RerunDecision:
    """Verify, reserve durably, then perform the single allowlisted GitHub write."""
    _verify_preflight(evidence, github_token, http)
    fingerprint = failure_fingerprint(evidence)
    url = database_url if database_url is not None else _database_url()
    if not url:
        raise DurableStorageUnavailable("durable PostgreSQL rerun ledger is required")

    attempt = reserve_attempt(url, evidence, fingerprint)
    if attempt is None:
        return RerunDecision(
            state=EXHAUSTED,
            fingerprint=fingerprint,
            diagnostic_envelope=diagnostic_envelope(evidence, fingerprint, EXHAUSTED),
        )

    path = f"/repos/{ALLOWED_REPOSITORY}/actions/jobs/{evidence.job_id}/rerun"
    _assert_allowed_write("POST", path, evidence.job_id)
    response = http.post(_API + path, headers=_headers(github_token), timeout=20)
    result = {"status_code": response.status_code, "ok": bool(response.ok)}
    state = "RERUN_REQUESTED" if response.ok else "RERUN_REQUEST_FAILED"
    finish_attempt(url, fingerprint, attempt, state, result)
    return RerunDecision(
        state=state,
        fingerprint=fingerprint,
        attempt_number=attempt,
        github_result=result,
        diagnostic_envelope=diagnostic_envelope(evidence, fingerprint, state),
    )
