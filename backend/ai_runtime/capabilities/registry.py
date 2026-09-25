"""LUMINA Mind orchestration registry.

Declarative description of the existing LUMINA capability surface. Every
operation maps to an *existing* HTTP endpoint the studio pages already use; the
orchestrator only calls these real routes (never fabricated results).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

Risk = Literal["auto", "approval"]
ContentKind = Literal["json", "query", "form", "form-result"]
Poll = Callable[[dict[str, Any]], str | None]


def _default_id(value: dict[str, Any]) -> str:
    return str(value.get("id") or "")


def _first_media(value: dict[str, Any]) -> str:
    outputs = value.get("output_media_ids") or []
    return str(outputs[0]) if outputs else str(value.get("output_media_id") or "")


@dataclass(frozen=True)
class CapabilityOperation:
    """One executable capability action backed by one existing endpoint."""

    id: str
    method: str
    path: str
    risk: Risk
    content: ContentKind = "json"
    description: str = ""
    required_params: tuple[str, ...] = ()
    optional_params: tuple[str, ...] = ()
    job_fallback_path: str | None = None
    job_status_field: str = "status"
    job_terminal: tuple[str, ...] = ("completed", "failed", "cancelled")
    job_id_field: str = "id"
    summary_fields: tuple[str, ...] = ()
    result_link: Callable[[dict[str, Any]], str] | None = None

    def route(self, **params: str) -> str:
        """Render the route template, substituting path parameters."""
        path = self.path
        for key, value in params.items():
            path = path.replace(f"{{{key}}}", str(value))
        return path


@dataclass(frozen=True)
class Capability:
    id: str
    name: str
    description: str
    operations: dict[str, CapabilityOperation] = field(default_factory=dict)

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "operations": {
                op_id: {
                    "method": op.method,
                    "path": op.path,
                    "risk": op.risk,
                    "description": op.description,
                    "required_params": list(op.required_params),
                    "optional_params": list(op.optional_params),
                }
                for op_id, op in self.operations.items()
            },
        }


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
_DOCUMENTS = Capability(
    id="documents",
    name="Documents",
    description="Corporate document studio: create, generate, search, analyze and review legal and business documents.",
    operations={
        "list": CapabilityOperation(
            id="list", method="GET", path="/api/documents", risk="auto",
            description="List the owner's corporate documents.",
            summary_fields=("title", "id"),
        ),
        "search": CapabilityOperation(
            id="search", method="GET", path="/api/documents/search", risk="auto",
            content="query", description="Search documents by keyword.",
            optional_params=("text",), summary_fields=("title", "id"),
        ),
        "get": CapabilityOperation(
            id="get", method="GET", path="/api/documents/{document_id}", risk="auto",
            description="Fetch a single document by id.",
            required_params=("document_id",), summary_fields=("title", "id", "status"),
        ),
        "create": CapabilityOperation(
            id="create", method="POST", path="/api/documents", risk="auto",
            description="Create a document with title and optional content.",
            optional_params=("title", "content_text", "content_html", "document_type", "category", "tags", "language", "country"),
            summary_fields=("id", "title"),
        ),
        "generate": CapabilityOperation(
            id="generate", method="POST", path="/api/documents/generate", risk="auto",
            description="Generate a corporate document from a template or classified prompt.",
            optional_params=("title", "prompt", "template_id", "creation_mode", "parties", "jurisdiction", "effective_date", "fields", "tags", "language", "country"),
            summary_fields=("id", "title", "document_type"),
        ),
        "analysis": CapabilityOperation(
            id="analysis", method="POST", path="/api/documents/{document_id}/analysis", risk="auto",
            description="Run a structured analysis (summarize, risks, clauses) on a document.",
            required_params=("document_id",),
            optional_params=("action", "question", "comparison_document_id", "required_clauses"),
            summary_fields=("action",),
        ),
        "legal_review": CapabilityOperation(
            id="legal_review", method="POST", path="/api/documents/{document_id}/legal-review", risk="auto",
            description="Run a local legal-safety review of a document.",
            required_params=("document_id",), summary_fields=("passed",),
        ),
        "list_templates": CapabilityOperation(
            id="list_templates", method="GET", path="/api/documents/template-library", risk="auto",
            description="List corporate document templates.",
            summary_fields=("id", "name"),
        ),
        "delete": CapabilityOperation(
            id="delete", method="DELETE", path="/api/documents/{document_id}", risk="approval",
            description="Permanently delete a document and its versions.",
            required_params=("document_id",),
        ),
        "delete_folder": CapabilityOperation(
            id="delete_folder", method="DELETE", path="/api/documents/folders/{folder_id}", risk="approval",
            description="Delete a document folder and unlink its documents.",
            required_params=("folder_id",),
        ),
    },
)

# ---------------------------------------------------------------------------
# Image / Photo Studio
# ---------------------------------------------------------------------------
_IMAGE = Capability(
    id="image",
    name="Image Studio",
    description="Generative image studio: create images and browse the gallery of generated shots.",
    operations={
        "generate": CapabilityOperation(
            id="generate", method="POST", path="/api/generate", risk="auto",
            description="Queue an image generation job.",
            optional_params=("prompt", "negative_prompt", "aspect_ratio", "resolution", "quality", "count", "scene", "outfit", "mode"),
            job_fallback_path="/api/jobs/{id}", summary_fields=("id", "status", "output_media_ids"),
        ),
        "list_gallery": CapabilityOperation(
            id="list_gallery", method="GET", path="/api/gallery", risk="auto",
            description="List generated images in the gallery.",
            summary_fields=("id", "prompt"),
        ),
        "list_jobs": CapabilityOperation(
            id="list_jobs", method="GET", path="/api/jobs", risk="auto",
            description="List image generation jobs.",
            summary_fields=("id", "prompt", "status"),
        ),
        "delete_gallery_item": CapabilityOperation(
            id="delete_gallery_item", method="DELETE", path="/api/gallery/{item_id}", risk="approval",
            description="Permanently delete a gallery image and its media record.",
            required_params=("item_id",),
        ),
    },
)

# ---------------------------------------------------------------------------
# Video Studio
# ---------------------------------------------------------------------------
_VIDEO = Capability(
    id="video",
    name="Video Studio",
    description="Video generation studio: create motion shots and inspect video jobs and projects.",
    operations={
        "generate": CapabilityOperation(
            id="generate", method="POST", path="/api/video/generate", risk="auto",
            content="form-result",
            description="Queue a text-to-video generation job.",
            optional_params=("prompt", "mode", "duration_seconds", "aspect_ratio", "resolution", "quality", "fps", "style"),
            job_fallback_path="/api/video/jobs/{id}",
            job_status_field="status",
            job_terminal=("completed", "failed", "cancelled"),
            summary_fields=("id", "status", "output_media_id"),
        ),
        "list_jobs": CapabilityOperation(
            id="list_jobs", method="GET", path="/api/video/jobs", risk="auto",
            description="List video generation jobs.",
            summary_fields=("id", "title", "status"),
        ),
        "list_projects": CapabilityOperation(
            id="list_projects", method="GET", path="/api/video/projects", risk="auto",
            description="List video projects.",
            summary_fields=("id", "name"),
        ),
        "get_job": CapabilityOperation(
            id="get_job", method="GET", path="/api/video/jobs/{job_id}", risk="auto",
            description="Fetch a video job by id.",
            required_params=("job_id",), summary_fields=("id", "status", "output_media_id"),
        ),
        "delete_job": CapabilityOperation(
            id="delete_job", method="DELETE", path="/api/video/jobs/{job_id}", risk="approval",
            description="Delete a video job and its source/output media.",
            required_params=("job_id",),
        ),
    },
)

# ---------------------------------------------------------------------------
# Voice Studio
# ---------------------------------------------------------------------------
_VOICE = Capability(
    id="voice",
    name="Voice Studio",
    description="Voice synthesis studio: generate speech narration and inspect voice jobs and packs.",
    operations={
        "generate": CapabilityOperation(
            id="generate", method="POST", path="/api/voice/generate", risk="auto",
            content="form-result",
            description="Queue a text-to-speech generation job.",
            optional_params=("text", "mode", "voice", "style", "output_format", "title"),
            job_fallback_path="/api/voice/jobs/{id}",
            job_status_field="status",
            job_terminal=("completed", "failed", "cancelled"),
            summary_fields=("id", "status", "output_media_id"),
        ),
        "list_jobs": CapabilityOperation(
            id="list_jobs", method="GET", path="/api/voice/jobs", risk="auto",
            description="List voice generation jobs.",
            summary_fields=("id", "title", "status"),
        ),
        "get_job": CapabilityOperation(
            id="get_job", method="GET", path="/api/voice/jobs/{job_id}", risk="auto",
            description="Fetch a voice job by id.",
            required_params=("job_id",), summary_fields=("id", "status", "output_media_id"),
        ),
        "list_packs": CapabilityOperation(
            id="list_packs", method="GET", path="/api/voice/packs", risk="auto",
            description="List personal voice packs.",
            summary_fields=("id", "name"),
        ),
        "delete_job": CapabilityOperation(
            id="delete_job", method="DELETE", path="/api/voice/jobs/{job_id}", risk="approval",
            description="Delete a voice job and its media record.",
            required_params=("job_id",),
        ),
        "delete_pack": CapabilityOperation(
            id="delete_pack", method="DELETE", path="/api/voice/packs/{pack_id}", risk="approval",
            description="Delete a personal voice pack.",
            required_params=("pack_id",),
        ),
    },
)

# ---------------------------------------------------------------------------
# Media / Projects
# ---------------------------------------------------------------------------
_STUDIO = Capability(
    id="studio",
    name="Media & Projects",
    description="Media library and project workspace: list media assets and manage creative projects.",
    operations={
        "list_media": CapabilityOperation(
            id="list_media", method="GET", path="/api/media-library", risk="auto",
            description="List media assets with paging.",
            summary_fields=("items", "count"),
        ),
        "list_projects": CapabilityOperation(
            id="list_projects", method="GET", path="/api/projects", risk="auto",
            description="List projects.",
            summary_fields=("id", "name"),
        ),
        "get_project": CapabilityOperation(
            id="get_project", method="GET", path="/api/projects/{project_id}", risk="auto",
            description="Fetch a project by id.",
            required_params=("project_id",), summary_fields=("id", "name"),
        ),
        "create_project": CapabilityOperation(
            id="create_project", method="POST", path="/api/projects", risk="auto",
            description="Create a new project.",
            optional_params=("name", "description"),
            summary_fields=("id", "name"),
        ),
        "delete_project": CapabilityOperation(
            id="delete_project", method="DELETE", path="/api/projects/{project_id}", risk="approval",
            description="Delete a project and its association records.",
            required_params=("project_id",),
        ),
        "delete_media": CapabilityOperation(
            id="delete_media", method="DELETE", path="/api/media-library/{media_id}", risk="approval",
            description="Delete a media asset.",
            required_params=("media_id",),
        ),
    },
)

# ---------------------------------------------------------------------------
# Code Builder V2
# ---------------------------------------------------------------------------
_CODE_BUILDER = Capability(
    id="code_builder",
    name="Code Builder",
    description="Autonomous code change engine: plan and apply verified repository changes backed by automated rollback.",
    operations={
        "health": CapabilityOperation(
            id="health", method="GET", path="/api/code-builder-v2/health", risk="auto",
            description="Check Code Builder engine health.",
            summary_fields=("status",),
        ),
        "plan": CapabilityOperation(
            id="plan", method="POST", path="/api/code-builder-v2/tasks", risk="auto",
            description="Create a code-change plan without applying it.",
            optional_params=("prompt", "model", "auto_apply"),
            summary_fields=("id", "status"),
        ),
        "get_task": CapabilityOperation(
            id="get_task", method="GET", path="/api/code-builder-v2/tasks/{task_id}", risk="auto",
            description="Fetch a code build task by id.",
            required_params=("task_id",), summary_fields=("id", "status"),
        ),
        "execute": CapabilityOperation(
            id="execute", method="POST", path="/api/code-builder-v2/tasks/{task_id}/execute", risk="approval",
            description="Apply an approved code-change plan to the repository.",
            required_params=("task_id",),
        ),
        "rollback": CapabilityOperation(
            id="rollback", method="POST", path="/api/code-builder-v2/tasks/{task_id}/rollback", risk="auto",
            description="Restore the repository from the task backup (reversible).",
            required_params=("task_id",),
        ),
    },
)

CAPABILITY_REGISTRY: dict[str, Capability] = {
    capability.id: capability
    for capability in (
        _DOCUMENTS,
        _IMAGE,
        _VIDEO,
        _VOICE,
        _STUDIO,
        _CODE_BUILDER,
    )
}


def default_catalog() -> list[dict[str, Any]]:
    """Public catalog of capabilities (for UI and model grounding)."""
    return [capability.describe() for capability in CAPABILITY_REGISTRY.values()]