"""LLM-driven diagnostic pipeline.

Given a `DiagnosticContext` (failed pipeline stage, stdout/stderr, browser
evidence, list of source files), asks the LLM for a JSON `RepairPlan`:

    {
      "root_cause": "...",
      "affected_files": ["path1", "path2"],
      "modifications": [
        {"path": "...", "reason": "...", "new_content": "..." (optional)}
      ]
    }

Callers then read each affected file, ask the generator to produce the
full corrected content, write the changes, and re-run the pipeline. This
replaces the simplistic keyword heuristic in `repair.py`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import List, Optional

from ..models import GeneratedFile, Plan, RepairPlan
from .repo_intelligence import RepoContextMap, format_repo_architecture_summary
from ..providers.base import CompletionRequest, Message
from ..providers.router import router
from ..progress import traced


DIAGNOSTIC_SYSTEM = """You are the diagnostic layer of Gold Builder AI.
You receive:
- the current stack + plan summary
- the failing pipeline stage
- stdout / stderr from failing commands
- browser console errors, page errors, failed network requests
- the failed verification step (if any)
- the list of source files in the generated project

Your job: identify the ROOT CAUSE, name the FILES most likely at fault,
and describe the exact modifications required. Return STRICT JSON only:

{
  "root_cause": "one short paragraph explaining the underlying problem",
  "affected_files": ["path/to/file1", "path/to/file2"],
  "modifications": [
    {"path": "path/to/file1", "reason": "concrete edit description"}
  ]
}

Rules:
- affected_files must be files that already exist in the project OR that
  legitimately need to be created to fix the issue.
- Prefer editing the smallest number of files.
- When a full acceptance contract is supplied, inspect it as a whole. A browser
  run may stop at the first failed step; repair all clearly related missing
  controls/hooks/behaviours in the affected file in one coherent change rather
  than fixing only the first missing selector.
- If create succeeds before reload but the item disappears after reload, treat
  persistence logic as the primary suspect. In React, specifically check for the
  anti-pattern where one mount effect loads localStorage while another effect
  immediately persists the initial empty/default state; effect ordering can
  clobber storage. Prefer synchronous lazy state initialization from storage.
- Context excerpts may omit the middle of a complete source file. Never diagnose
  a source truncation solely from an explicitly marked context excerpt.
- Do NOT include commentary, markdown fences or code blocks. JSON only.
"""


@dataclass
class DiagnosticContext:
    plan: Plan
    stage: str  # e.g. "build" | "typecheck" | "test" | "verify" | "runtime"
    original_request: str = ""
    stdout_tail: str = ""
    stderr_tail: str = ""
    console_errors: List[str] = field(default_factory=list)
    network_errors: List[str] = field(default_factory=list)
    failed_step: Optional[str] = None
    file_paths: List[str] = field(default_factory=list)
    file_snippets: dict[str, str] = field(default_factory=dict)
    repo_map: Optional[RepoContextMap] = None
    dependency_conflicts: str = ""


def _extract_json(text: str) -> str:
    text = text.strip()
    m = re.match(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    start = text.find("{")
    if start < 0:
        return text
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


def build_prompt(ctx: DiagnosticContext) -> str:
    parts: List[str] = []
    parts.append(f"stack: {ctx.plan.stack_id}")
    parts.append(f"app_name: {ctx.plan.app_name}")
    parts.append(f"app_description: {ctx.plan.description}")
    if ctx.original_request:
        parts.append("ORIGINAL_USER_REQUEST (all exact requirements remain binding):\n" + ctx.original_request)
    parts.append(f"failing_stage: {ctx.stage}")
    if ctx.dependency_conflicts:
        parts.append(
            "DEPENDENCY_CONFLICTS (authoritative structured npm ERESOLVE evidence — "
            "base the dependency correction on these exact constraints):\n"
            + ctx.dependency_conflicts
        )
    if ctx.plan.verification_scenario:
        parts.append(
            "FULL_ACCEPTANCE_CONTRACT (repair comprehensively against all steps, not only the first observed failure):\n"
            + "\n".join(f"- {s.action}: {s.args}" for s in ctx.plan.verification_scenario)
        )
    if ctx.failed_step:
        parts.append(f"failed_verification_step: {ctx.failed_step}")
    if ctx.stdout_tail:
        parts.append("stdout_tail:\n" + ctx.stdout_tail[-2000:])
    if ctx.stderr_tail:
        parts.append("stderr_tail:\n" + ctx.stderr_tail[-2000:])
    if ctx.console_errors:
        parts.append("browser_console_errors:\n" + "\n".join(ctx.console_errors[:10]))
    if ctx.network_errors:
        parts.append("browser_network_errors:\n" + "\n".join(ctx.network_errors[:10]))
    parts.append("project_files:\n" + "\n".join(ctx.file_paths[:60]))
    if ctx.file_snippets:
        parts.append("file_snippets:")
        for path, content in list(ctx.file_snippets.items())[:8]:
            parts.append(f"--- {path} ---\n{content}")
    return "\n\n".join(parts)


@traced("DIAGNOSIS")
async def diagnose(
    ctx: DiagnosticContext,
    preferred_provider: Optional[str] = None,
) -> RepairPlan:
    prompt = build_prompt(ctx)
    req = CompletionRequest(
        messages=[Message(role="user", content=prompt)],
        system=DIAGNOSTIC_SYSTEM,
        max_tokens=1500,
        temperature=0.15,
        json_mode=True,
    )
    resp = await router.complete(req, preferred_id=preferred_provider)
    data = json.loads(_extract_json(resp.text))
    return RepairPlan(
        root_cause=data.get("root_cause", "unknown"),
        affected_files=list(data.get("affected_files") or []),
        modifications=list(data.get("modifications") or []),
    )
