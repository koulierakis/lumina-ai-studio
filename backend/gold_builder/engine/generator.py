"""File-by-file code generator.

For each Task with kind=="generate", we send a focused prompt that includes:
  - the full plan context
  - the list of files already produced (so subsequent files stay consistent)
  - the specific file to produce

We ask for the raw file contents only. Fenced code blocks are stripped.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from ..models import GeneratedFile, Plan, Task
from ..providers.base import CompletionRequest, Message
from ..providers.router import router
from ..progress import traced

GENERATOR_SYSTEM = """You are the code generator for Gold Builder AI.
Produce ONE file at a time. Return only raw file contents — no markdown
fences, no commentary, no leading explanations. The output will be written
verbatim to disk. Do not include filename headers.

Constraints:
- Produce complete, runnable code. Never emit TODO placeholders.
- For browser persistence requirements, initialize state synchronously from storage
  (for example useState(() => loadFromStorage())). Do NOT use one mount effect to
  load persisted state plus another effect that writes the initial empty/default
  state: React effect ordering can overwrite storage before the loaded state is
  committed.
- Prefer plain HTML/CSS/JS (no build step) unless the plan says otherwise.
- Keep the code cohesive with previously generated files.
- Reference the exact planned local stylesheet/script paths; do not invent filenames.
- Keep HTML compact and put styles/behaviour in the planned CSS/JS files.
- For html-static, use ordinary CSS classes and generate their actual rules. Do not
  assume a utility framework exists unless it is an explicit planned dependency.
- Use accessible, semantic markup.
- No external CDN dependencies unless strictly needed.
- No API keys, no secrets."""


def _strip_fences(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:[a-zA-Z0-9]+)?\s*\n(.*?)\n```\s*$", text, re.DOTALL)
    if m:
        return m.group(1)
    text = re.sub(r"^```[a-zA-Z0-9]*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text


@traced("FILE GENERATION")
async def generate_file(
    plan: Plan,
    task: Task,
    existing: List[GeneratedFile],
    preferred_provider: Optional[str] = None,
    cross_file_context: Optional[str] = None,
    original_request: Optional[str] = None,
    job_id: Optional[str] = None,
) -> GeneratedFile:
    if not task.file_path:
        raise ValueError(f"Task {task.name} has no file_path")

    existing_summary: Dict[str, str] = {}
    for f in existing[-8:]:
        snippet = f.content
        if len(snippet) > 16000:
            snippet = (snippet[:8000] + "\n[Context excerpt: middle omitted; original file is complete]\n"
                       + snippet[-8000:])
        existing_summary[f.path] = snippet

    summary_lines = [f"--- {p} ---\n{c}\n" for p, c in existing_summary.items()]
    context_str = "\n".join(summary_lines) if summary_lines else "(none yet — this is the first file)"

    media_hints = []
    for img in plan.image_specs:
        media_hints.append(
            f"- image path: {img.path} (alt: {img.alt}; operation: {img.operation})"
        )
    for video in plan.video_specs:
        media_hints.append(
            f"- video path: {video.path} (operation: {video.operation})"
        )
    media_str = "\n".join(media_hints) if media_hints else "(no generated media in this project)"

    arch_block = f"\nCROSS-FILE ARCHITECTURE:\n{cross_file_context}\n" if cross_file_context else ""
    acceptance = ""
    if plan.verification_scenario:
        acceptance = "\nACCEPTANCE CONTRACT (the generated app MUST expose controls/state that make every step executable):\n"
        acceptance += "\n".join(
            f"- {s.action}: {s.args}" for s in plan.verification_scenario
        ) + "\n"

    planned_files = "\n".join(t.file_path for t in plan.tasks if t.file_path)

    prompt = f"""Target file: {task.file_path}
Task description: {task.description}

ORIGINAL USER REQUEST (preserve every exact name, count, label and requirement):
{original_request or plan.description}

App overview:
app_name: {plan.app_name}
description: {plan.description}
stack_id: {plan.stack_id}
verify_url: {plan.verify_url}

Planned project files (use these exact paths for local resources):
{planned_files}

Planned generated media (reference these exact project-relative paths in img/video/CSS as appropriate):
{media_str}
{arch_block}{acceptance}
Files already generated for this project:
{context_str}

Produce the COMPLETE contents of {task.file_path}. No fences, no commentary."""

    req = CompletionRequest(
        messages=[Message(role="user", content=prompt)],
        system=GENERATOR_SYSTEM,
        max_tokens=12000,
        temperature=0.2,
    )
    resp = await router.complete(req, preferred_id=preferred_provider, job_id=job_id)
    return GeneratedFile(path=task.file_path, content=_strip_fences(resp.text))


@traced("FILE GENERATION")
async def repair_file(
    plan: Plan,
    file: GeneratedFile,
    failure_evidence: str,
    preferred_provider: Optional[str] = None,
    cross_file_context: Optional[str] = None,
    root_cause: Optional[str] = None,
) -> GeneratedFile:
    """Ask the LLM to fix ONE file given diagnostic evidence and surrounding architecture."""
    cause_str = f"DIAGNOSED ROOT CAUSE:\n{root_cause}\n\n" if root_cause else ""
    context_str = f"SURROUNDING ARCHITECTURE & CROSS-FILE CONTEXT:\n{cross_file_context}\n\n" if cross_file_context else ""

    prompt = f"""The file below is part of application "{plan.app_name}".
{cause_str}When we ran/verified the app we observed these errors:

{failure_evidence}

{context_str}Here is the current file at path {file.path}:

{file.content}

INSTRUCTIONS:
1. Return the FULL corrected file contents only. No fences, no commentary.
2. Fix the root cause and runtime errors while preserving surrounding interfaces.
3. Keep everything that works."""

    req = CompletionRequest(
        messages=[Message(role="user", content=prompt)],
        system=GENERATOR_SYSTEM,
        max_tokens=12000,
        temperature=0.1,
    )
    resp = await router.complete(req, preferred_id=preferred_provider)
    return GeneratedFile(path=file.path, content=_strip_fences(resp.text))
