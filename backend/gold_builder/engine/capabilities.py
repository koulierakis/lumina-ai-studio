"""Machine-readable capability registry.

Every capability is reported as `AVAILABLE | PARTIAL | UNAVAILABLE`. The
result is computed at request time so probes reflect the running engine's
actual state (installed browsers, configured providers, registered
stacks, …).

DO NOT set a capability to AVAILABLE just because an interface exists —
if there is no concrete implementation, report UNAVAILABLE.
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys
from typing import List

from ..models import Capability, CapabilityStatus
from ..providers.router import router
from .stacks import STACKS


def _has_module(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except Exception:  # noqa: BLE001
        return False


def _has_binary(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def report() -> List[Capability]:
    """Return live capability status for all Gold Builder systems."""
    pw_installed = _has_module("playwright")
    pw_browser_ready = bool(
        pw_installed and (
            shutil.which("google-chrome")
            or shutil.which("chromium")
            or os.path.exists("/root/.cache/ms-playwright")
            or os.path.exists(os.path.expanduser("~/.cache/ms-playwright"))
            or os.path.exists(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""))
            or os.path.exists("/opt/render/project/src/.playwright-browsers")
        )
    )

    llms = router.available_llm()
    images = router.available_image()
    videos = router.available_video()
    image_generate = [p for p in images if p.supports("generate")]
    image_edit = [p for p in images if p.supports("edit")]
    video_text = [p for p in videos if p.supports("generate")]
    video_image = [p for p in videos if p.supports("animate") or p.supports("text_image")]
    video_transform = [p for p in videos if p.supports("transform")]
    private_git_ready = bool((os.environ.get("GB_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip())
    workspace_root = os.environ.get("WORKSPACE_ROOT", "/app/workspaces")
    durable_workspace = not (workspace_root.startswith("/tmp/") or workspace_root == "/tmp")
    durable_db = bool(
        os.environ.get("MONGO_URL", "").strip()
        or os.environ.get("JOB_DATABASE_URL", "").strip()
        or os.environ.get("DATABASE_URL", "").strip()
    )
    durable_archive = bool(os.environ.get("JOB_DATABASE_URL", "").strip() or os.environ.get("DATABASE_URL", "").strip())

    caps: List[Capability] = [
        Capability(
            id="llm",
            status=CapabilityStatus.AVAILABLE if llms else CapabilityStatus.UNAVAILABLE,
            detail=f"{len(llms)} provider(s) ready" if llms else "No LLM providers available",
            providers=llms,
        ),
        Capability(
            id="image_generation",
            status=CapabilityStatus.AVAILABLE if image_generate else CapabilityStatus.UNAVAILABLE,
            detail=f"{len(image_generate)} provider(s) ready" if image_generate else "No image provider configured",
            providers=[p.id for p in image_generate],
        ),
        Capability(
            id="video_generation",
            status=CapabilityStatus.AVAILABLE if video_text else CapabilityStatus.UNAVAILABLE,
            detail=f"{len(video_text)} provider(s) ready" if video_text else "Video generation unavailable: no concrete video provider configured",
            providers=[p.id for p in video_text],
        ),
        Capability(
            id="text_to_image",
            status=CapabilityStatus.AVAILABLE if image_generate else CapabilityStatus.UNAVAILABLE,
            detail=f"{len(image_generate)} provider(s) ready" if image_generate else "No text-to-image provider configured",
            providers=[p.id for p in image_generate],
        ),
        Capability(
            id="image_to_image",
            status=CapabilityStatus.AVAILABLE if image_edit else CapabilityStatus.UNAVAILABLE,
            detail=f"{len(image_edit)} provider(s) ready" if image_edit else "No image-edit provider configured",
            providers=[p.id for p in image_edit],
        ),
        Capability(
            id="text_to_video",
            status=CapabilityStatus.AVAILABLE if video_text else CapabilityStatus.UNAVAILABLE,
            detail=f"{len(video_text)} provider(s) ready" if video_text else "Provider-ready; no text-to-video provider configured",
            providers=[p.id for p in video_text],
        ),
        Capability(
            id="image_to_video",
            status=CapabilityStatus.AVAILABLE if video_image else CapabilityStatus.UNAVAILABLE,
            detail=f"{len(video_image)} provider(s) ready" if video_image else "Provider-ready; no image-to-video provider configured",
            providers=[p.id for p in video_image],
        ),
        Capability(
            id="video_to_video",
            status=CapabilityStatus.AVAILABLE if video_transform else CapabilityStatus.UNAVAILABLE,
            detail=f"{len(video_transform)} provider(s) ready" if video_transform else "Provider-ready; no video-transform provider configured",
            providers=[p.id for p in video_transform],
        ),
        Capability(
            id="browser_verification",
            status=CapabilityStatus.AVAILABLE if pw_browser_ready else (CapabilityStatus.PARTIAL if pw_installed else CapabilityStatus.UNAVAILABLE),
            detail="Playwright and browser binary verified" if pw_browser_ready else ("Playwright installed, browser binary missing (HTTP fallback active)" if pw_installed else "Playwright not installed"),
        ),
        Capability(
            id="interactive_preview",
            status=CapabilityStatus.AVAILABLE,
            detail="Internal preview lifecycle manager and proxy active",
        ),
        Capability(
            id="existing_repo_editing",
            status=CapabilityStatus.AVAILABLE if private_git_ready else CapabilityStatus.PARTIAL,
            detail=(
                "Public and private GitHub clone, isolated work branch, local verified commits, repository intelligence and patch planning active"
                if private_git_ready else
                "Public repositories are ready; private GitHub repositories require GB_GITHUB_TOKEN in the engine environment"
            ),
        ),
        Capability(
            id="autonomous_repair",
            status=CapabilityStatus.AVAILABLE,
            detail="Observe-Reason-Act-Verify multi-file repair with rollback active",
        ),
        # Architectural completion capabilities
        Capability(
            id="intelligent_verification_planning",
            status=CapabilityStatus.AVAILABLE,
            detail="Application-specific structured browser verification planner active",
        ),
        Capability(
            id="observe_reason_repair_loop",
            status=CapabilityStatus.AVAILABLE,
            detail="Autonomous diagnosis and multi-file repair with safe rollback active",
        ),
        Capability(
            id="repository_intelligence",
            status=CapabilityStatus.AVAILABLE,
            detail="AST/regex context mapping and cross-file relevance selection active",
        ),
        Capability(
            id="persistent_project_iteration",
            status=CapabilityStatus.AVAILABLE if (durable_db and (durable_workspace or durable_archive)) else CapabilityStatus.PARTIAL,
            detail=(
                "Durable database plus workspace archive configured for restart/deploy-safe continuation"
                if (durable_db and (durable_workspace or durable_archive)) else
                "Iteration works across ordinary process restarts, but deploy/host replacement can lose workspace until JOB_DATABASE_URL/DATABASE_URL or durable workspace storage is configured"
            ),
        ),
        Capability(
            id="requirement_traceability",
            status=CapabilityStatus.AVAILABLE,
            detail="REQ-by-REQ acceptance coverage blocks completion when a verifiable requirement lacks browser evidence",
        ),
        Capability(
            id="responsive_browser_verification",
            status=CapabilityStatus.AVAILABLE if pw_browser_ready else CapabilityStatus.PARTIAL,
            detail="Desktop and mobile viewport checks with horizontal-overflow detection",
        ),
        Capability(
            id="production_deploy_verification",
            status=CapabilityStatus.PARTIAL,
            detail="Browser verification can target a supplied live URL, but automatic deployment discovery/push is not yet wired for arbitrary external repositories",
        ),
        Capability(
            id="version_history_rollback",
            status=CapabilityStatus.AVAILABLE,
            detail="Checkpoint snapshotting, rollback, and git-compatible history active",
        ),
        Capability(
            id="smart_provider_routing",
            status=CapabilityStatus.AVAILABLE if llms else CapabilityStatus.UNAVAILABLE,
            detail=f"Role-based routing (planner, coder, debugger, verifier) with {len(llms)} LLM provider(s)",
            providers=llms,
        ),
    ]

    # Stacks
    for s in STACKS.values():
        caps.append(Capability(
            id=f"stack:{s.id}",
            status=CapabilityStatus.AVAILABLE,
            detail=f"Stack: {s.label}",
        ))

    return caps
