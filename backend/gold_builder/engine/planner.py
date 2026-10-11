"""Planner — turns natural language into a validated Plan.

Two modes:
  1. build_plan(request, stack_id) — new app from scratch
  2. build_patch_plan(request, inspected_repo) — minimal-change plan for an
     existing repo

Both modes return a fully-validated `Plan` pydantic model. Free-form JSON
parsing is defensive (fence-strip + brace-balance) but the output is always
coerced through the Plan schema so downstream code can trust it.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from ..models import AcceptanceRequirement, ImageSpec, VideoSpec, Plan, Task
from ..providers.base import CompletionRequest, Message
from ..providers.router import router
from ..progress import traced
from .semantic_acceptance import (
    ensure_requirement_coverage,
    read_only_request,
    repair_contract_coverage,
    validate_contract,
)
from .stacks import STACKS, get_stack
from .video_planner import detect_video_requirement


PLANNER_SYSTEM_TEMPLATE = """You are the planner for Gold Builder AI.
You produce a strict JSON plan for building a small REAL working application.

Selected stack: {stack_id} — {stack_label}
Stack rules:
{planner_hint}

You MUST include (at minimum) these files as generate tasks (relative paths):
{seed_files}

If the app needs generated media, describe it explicitly.
For text→image use image_specs items such as:
{{"path":"generated/hero.png","prompt":"...","alt":"...","operation":"generate","size":"1536x1024","quality":"medium","number_of_outputs":1}}.
For image→image use operation="edit" plus input_image_path and/or reference_images.
For text→video use video_specs with operation="generate".
For image→video use operation="animate" or "text_image" plus input_image_path/reference_images.
For video→video use operation="transform" plus input_video_path.
Use project-relative output/input paths only. Never invent external URLs for generated media.
Only request video when the user explicitly asks for video.

Return ONLY valid JSON matching this schema exactly:
{{
  "app_name": "short-kebab-name",
  "description": "one-paragraph description",
  "stack_id": "{stack_id}",
  "stack": {{"frontend": "...", "backend": "..."}},
  "entrypoints": {{"frontend": "..."}},
  "verify_url": "http://localhost:{port}/",
  "required_env": [],
  "image_specs": [],
  "video_specs": [],
  "requirements": [
    {{"id": "REQ-001", "text": "one explicit user requirement", "kind": "ui|behavior|responsive|data|integration", "verifiable": true}}
  ],
  "verification_scenario": [
    {{"action": "fill", "args": {{"selector": "#application-specific-input", "value": "unique test value"}}, "requirement_id": "REQ-001"}},
    {{"action": "click", "args": {{"selector": "#application-specific-action"}}, "requirement_id": "REQ-001"}},
    {{"action": "assert_text", "args": {{"selector": "#result", "contains": "unique test value"}}, "requirement_id": "REQ-001"}}
  ],
  "tasks": [
    {{"name": "index.html", "kind": "generate", "file_path": "index.html",
     "description": "..."}}
  ]
}}

Extract EVERY explicit user requirement into the requirements array before planning files. Give each one a stable REQ-### id. Do not merge unrelated requirements. Mark only genuinely non-testable external dependencies as verifiable=false.

Every verifiable requirement MUST be linked to at least one verification assertion by requirement_id. Include assertions for every explicitly requested title, subtitle, CTA label, service-card name/count, schedule day and footer text. These exact values must not be replaced by invented copy. Derive assertions from the original request, even if the plan description is a summary.

For mobile/responsive requirements, include both desktop and mobile viewport checks using set_viewport plus assert_no_overflow. Use at least one desktop width >= 1024 and one mobile width <= 480.

The verification_scenario is a deterministic acceptance contract derived from the ORIGINAL request and planned UI. Use application-specific selectors and expected values. For every requested create/edit/search/delete/booking workflow, perform the action and then assert its observable result. Include reload plus a post-reload assertion when persistence is required. Supported actions: open, navigate, click, fill, select, check, submit, wait, reload, set_viewport, assert_visible, assert_hidden, assert_text, assert_not_text, assert_url, assert_count, assert_in_viewport, assert_no_overflow, screenshot. Never use mere page load or element existence as proof of requested behaviour.

Do NOT include commentary. Do NOT wrap in markdown fences. Return raw JSON only.
"""


PATCH_PLANNER_SYSTEM = """You are the patch planner for Gold Builder AI.
You are given an EXISTING repository and a user modification request.

You MUST:
- Change only what is necessary to satisfy the request.
- Preserve all existing working functionality.
- Prefer editing existing files over creating new ones.
- Never rewrite the whole app.

Return ONLY valid JSON:
{
  "app_name": "kept-from-repo-or-derived",
  "description": "what change we are making and why (1 short paragraph)",
  "stack_id": "html-static | react-vite | node-express | fastapi | react-vite-fastapi",
  "verify_url": "http://localhost:PORT/",
  "image_specs": [],
  "video_specs": [],
  "requirements": [
    {"id": "REQ-001", "text": "one explicit requested change", "kind": "behavior", "verifiable": true}
  ],
  "verification_scenario": [
    {"action": "fill", "args": {"selector": "#real-input", "value": "unique test value"}, "requirement_id": "REQ-001"},
    {"action": "click", "args": {"selector": "#real-action"}, "requirement_id": "REQ-001"},
    {"action": "assert_text", "args": {"selector": "#result", "contains": "unique test value"}, "requirement_id": "REQ-001"}
  ],
  "tasks": [
    {"name": "path/to/file.ext", "kind": "patch", "file_path": "path/to/file.ext",
     "description": "concrete edit to make in this file"}
  ]
}

Each task points at ONE file. `kind` must be `patch` for edits to existing files
or `generate` for new files. Order tasks so dependencies come first.
Extract every explicit requested change into the requirements array with stable REQ-### ids.
Every verifiable requirement must be covered by at least one assertion carrying the same requirement_id.
For responsive/mobile requests, verify both desktop and mobile viewports with set_viewport and assert_no_overflow.
The verification_scenario must exercise every requested behaviour in the real
browser and assert its observable result with selectors from the repository.
For persistence, reload and assert the saved state. The scenario is a contract;
it never declares pass or fail.
"""


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
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


def _default_verify_url(stack_id: str) -> str:
    cfg = get_stack(stack_id)
    return f"http://localhost:{cfg.default_port}/"


async def _ensure_verifiable_plan(
    data: dict,
    user_request: str,
    system_prompt: str,
    user_prompt: str,
    preferred_provider: Optional[str],
    provider_event=None,
) -> dict:
    requirements = data.get("requirements") or []
    scenario = data.get("verification_scenario") or []
    # A caller-supplied exact browser contract is authoritative. It can prove
    # behaviour without planner-invented requirement_id annotations, and must
    # remain byte-for-byte stable for later re-verification/repair.
    exact_contract = "Use this exact browser acceptance scenario in the plan:" in user_request
    # A read-only audit has no browser-observable requirement to prove. Its
    # requirements are inspection findings, not acceptance assertions, so the
    # mutation/persistence/responsive coverage gate must not force a synthetic
    # browser scenario or mark findings unverifiable.
    if read_only_request(user_request):
        return data
    validation_requirements = [] if exact_contract else requirements
    ok, errors = validate_contract(scenario, user_request, validation_requirements)
    if not requirements:
        ok = False
        errors = [*errors, "planner returned no explicit requirements"]
    if ok:
        return data

    correction = (
        f"{user_prompt}\n\n"
        "Your previous plan cannot be accepted because its verification contract is incomplete.\n"
        f"VALIDATION ERRORS: {errors}\n\n"
        "PREVIOUS PLAN JSON:\n"
        f"{json.dumps(data, ensure_ascii=False)}\n\n"
        "Return the COMPLETE corrected JSON plan. Preserve the requested implementation, "
        "but extract every explicit requirement and ensure every verifiable REQ-### has at least "
        "one assertion with the same requirement_id. Include real mobile+desktop viewport checks "
        "when responsive behaviour is requested."
    )
    retry = CompletionRequest(
        messages=[Message(role="user", content=correction)],
        system=system_prompt,
        max_tokens=4096,
        temperature=0.1,
        json_mode=True,
    )
    resp = await router.complete(retry, preferred_id=preferred_provider, event_callback=provider_event)
    repaired = json.loads(_extract_json(resp.text))
    repaired_requirements = repaired.get("requirements") or []
    repaired_ok, repaired_errors = validate_contract(
        repaired.get("verification_scenario") or [], user_request,
        [] if exact_contract else repaired_requirements
    )
    if not repaired_requirements:
        repaired_ok = False
        repaired_errors = [*repaired_errors, "planner returned no explicit requirements"]
    if not repaired_ok:
        if not exact_contract:
            repaired["verification_scenario"] = repair_contract_coverage(
                repaired.get("verification_scenario") or [],
                user_request,
                repaired_requirements,
            )
        repaired_ok, repaired_errors = validate_contract(
            repaired.get("verification_scenario") or [], user_request,
            [] if exact_contract else repaired_requirements
        )
    if not repaired_ok:
        # One final semantic correction is safer than either killing the job or
        # silently attaching an unrelated assertion to a requirement. This is
        # especially important for existing-repo audit/self-improvement jobs:
        # internal engineering instructions are not browser-observable and must
        # be marked verifiable=false, while real user-facing requirements must
        # receive a concrete assertion that proves them.
        final_correction = (
            f"{user_prompt}\\n\\n"
            "The corrected plan is still invalid.\\n"
            f"VALIDATION ERRORS: {repaired_errors}\\n\\n"
            "CURRENT PLAN JSON:\\n"
            f"{json.dumps(repaired, ensure_ascii=False)}\\n\\n"
            "Return the COMPLETE corrected JSON plan. For EACH uncovered REQ-###, do exactly one of: "
            "(A) add a concrete browser assertion with that requirement_id which genuinely proves the "
            "observable requirement, or (B) if the requirement is an internal engineering/audit/process "
            "instruction that cannot be proven in the application browser, keep it but set verifiable=false. "
            "Never mark a user-facing UI or behavior requirement unverifiable merely to pass validation. "
            "Do not invent fake selectors or assertions."
        )
        final_req = CompletionRequest(
            messages=[Message(role="user", content=final_correction)],
            system=system_prompt,
            max_tokens=4096,
            temperature=0.05,
            json_mode=True,
        )
        final_resp = await router.complete(
            final_req, preferred_id=preferred_provider, event_callback=provider_event
        )
        final_data = json.loads(_extract_json(final_resp.text))
        final_requirements = final_data.get("requirements") or []
        final_ok, final_errors = validate_contract(
            final_data.get("verification_scenario") or [], user_request,
            [] if exact_contract else final_requirements
        )
        if not final_requirements:
            final_ok = False
            final_errors = [*final_errors, "planner returned no explicit requirements"]
        if not final_ok and final_requirements and not exact_contract:
            # Deterministic, LLM-free fallback: link uncovered requirements to
            # assertions that already exist in the recovered scenario. It never
            # invents selectors/values or marks a requirement unverifiable, so
            # strict validation is preserved — re-validation below still fails
            # the job when coverage cannot be proven.
            final_data["verification_scenario"], _unresolved = ensure_requirement_coverage(
                final_data.get("verification_scenario") or [],
                user_request,
                final_requirements,
            )
            final_ok, final_errors = validate_contract(
                final_data.get("verification_scenario") or [], user_request,
                final_requirements,
            )
        if not final_ok:
            import os as _dbg_os; _p = _dbg_os.environ.get("GB_DEBUG_REJECTED_PLAN")  # TEMP-DEBUG
            if _p: open(_p, "w").write(json.dumps(final_data, ensure_ascii=False, indent=1))  # TEMP-DEBUG
            raise ValueError(
                "planner produced an unverifiable acceptance contract after semantic recovery: "
                + "; ".join(final_errors)
            )
        return final_data
    return repaired


@traced("PLAN")
async def build_plan(
    user_request: str,
    stack_id: Optional[str] = None,
    with_media: bool = True,
    preferred_provider: Optional[str] = None,
    provider_event=None,
) -> Plan:
    stack_id = stack_id if stack_id in STACKS else "html-static"
    cfg = get_stack(stack_id)
    sys_prompt = PLANNER_SYSTEM_TEMPLATE.format(
        stack_id=stack_id,
        stack_label=cfg.label,
        planner_hint=cfg.planner_hint,
        seed_files="\n".join(f"  - {p}" for p in cfg.seed_files),
        port=cfg.default_port,
    )
    if not with_media:
        sys_prompt += "\nDo NOT include image_specs or video_specs — set both to []."

    req = CompletionRequest(
        messages=[Message(role="user", content=user_request)],
        system=sys_prompt,
        max_tokens=4096,
        temperature=0.2,
        json_mode=True,
    )
    resp = await router.complete(req, preferred_id=preferred_provider, event_callback=provider_event)
    data = json.loads(_extract_json(resp.text))
    data = await _ensure_verifiable_plan(
        data, user_request, sys_prompt, user_request, preferred_provider, provider_event
    )

    tasks = [Task(**t) for t in data.get("tasks", []) if isinstance(t, dict)]
    # Ensure required seed files are present (planner might forget some)
    seen = {t.file_path for t in tasks if t.file_path}
    for seed in cfg.seed_files:
        if seed not in seen:
            tasks.append(Task(name=seed, kind="generate", file_path=seed,
                              description=f"Seed file for stack {stack_id}"))

    image_specs_raw = data.get("image_specs") or []
    image_specs = [ImageSpec(**s) for s in image_specs_raw
                   if isinstance(s, dict) and s.get("path") and s.get("prompt")]
    video_specs_raw = data.get("video_specs") or []
    video_specs = [VideoSpec(**s) for s in video_specs_raw
                   if isinstance(s, dict) and s.get("path") and s.get("prompt")]

    # Deterministic autonomous video planner: if the user explicitly asks for
    # generated video and the LLM did not emit a spec, add one. Non-video
    # requests remain unchanged.
    if with_media and not video_specs:
        detected = detect_video_requirement(user_request, image_specs)
        if detected is not None:
            video_specs = [detected]

    return Plan(
        app_name=data.get("app_name", "gold-app"),
        description=data.get("description", user_request),
        stack_id=stack_id,
        stack=data.get("stack", {"frontend": stack_id, "backend": cfg.id}),
        tasks=tasks,
        entrypoints=data.get("entrypoints", {}),
        verify_url=data.get("verify_url") or _default_verify_url(stack_id),
        required_env=data.get("required_env", []),
        image_specs=image_specs,
        video_specs=video_specs,
        requirements=[AcceptanceRequirement(**r) for r in (data.get("requirements") or []) if isinstance(r, dict) and r.get("id") and r.get("text")],
        verification_scenario=data.get("verification_scenario") or [],
        acceptance_contract_authoritative="Use this exact browser acceptance scenario in the plan:" in user_request,
    )


@traced("PLAN")
async def build_patch_plan(
    user_request: str,
    repo_summary: str,
    preferred_provider: Optional[str] = None,
    provider_event=None,
) -> Plan:
    prompt = (
        f"USER REQUEST:\n{user_request}\n\n"
        f"REPOSITORY SUMMARY:\n{repo_summary}\n\n"
        "Produce the smallest set of file-level changes that fulfil the request."
    )
    req = CompletionRequest(
        messages=[Message(role="user", content=prompt)],
        system=PATCH_PLANNER_SYSTEM,
        max_tokens=4096,
        temperature=0.15,
        json_mode=True,
    )
    resp = await router.complete(req, preferred_id=preferred_provider, event_callback=provider_event)
    data = json.loads(_extract_json(resp.text))
    data = await _ensure_verifiable_plan(
        data, user_request, PATCH_PLANNER_SYSTEM, prompt, preferred_provider, provider_event
    )
    tasks = [Task(**t) for t in data.get("tasks", []) if isinstance(t, dict)]
    stack_id = data.get("stack_id") or "html-static"
    image_specs_raw = data.get("image_specs") or []
    image_specs = [ImageSpec(**s) for s in image_specs_raw
                   if isinstance(s, dict) and s.get("path") and s.get("prompt")]
    video_specs_raw = data.get("video_specs") or []
    video_specs = [VideoSpec(**s) for s in video_specs_raw
                   if isinstance(s, dict) and s.get("path") and s.get("prompt")]
    return Plan(
        app_name=data.get("app_name", "existing-repo-patch"),
        description=data.get("description", user_request),
        stack_id=stack_id,
        stack={"mode": "patch"},
        tasks=tasks,
        entrypoints={},
        verify_url=data.get("verify_url") or _default_verify_url(stack_id),
        required_env=[],
        image_specs=image_specs,
        video_specs=video_specs,
        requirements=[AcceptanceRequirement(**r) for r in (data.get("requirements") or []) if isinstance(r, dict) and r.get("id") and r.get("text")],
        verification_scenario=data.get("verification_scenario") or [],
        acceptance_contract_authoritative="Use this exact browser acceptance scenario in the plan:" in user_request,
    )
