from __future__ import annotations

import html
import io
import json
import zipfile
from typing import Annotated
from urllib.parse import quote

from ai_runtime.manager import runtime_manager
from ai_runtime.schemas import RuntimeJob, RuntimeJobStatus
from auth import require_owner
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from models import MediaAsset, now_iso
from persistence import LocalPersistenceCollection, SQLitePersistenceProvider
from storage import save_bytes

from .models import (
    BankProfile,
    ClauseTemplate,
    CompanyProfile,
    CompanyVersion,
    CorporateDocument,
    CorporatePerson,
    CorporateTemplate,
    DocumentAnalysisRequest,
    DocumentAnalysisResult,
    DocumentCollection,
    DocumentDesignRequest,
    DocumentFolder,
    DocumentGenerationRequest,
    DocumentLockRequest,
    DocumentOperationRequest,
    DocumentReviewRequest,
    DocumentTag,
    DocumentTemplateVersion,
    DocumentVersion,
    EnterpriseDocumentTemplate,
    ExportJobRequest,
    PackageBuildRequest,
    ReviewActionRequest,
    TrackChangeActionRequest,
    TrackChangeRequest,
    VersionActionRequest,
)
from .service import (
    CHART_TYPES,
    CLAUSE_LIBRARY,
    COMPONENT_LIBRARY,
    COVER_STYLES,
    DOCUMENT_CLASS_DEFINITIONS,
    DOCUMENT_TYPE_CATALOG,
    EXPORT_FORMATS,
    PACKAGE_TYPES,
    SMART_TABLE_TYPES,
    TEMPLATES,
    analyze_document,
    apply_design_system,
    apply_document_operation,
    apply_review_action,
    apply_track_change_action,
    build_package,
    classify_document_request,
    compare_documents,
    create_review_item,
    create_track_change,
    extract_smart_fields,
    extract_text_from_upload,
    get_template,
    legal_review_document,
    quality_score,
    render_classified_document,
    render_document_html,
    render_docx_bytes,
    render_merge_template,
    render_pdf_bytes,
    render_text_export,
    validate_merge_template,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])

documents_coll = versions_coll = profiles_coll = company_versions_coll = folders_coll = (
    collections_coll
) = templates_coll = template_versions_coll = tags_coll = people_coll = banks_coll = (
    clauses_coll
) = media_coll = notifications_coll = None

ALLOWED_DOCUMENT_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/html",
    "text/markdown",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
}
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024


def _download_content_disposition(title: str, extension: str) -> str:
    safe_extension = "".join(ch for ch in extension.lower() if ch.isalnum()) or "bin"
    ascii_stem = "".join(
        ch if ch.isascii() and (ch.isalnum() or ch in "-_") else "_"
        for ch in str(title or "document")
    ).strip("_")[:80] or "document"
    unicode_name = quote(f"{str(title or 'document')}.{safe_extension}", safe="")
    return (
        f'attachment; filename="{ascii_stem}.{safe_extension}"; '
        f"filename*=UTF-8''{unicode_name}"
    )


def _safe_import_html(title: str, extracted_text: str) -> str:
    safe_title = html.escape(str(title or "Imported document"), quote=True)
    paragraphs = [
        f"<p>{html.escape(part, quote=True)}</p>"
        for part in str(extracted_text or "").splitlines()
        if part.strip()
    ]
    body = "".join(paragraphs) or "<p></p>"
    return f"<article><h1>{safe_title}</h1>{body}</article>"


def configure_document_studio_router(
    persistence_provider, media_collection, notifications_collection
) -> None:
    global \
        documents_coll, \
        versions_coll, \
        profiles_coll, \
        company_versions_coll, \
        folders_coll, \
        collections_coll, \
        templates_coll, \
        template_versions_coll, \
        tags_coll, \
        people_coll, \
        banks_coll, \
        clauses_coll, \
        media_coll, \
        notifications_coll
    if (
        isinstance(persistence_provider, SQLitePersistenceProvider)
        and not persistence_provider.ready
    ):
        persistence_provider._initialize_sync()
    documents_coll = LocalPersistenceCollection(persistence_provider, "documents")
    versions_coll = LocalPersistenceCollection(persistence_provider, "document_versions")
    profiles_coll = LocalPersistenceCollection(persistence_provider, "company_profiles")
    company_versions_coll = LocalPersistenceCollection(persistence_provider, "company_versions")
    folders_coll = LocalPersistenceCollection(persistence_provider, "document_folders")
    collections_coll = LocalPersistenceCollection(persistence_provider, "document_collections")
    templates_coll = LocalPersistenceCollection(
        persistence_provider, "enterprise_document_templates"
    )
    template_versions_coll = LocalPersistenceCollection(
        persistence_provider, "enterprise_document_template_versions"
    )
    tags_coll = LocalPersistenceCollection(persistence_provider, "document_tags")
    people_coll = LocalPersistenceCollection(persistence_provider, "document_people")
    banks_coll = LocalPersistenceCollection(persistence_provider, "document_banks")
    clauses_coll = LocalPersistenceCollection(persistence_provider, "document_clauses")
    media_coll = media_collection
    notifications_coll = notifications_collection


async def _profile(owner: str, profile_id: str | None = None) -> CompanyProfile:
    query = {"owner_email": owner}
    if profile_id:
        query["id"] = profile_id
    doc = await profiles_coll.find_one(query, {"_id": 0})
    if doc:
        return CompanyProfile(**doc)
    profile = CompanyProfile(owner_email=owner)
    await profiles_coll.insert_one(profile.model_dump())
    return profile


async def _document(document_id: str, owner: str) -> CorporateDocument:
    doc = await documents_coll.find_one({"id": document_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document not found")
    return CorporateDocument(**doc)


async def _validate_folder(folder_id: str | None, owner: str) -> str | None:
    normalized = str(folder_id or "").strip() or None
    if normalized and not await folders_coll.find_one(
        {"id": normalized, "owner_email": owner}, {"_id": 0, "id": 1}
    ):
        raise HTTPException(404, "Folder not found")
    return normalized


async def _validate_collection_ids(collection_ids: list, owner: str) -> list[str]:
    requested = list(
        dict.fromkeys(str(item).strip() for item in collection_ids if str(item).strip())
    )[:100]
    if not requested:
        return []
    existing = {
        item["id"]
        async for item in collections_coll.find(
            {"owner_email": owner, "id": {"$in": requested}}, {"_id": 0, "id": 1}
        )
    }
    missing = [item for item in requested if item not in existing]
    if missing:
        raise HTTPException(404, {"message": "Collection not found", "ids": missing})
    return requested


async def _save_version(document: CorporateDocument, owner: str, note: str) -> DocumentVersion:
    version = DocumentVersion(
        document_id=document.id,
        owner_email=owner,
        version_number=document.version_number,
        title=document.title,
        content_html=document.content_html,
        content_text=document.content_text,
        change_note=note,
        metadata=document.metadata,
    )
    await versions_coll.insert_one(version.model_dump())
    return version


async def _save_company_version(profile: CompanyProfile, owner: str, note: str) -> CompanyVersion:
    count = await company_versions_coll.count_documents(
        {"company_profile_id": profile.id, "owner_email": owner}
    )
    version = CompanyVersion(
        company_profile_id=profile.id,
        owner_email=owner,
        version_number=count + 1,
        snapshot=profile.model_dump(),
        change_note=note,
        changed_by=owner,
    )
    await company_versions_coll.insert_one(version.model_dump())
    return version


async def _save_template_version(
    template: EnterpriseDocumentTemplate, owner: str, note: str
) -> DocumentTemplateVersion:
    version = DocumentTemplateVersion(
        template_id=template.id,
        owner_email=owner,
        version_number=template.version_number,
        name=template.name,
        content_html=template.content_html,
        merge_schema=template.merge_schema,
        change_note=note,
    )
    await template_versions_coll.insert_one(version.model_dump())
    return version


async def _hydrate_profile(owner: str, profile: CompanyProfile) -> CompanyProfile:
    data = profile.model_dump()
    people = [
        CorporatePerson(**doc).model_dump()
        async for doc in people_coll.find(
            {"owner_email": owner, "company_profile_id": profile.id}, {"_id": 0}
        ).sort("full_name", 1)
    ]
    banks = [
        BankProfile(**doc).model_dump()
        async for doc in banks_coll.find(
            {"owner_email": owner, "company_profile_id": profile.id}, {"_id": 0}
        ).sort("bank_name", 1)
    ]
    data["members"] = [
        p
        for p in people
        if "member" in p.get("relationship_to_company", "").lower()
        or "member" in p.get("role", "").lower()
    ]
    data["managers"] = [p for p in people if "manager" in p.get("role", "").lower()]
    data["directors"] = [p for p in people if "director" in p.get("role", "").lower()]
    data["authorized_signatories"] = [
        p
        for p in people
        if "sign" in p.get("role", "").lower() or "authority" in p.get("authority", "").lower()
    ]
    data["bank_accounts"] = banks
    return CompanyProfile(**data)


@router.get("/templates")
async def list_templates(_: str = Depends(require_owner)) -> dict:
    return {
        "templates": [template.model_dump() for template in TEMPLATES],
        "categories": sorted({template.category for template in TEMPLATES}),
        "document_types": DOCUMENT_TYPE_CATALOG,
        "document_classes": {
            key: value["label"] for key, value in DOCUMENT_CLASS_DEFINITIONS.items()
        },
        "export_formats": sorted(EXPORT_FORMATS),
        "cover_styles": COVER_STYLES,
        "component_library": COMPONENT_LIBRARY,
        "smart_table_types": SMART_TABLE_TYPES,
        "chart_types": CHART_TYPES,
        "package_types": PACKAGE_TYPES,
        "clause_library": [clause.model_dump() for clause in CLAUSE_LIBRARY],
        "marketplace_architecture": {
            "template_roots": ["backend/document_studio/templates", "memory/document_templates"],
            "schema": "CorporateTemplate.design_schema",
            "hot_add": True,
        },
    }


@router.get("/template-library", response_model=list[EnterpriseDocumentTemplate])
async def list_template_library(
    owner: str = Depends(require_owner), q: str = "", category: str = "", tag: str = ""
) -> list[EnterpriseDocumentTemplate]:
    query: dict = {"owner_email": owner}
    if category:
        query["category"] = category
    if tag:
        query["tags"] = tag
    if q.strip():
        query["$or"] = [
            {"name": {"$regex": q.strip(), "$options": "i"}},
            {"description": {"$regex": q.strip(), "$options": "i"}},
            {"tags": {"$regex": q.strip(), "$options": "i"}},
        ]
    return [
        EnterpriseDocumentTemplate(**doc)
        async for doc in templates_coll.find(query, {"_id": 0}).sort("updated_at", -1)
    ]


@router.post("/template-library", response_model=EnterpriseDocumentTemplate)
async def create_template_library_item(
    body: dict, owner: str = Depends(require_owner)
) -> EnterpriseDocumentTemplate:
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Template name is required")
    template = EnterpriseDocumentTemplate(
        owner_email=owner,
        name=name,
        category=str(body.get("category") or "General"),
        description=str(body.get("description") or ""),
        tags=[str(tag).strip() for tag in body.get("tags", []) if str(tag).strip()][:20],
        content_html=str(body.get("content_html") or "<article><h1>{{title}}</h1></article>"),
        merge_schema=body.get("merge_schema") or {"required": ["title"]},
        metadata=body.get("metadata") or {},
    )
    await templates_coll.insert_one(template.model_dump())
    await _save_template_version(template, owner, "Created template")
    return template


@router.patch("/template-library/{template_id}", response_model=EnterpriseDocumentTemplate)
async def update_template_library_item(
    template_id: str, body: dict, owner: str = Depends(require_owner)
) -> EnterpriseDocumentTemplate:
    doc = await templates_coll.find_one({"id": template_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Template not found")
    if doc.get("locked") and not body.get("unlock"):
        raise HTTPException(423, "Template is locked")
    data = {**doc}
    for field in (
        "name",
        "category",
        "description",
        "tags",
        "favorite",
        "locked",
        "content_html",
        "merge_schema",
        "metadata",
    ):
        if field in body:
            data[field] = body[field]
    if any(field in body for field in ("content_html", "merge_schema", "name")):
        data["version_number"] = int(data.get("version_number", 1)) + 1
    data["updated_at"] = now_iso()
    template = EnterpriseDocumentTemplate(**data)
    await templates_coll.replace_one(
        {"id": template_id, "owner_email": owner}, template.model_dump()
    )
    await _save_template_version(
        template, owner, str(body.get("change_note") or "Updated template")
    )
    return template


@router.post("/template-library/{template_id}/{action}", response_model=EnterpriseDocumentTemplate)
async def template_action(
    template_id: str, action: str, owner: str = Depends(require_owner)
) -> EnterpriseDocumentTemplate:
    doc = await templates_coll.find_one({"id": template_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Template not found")
    data = {**doc, "updated_at": now_iso()}
    if action == "duplicate":
        data.update(
            {
                "id": EnterpriseDocumentTemplate(owner_email=owner, name=data["name"]).id,
                "name": f"Copy of {data['name']}",
                "status": "draft",
                "locked": False,
                "created_at": now_iso(),
                "version_number": 1,
            }
        )
        template = EnterpriseDocumentTemplate(**data)
        await templates_coll.insert_one(template.model_dump())
        await _save_template_version(template, owner, "Duplicated template")
        return template
    status_map = {
        "publish": "published",
        "draft": "draft",
        "archive": "archived",
        "lock": "draft",
        "favorite": data.get("status", "draft"),
        "use": data.get("status", "draft"),
    }
    if action not in status_map:
        raise HTTPException(400, "Unsupported template action")
    data["status"] = status_map[action]
    if action == "lock":
        data["locked"] = True
    if action == "favorite":
        data["favorite"] = not bool(data.get("favorite"))
    if action == "use":
        data["recently_used_at"] = now_iso()
    template = EnterpriseDocumentTemplate(**data)
    await templates_coll.replace_one(
        {"id": template_id, "owner_email": owner}, template.model_dump()
    )
    await _save_template_version(template, owner, f"Template action: {action}")
    return template


@router.delete("/template-library/{template_id}")
async def delete_template_library_item(
    template_id: str, owner: str = Depends(require_owner)
) -> dict:
    result = await templates_coll.delete_one({"id": template_id, "owner_email": owner})
    if not result.deleted_count:
        raise HTTPException(404, "Template not found")
    await template_versions_coll.delete_many({"template_id": template_id, "owner_email": owner})
    return {"ok": True, "template_id": template_id}


@router.post("/template-library/{template_id}/merge")
async def merge_template_library_item(
    template_id: str, body: dict, owner: str = Depends(require_owner)
) -> dict:
    doc = await templates_coll.find_one({"id": template_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Template not found")
    template = EnterpriseDocumentTemplate(**doc)
    content_html, content_text, diagnostics = render_merge_template(
        template.content_html, body.get("variables") or {}, template.merge_schema
    )
    return {"content_html": content_html, "content_text": content_text, "diagnostics": diagnostics}


@router.get(
    "/template-library/{template_id}/versions", response_model=list[DocumentTemplateVersion]
)
async def list_template_versions(
    template_id: str, owner: str = Depends(require_owner)
) -> list[DocumentTemplateVersion]:
    await templates_coll.find_one({"id": template_id, "owner_email": owner}, {"_id": 0})
    return [
        DocumentTemplateVersion(**doc)
        async for doc in template_versions_coll.find(
            {"template_id": template_id, "owner_email": owner}, {"_id": 0}
        ).sort("version_number", -1)
    ]


@router.get("/template-library/{template_id}/preview")
async def preview_template_library_item(
    template_id: str, owner: str = Depends(require_owner)
) -> Response:
    doc = await templates_coll.find_one({"id": template_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Template not found")
    template = EnterpriseDocumentTemplate(**doc)
    sample = {
        "title": template.name,
        "company": "Sample Company Ltd",
        "signer": "Authorized Signatory",
        "fees": [{"name": "Professional Fee", "amount": 1250}],
    }
    content_html, _, _ = render_merge_template(template.content_html, sample, template.merge_schema)
    return Response(content=content_html, media_type="text/html")


@router.post("/template-library/{template_id}/validate")
async def validate_template_library_item(
    template_id: str, body: dict | None = None, owner: str = Depends(require_owner)
) -> dict:
    doc = await templates_coll.find_one({"id": template_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Template not found")
    template = EnterpriseDocumentTemplate(**doc)
    variables = (body or {}).get("variables") or {}
    validation = validate_merge_template(template.content_html, template.merge_schema)
    _, _, merge_diagnostics = render_merge_template(
        template.content_html, variables, template.merge_schema
    )
    return {"template": validation, "merge": merge_diagnostics}


@router.post(
    "/template-library/{template_id}/versions/{version_id}/restore",
    response_model=EnterpriseDocumentTemplate,
)
async def restore_template_version(
    template_id: str, version_id: str, owner: str = Depends(require_owner)
) -> EnterpriseDocumentTemplate:
    current = await templates_coll.find_one({"id": template_id, "owner_email": owner}, {"_id": 0})
    version_doc = await template_versions_coll.find_one(
        {"id": version_id, "template_id": template_id, "owner_email": owner}, {"_id": 0}
    )
    if not current or not version_doc:
        raise HTTPException(404, "Template version not found")
    version = DocumentTemplateVersion(**version_doc)
    data = {**current}
    data.update(
        {
            "name": version.name,
            "content_html": version.content_html,
            "merge_schema": version.merge_schema,
            "version_number": int(data.get("version_number", 1)) + 1,
            "updated_at": now_iso(),
        }
    )
    restored = EnterpriseDocumentTemplate(**data)
    await templates_coll.replace_one(
        {"id": template_id, "owner_email": owner}, restored.model_dump()
    )
    await _save_template_version(
        restored, owner, f"Restored template version {version.version_number}"
    )
    return restored


@router.post("/classify")
async def classify_request(body: dict, owner: str = Depends(require_owner)) -> dict:
    profile = await _profile(owner, body.get("company_profile_id"))
    classification = classify_document_request(
        str(body.get("prompt") or ""),
        str(body.get("title") or ""),
        str(body.get("selected_type") or body.get("template_id") or ""),
    )
    fields = extract_smart_fields(
        str(body.get("prompt") or ""), profile, str(body.get("title") or "")
    )
    return {
        "document_class": classification,
        "smart_fields": fields,
        "schema": DOCUMENT_CLASS_DEFINITIONS[classification["key"]],
    }


@router.get("/company-profile", response_model=CompanyProfile)
async def get_company_profile(owner: str = Depends(require_owner)) -> CompanyProfile:
    return await _hydrate_profile(owner, await _profile(owner))


@router.get("/companies", response_model=list[CompanyProfile])
async def list_company_profiles(
    owner: str = Depends(require_owner),
    include_archived: bool = False,
    include_deleted: bool = False,
) -> list[CompanyProfile]:
    query = {"owner_email": owner}
    if not include_archived:
        query["archived"] = False
    if not include_deleted:
        query["deleted"] = False
    profiles = [
        CompanyProfile(**doc)
        async for doc in profiles_coll.find(query, {"_id": 0}).sort("company_name", 1)
    ]
    if not profiles:
        profiles = [await _profile(owner)]
    return [await _hydrate_profile(owner, profile) for profile in profiles]


@router.post("/companies", response_model=CompanyProfile)
async def create_company_profile(body: dict, owner: str = Depends(require_owner)) -> CompanyProfile:
    profile = CompanyProfile(
        owner_email=owner,
        **{
            k: v
            for k, v in body.items()
            if k not in {"id", "owner_email", "created_at", "updated_at"}
        },
    )
    await profiles_coll.insert_one(profile.model_dump())
    await _save_company_version(profile, owner, "Created company profile")
    return await _hydrate_profile(owner, profile)


@router.get("/companies/search", response_model=list[CompanyProfile])
async def search_companies(
    q: str = "", owner: str = Depends(require_owner)
) -> list[CompanyProfile]:
    term = q.strip()
    if not term:
        return await list_company_profiles(owner, include_archived=True, include_deleted=False)
    people = [
        CorporatePerson(**doc)
        async for doc in people_coll.find(
            {
                "owner_email": owner,
                "$or": [
                    {"full_name": {"$regex": term, "$options": "i"}},
                    {"passport": {"$regex": term, "$options": "i"}},
                    {"government_id": {"$regex": term, "$options": "i"}},
                ],
            },
            {"_id": 0},
        )
    ]
    banks = [
        BankProfile(**doc)
        async for doc in banks_coll.find(
            {
                "owner_email": owner,
                "$or": [
                    {"bank_name": {"$regex": term, "$options": "i"}},
                    {"swift": {"$regex": term, "$options": "i"}},
                    {"iban": {"$regex": term, "$options": "i"}},
                ],
            },
            {"_id": 0},
        )
    ]
    ids = {item.company_profile_id for item in people + banks if item.company_profile_id}
    profiles = [
        CompanyProfile(**doc)
        async for doc in profiles_coll.find(
            {
                "owner_email": owner,
                "deleted": False,
                "$or": [
                    {"company_name": {"$regex": term, "$options": "i"}},
                    {"registration_number": {"$regex": term, "$options": "i"}},
                    {"jurisdiction": {"$regex": term, "$options": "i"}},
                ],
            },
            {"_id": 0},
        )
    ]
    extra = [
        CompanyProfile(**doc)
        async for doc in profiles_coll.find(
            {"owner_email": owner, "id": {"$in": list(ids)}}, {"_id": 0}
        )
    ]
    unique = {profile.id: profile for profile in profiles + extra}
    return [await _hydrate_profile(owner, profile) for profile in unique.values()]


@router.get("/companies/{company_id}", response_model=CompanyProfile)
async def get_company(company_id: str, owner: str = Depends(require_owner)) -> CompanyProfile:
    return await _hydrate_profile(owner, await _profile(owner, company_id))


@router.patch("/companies/{company_id}", response_model=CompanyProfile)
async def update_company(
    company_id: str, body: dict, owner: str = Depends(require_owner)
) -> CompanyProfile:
    current = await _profile(owner, company_id)
    data = current.model_dump()
    for key, value in body.items():
        if key not in {"id", "owner_email", "created_at"}:
            data[key] = value
    data["updated_at"] = now_iso()
    updated = CompanyProfile(**data)
    await profiles_coll.replace_one(
        {"id": company_id, "owner_email": owner}, updated.model_dump(), upsert=True
    )
    await _save_company_version(
        updated, owner, str(body.get("change_note") or "Updated company profile")
    )
    return await _hydrate_profile(owner, updated)


@router.post("/companies/{company_id}/{action}", response_model=CompanyProfile)
async def company_lifecycle(
    company_id: str, action: str, owner: str = Depends(require_owner)
) -> CompanyProfile:
    current = await _profile(owner, company_id)
    data = current.model_dump()
    if action == "archive":
        data["archived"] = True
    elif action == "restore":
        data["archived"] = False
        data["deleted"] = False
    elif action == "delete":
        data["deleted"] = True
        data["archived"] = True
    elif action == "hard-delete":
        await profiles_coll.delete_one({"id": company_id, "owner_email": owner})
        await people_coll.delete_many({"company_profile_id": company_id, "owner_email": owner})
        await banks_coll.delete_many({"company_profile_id": company_id, "owner_email": owner})
        return current
    else:
        raise HTTPException(400, "Unsupported company lifecycle action")
    data["updated_at"] = now_iso()
    updated = CompanyProfile(**data)
    await profiles_coll.replace_one(
        {"id": company_id, "owner_email": owner}, updated.model_dump(), upsert=True
    )
    await _save_company_version(updated, owner, action)
    return await _hydrate_profile(owner, updated)


@router.get("/companies/{company_id}/versions", response_model=list[CompanyVersion])
async def list_company_versions(
    company_id: str, owner: str = Depends(require_owner)
) -> list[CompanyVersion]:
    return [
        CompanyVersion(**doc)
        async for doc in company_versions_coll.find(
            {"company_profile_id": company_id, "owner_email": owner}, {"_id": 0}
        ).sort("version_number", -1)
    ]


@router.post("/companies/{company_id}/versions/{version_id}/restore", response_model=CompanyProfile)
async def restore_company_version(
    company_id: str, version_id: str, owner: str = Depends(require_owner)
) -> CompanyProfile:
    version_doc = await company_versions_coll.find_one(
        {"id": version_id, "company_profile_id": company_id, "owner_email": owner}, {"_id": 0}
    )
    if not version_doc:
        raise HTTPException(404, "Company version not found")
    snapshot = CompanyVersion(**version_doc).snapshot
    snapshot["updated_at"] = now_iso()
    restored = CompanyProfile(**snapshot)
    await profiles_coll.replace_one(
        {"id": company_id, "owner_email": owner}, restored.model_dump(), upsert=True
    )
    await _save_company_version(restored, owner, f"Restored company version {version_id}")
    return await _hydrate_profile(owner, restored)


@router.put("/company-profile", response_model=CompanyProfile)
async def save_company_profile(body: dict, owner: str = Depends(require_owner)) -> CompanyProfile:
    current = await _profile(owner, body.get("id"))
    data = current.model_dump()
    for field in (
        "company_name",
        "trading_name",
        "legal_form",
        "jurisdiction",
        "registration_number",
        "ein_tax_number",
        "vat_number",
        "registered_office",
        "principal_office",
        "formation_date",
        "status",
        "standing",
        "capital",
        "website",
        "phone",
        "email",
        "corporate_seal",
        "default_signature",
        "corporate_logo",
        "compliance_notes",
        "logo_media_id",
        "primary_color",
        "secondary_color",
        "accent_color",
        "font_heading",
        "font_body",
        "signatures",
        "addresses",
        "contact_information",
        "legal_information",
        "branding_system",
    ):
        if field in body:
            data[field] = body[field]
    data["updated_at"] = now_iso()
    await profiles_coll.replace_one({"id": current.id, "owner_email": owner}, data, upsert=True)
    await documents_coll.update_many(
        {"owner_email": owner, "company_profile_id": current.id},
        {
            "$set": {
                "metadata.branding_revision": data["updated_at"],
                "updated_at": data["updated_at"],
            }
        },
    )
    return await _hydrate_profile(owner, CompanyProfile(**data))


@router.get("/people", response_model=list[CorporatePerson])
async def list_people(
    company_profile_id: str = "", owner: str = Depends(require_owner)
) -> list[CorporatePerson]:
    query = {"owner_email": owner}
    if company_profile_id:
        query["company_profile_id"] = company_profile_id
    return [
        CorporatePerson(**doc)
        async for doc in people_coll.find(query, {"_id": 0}).sort("full_name", 1)
    ]


@router.post("/people", response_model=CorporatePerson)
async def save_person(body: dict, owner: str = Depends(require_owner)) -> CorporatePerson:
    data = {**body, "owner_email": owner, "updated_at": now_iso()}
    person = CorporatePerson(**data)
    await people_coll.replace_one(
        {"id": person.id, "owner_email": owner}, person.model_dump(), upsert=True
    )
    return person


@router.get("/banks", response_model=list[BankProfile])
async def list_banks(
    company_profile_id: str = "", owner: str = Depends(require_owner)
) -> list[BankProfile]:
    query = {"owner_email": owner}
    if company_profile_id:
        query["company_profile_id"] = company_profile_id
    return [
        BankProfile(**doc) async for doc in banks_coll.find(query, {"_id": 0}).sort("bank_name", 1)
    ]


@router.post("/banks", response_model=BankProfile)
async def save_bank(body: dict, owner: str = Depends(require_owner)) -> BankProfile:
    data = {**body, "owner_email": owner, "updated_at": now_iso()}
    bank = BankProfile(**data)
    await banks_coll.replace_one(
        {"id": bank.id, "owner_email": owner}, bank.model_dump(), upsert=True
    )
    return bank


@router.post("/companies/{company_id}/upload")
async def upload_company_asset(
    company_id: str,
    file: Annotated[UploadFile, File(...)],
    kind: Annotated[str, Form()] = "certificate",
    owner: str = Depends(require_owner),
) -> dict:
    profile = await _profile(owner, company_id)
    data = await file.read()
    if not data or len(data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(400, "Upload must be between 1 byte and 50 MB")
    filename, _, size = save_bytes(
        data, file.content_type or "application/octet-stream", kind="company_registry"
    )
    media = MediaAsset(
        owner_email=owner,
        filename=filename,
        mime_type=file.content_type or "application/octet-stream",
        kind="company_registry",
        size_bytes=size,
        source_module="corporate-registry",
        edit_note=f"company-asset:{kind}",
    )
    await media_coll.insert_one(media.model_dump())
    data_profile = profile.model_dump()
    asset = {
        "kind": kind,
        "media_id": media.id,
        "filename": file.filename or filename,
        "uploaded_at": now_iso(),
    }
    if kind == "logo":
        data_profile["corporate_logo"] = media.id
        data_profile["logo_media_id"] = media.id
    elif kind == "seal":
        data_profile["corporate_seal"] = media.id
    elif kind in {"signature", "initials"}:
        data_profile.setdefault("signatures", []).append(asset)
        if kind == "signature":
            data_profile["default_signature"] = media.id
    else:
        data_profile.setdefault("certificates", []).append(asset)
    data_profile["updated_at"] = now_iso()
    updated = CompanyProfile(**data_profile)
    await profiles_coll.replace_one(
        {"id": company_id, "owner_email": owner}, updated.model_dump(), upsert=True
    )
    await _save_company_version(updated, owner, f"Uploaded {kind}")
    return {"ok": True, "media_id": media.id, "asset": asset, "company": updated.model_dump()}


@router.get("/companies/{company_id}/dashboard")
async def company_dashboard(company_id: str, owner: str = Depends(require_owner)) -> dict:
    profile = await _hydrate_profile(owner, await _profile(owner, company_id))
    docs = [
        CorporateDocument(**doc)
        async for doc in documents_coll.find(
            {"owner_email": owner, "company_profile_id": company_id}, {"_id": 0}
        )
        .sort("updated_at", -1)
        .limit(10)
    ]
    versions = [
        CompanyVersion(**doc)
        async for doc in company_versions_coll.find(
            {"owner_email": owner, "company_profile_id": company_id}, {"_id": 0}
        )
        .sort("created_at", -1)
        .limit(10)
    ]
    score = (
        50
        + min(20, len(profile.authorized_signatories) * 5)
        + min(10, len(profile.bank_accounts) * 5)
        + (10 if profile.registration_number else 0)
        + (
            10
            if profile.compliance_status.lower() in {"active", "compliant", "good standing"}
            or profile.standing.lower() == "good standing"
            else 0
        )
    )
    return {
        "company": profile.model_dump(),
        "recent_documents": [doc.model_dump() for doc in docs],
        "recent_activity": [version.model_dump() for version in versions],
        "corporate_score": min(score, 100),
        "document_count": len(docs),
        "compliance_status": profile.compliance_status or profile.status or "Pending",
    }


@router.get("/companies/{company_id}/export/{fmt}")
async def export_company(
    company_id: str, fmt: str, owner: str = Depends(require_owner)
) -> Response:
    profile = await _hydrate_profile(owner, await _profile(owner, company_id))
    payload = profile.model_dump()
    fmt = fmt.lower()
    if fmt == "json":
        data, mime, ext = (
            __import__("json").dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"),
            "application/json",
            "json",
        )
    elif fmt == "zip":
        import io
        import json
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("company-profile.json", json.dumps(payload, indent=2, ensure_ascii=False))
            zf.writestr("README.txt", f"Corporate Registry package for {profile.company_name}")
        data, mime, ext = buffer.getvalue(), "application/zip", "zip"
    else:
        doc = CorporateDocument(
            owner_email=owner,
            title=f"{profile.company_name} Company Profile",
            document_type="company_profile",
            category="Corporate Registry",
            company_profile_id=profile.id,
            content_text=str(payload),
            content_html=f"<h1>{profile.company_name}</h1><pre>{payload}</pre>",
        )
        data, mime, ext = (
            (render_pdf_bytes(doc, profile), "application/pdf", "pdf")
            if fmt == "pdf"
            else (
                render_docx_bytes(doc, profile),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "docx",
            )
        )
    return Response(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{profile.company_name}.{ext}"'},
    )


@router.get("/clauses", response_model=list[ClauseTemplate])
async def list_clauses(
    category: str = "", owner: str = Depends(require_owner)
) -> list[ClauseTemplate]:
    custom = [
        ClauseTemplate(**doc)
        async for doc in clauses_coll.find({"owner_email": owner}, {"_id": 0}).sort("title", 1)
    ]
    clauses = [*CLAUSE_LIBRARY, *custom]
    return [
        clause for clause in clauses if not category or clause.category.lower() == category.lower()
    ]


@router.post("/clauses", response_model=ClauseTemplate)
async def save_clause(body: dict, owner: str = Depends(require_owner)) -> ClauseTemplate:
    clause = ClauseTemplate(**{**body, "owner_email": owner, "updated_at": now_iso()})
    await clauses_coll.replace_one(
        {"id": clause.id, "owner_email": owner}, clause.model_dump(), upsert=True
    )
    return clause


@router.get("/folders", response_model=list[DocumentFolder])
async def list_folders(owner: str = Depends(require_owner)) -> list[DocumentFolder]:
    return [
        DocumentFolder(**doc)
        async for doc in folders_coll.find({"owner_email": owner}, {"_id": 0}).sort("name", 1)
    ]


@router.post("/folders", response_model=DocumentFolder)
async def create_folder(body: dict, owner: str = Depends(require_owner)) -> DocumentFolder:
    name = str(body.get("name") or "").strip()
    parent_id = body.get("parent_id")
    if not name:
        raise HTTPException(400, "Folder name is required")
    if parent_id:
        parent = await folders_coll.find_one({"id": parent_id, "owner_email": owner}, {"_id": 0})
        if not parent:
            raise HTTPException(404, "Parent folder not found")
    duplicate = await folders_coll.find_one(
        {"owner_email": owner, "name": name, "parent_id": parent_id}, {"_id": 0}
    )
    if duplicate:
        raise HTTPException(409, "A folder with this name already exists")
    folder = DocumentFolder(owner_email=owner, name=name, parent_id=parent_id)
    await folders_coll.insert_one(folder.model_dump())
    return folder


@router.put("/folders/{folder_id}", response_model=DocumentFolder)
async def rename_folder(
    folder_id: str, body: dict, owner: str = Depends(require_owner)
) -> DocumentFolder:
    current = await folders_coll.find_one(
        {"id": folder_id, "owner_email": owner}, {"_id": 0}
    )
    if not current:
        raise HTTPException(404, "Folder not found")
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Folder name is required")
    duplicate = await folders_coll.find_one(
        {
            "owner_email": owner,
            "name": name,
            "parent_id": current.get("parent_id"),
            "id": {"$ne": folder_id},
        },
        {"_id": 0},
    )
    if duplicate:
        raise HTTPException(409, "A folder with this name already exists")
    updated = DocumentFolder(**{**current, "name": name, "updated_at": now_iso()})
    await folders_coll.replace_one(
        {"id": folder_id, "owner_email": owner}, updated.model_dump()
    )
    return updated


@router.post("/folders/{folder_id}/move", response_model=DocumentFolder)
async def move_folder(
    folder_id: str, body: dict, owner: str = Depends(require_owner)
) -> DocumentFolder:
    current = await folders_coll.find_one(
        {"id": folder_id, "owner_email": owner}, {"_id": 0}
    )
    if not current:
        raise HTTPException(404, "Folder not found")
    parent_id = body.get("parent_id") or None
    if parent_id == folder_id:
        raise HTTPException(400, "A folder cannot be nested inside itself")
    ancestor_id = parent_id
    visited: set[str] = set()
    while ancestor_id:
        if ancestor_id == folder_id:
            raise HTTPException(400, "A folder cannot be moved into one of its descendants")
        if ancestor_id in visited:
            raise HTTPException(409, "The folder hierarchy contains a cycle")
        visited.add(ancestor_id)
        ancestor = await folders_coll.find_one(
            {"id": ancestor_id, "owner_email": owner}, {"_id": 0}
        )
        if not ancestor:
            raise HTTPException(404, "Parent folder not found")
        ancestor_id = ancestor.get("parent_id")
    duplicate = await folders_coll.find_one(
        {
            "owner_email": owner,
            "name": current["name"],
            "parent_id": parent_id,
            "id": {"$ne": folder_id},
        },
        {"_id": 0},
    )
    if duplicate:
        raise HTTPException(409, "A folder with this name already exists")
    updated = DocumentFolder(
        **{**current, "parent_id": parent_id, "updated_at": now_iso()}
    )
    await folders_coll.replace_one(
        {"id": folder_id, "owner_email": owner}, updated.model_dump()
    )
    return updated


@router.delete("/folders/{folder_id}")
async def delete_folder(folder_id: str, owner: str = Depends(require_owner)) -> dict:
    result = await folders_coll.delete_one({"id": folder_id, "owner_email": owner})
    if not result.deleted_count:
        raise HTTPException(404, "Folder not found")
    timestamp = now_iso()
    await folders_coll.update_many(
        {"owner_email": owner, "parent_id": folder_id},
        {"$set": {"parent_id": None, "updated_at": timestamp}},
    )
    await documents_coll.update_many(
        {"owner_email": owner, "folder_id": folder_id},
        {"$set": {"folder_id": None, "updated_at": timestamp}},
    )
    return {"ok": True, "folder_id": folder_id}


@router.get("/collections", response_model=list[DocumentCollection])
async def list_collections(
    owner: str = Depends(require_owner), q: str = "", parent_id: str | None = None
) -> list[DocumentCollection]:
    query: dict = {"owner_email": owner}
    if parent_id is not None:
        query["parent_id"] = parent_id or None
    if q.strip():
        query["$or"] = [
            {"name": {"$regex": q.strip(), "$options": "i"}},
            {"description": {"$regex": q.strip(), "$options": "i"}},
        ]
    return [
        DocumentCollection(**doc)
        async for doc in collections_coll.find(query, {"_id": 0}).sort("name", 1)
    ]


@router.post("/collections", response_model=DocumentCollection)
async def create_collection(body: dict, owner: str = Depends(require_owner)) -> DocumentCollection:
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Collection name is required")
    parent_id = body.get("parent_id") or None
    if parent_id and not await collections_coll.find_one({"id": parent_id, "owner_email": owner}):
        raise HTTPException(404, "Parent collection not found")
    duplicate = await collections_coll.find_one(
        {"owner_email": owner, "name": name, "parent_id": parent_id}, {"_id": 0}
    )
    if duplicate:
        raise HTTPException(409, "A collection with this name already exists")
    document_ids = [str(item) for item in body.get("document_ids", [])][:500]
    if document_ids:
        existing = {
            doc["id"]
            async for doc in documents_coll.find(
                {"owner_email": owner, "id": {"$in": document_ids}}, {"_id": 0, "id": 1}
            )
        }
        document_ids = [item for item in document_ids if item in existing]
    collection = DocumentCollection(
        owner_email=owner,
        name=name,
        description=str(body.get("description") or ""),
        parent_id=parent_id,
        document_ids=document_ids,
        smart_query=body.get("smart_query") or {},
        color=str(body.get("color") or "#B9985A"),
        icon=str(body.get("icon") or "collection"),
    )
    await collections_coll.insert_one(collection.model_dump())
    if document_ids:
        await documents_coll.update_many(
            {"owner_email": owner, "id": {"$in": document_ids}},
            {"$addToSet": {"collection_ids": collection.id}, "$set": {"updated_at": now_iso()}},
        )
    return collection


@router.patch("/collections/{collection_id}", response_model=DocumentCollection)
async def update_collection(
    collection_id: str, body: dict, owner: str = Depends(require_owner)
) -> DocumentCollection:
    current = await collections_coll.find_one(
        {"id": collection_id, "owner_email": owner}, {"_id": 0}
    )
    if not current:
        raise HTTPException(404, "Collection not found")
    data = {**current}
    for field in ("name", "description", "parent_id", "smart_query", "color", "icon"):
        if field in body:
            data[field] = body[field]
    data["name"] = str(data.get("name") or "").strip()
    if not data["name"]:
        raise HTTPException(400, "Collection name is required")
    data["parent_id"] = data.get("parent_id") or None
    if data["parent_id"] == collection_id:
        raise HTTPException(400, "A collection cannot be nested inside itself")
    ancestor_id = data["parent_id"]
    visited: set[str] = set()
    while ancestor_id:
        if ancestor_id == collection_id:
            raise HTTPException(400, "A collection cannot be moved into one of its descendants")
        if ancestor_id in visited:
            raise HTTPException(409, "The collection hierarchy contains a cycle")
        visited.add(ancestor_id)
        ancestor = await collections_coll.find_one(
            {"id": ancestor_id, "owner_email": owner}, {"_id": 0}
        )
        if not ancestor:
            raise HTTPException(404, "Parent collection not found")
        ancestor_id = ancestor.get("parent_id")
    duplicate = await collections_coll.find_one(
        {
            "owner_email": owner,
            "name": data["name"],
            "parent_id": data["parent_id"],
            "id": {"$ne": collection_id},
        },
        {"_id": 0},
    )
    if duplicate:
        raise HTTPException(409, "A collection with this name already exists")
    if "document_ids" in body:
        requested = list(
            dict.fromkeys(
                str(item).strip()
                for item in body.get("document_ids", [])
                if str(item).strip()
            )
        )[:500]
        existing = {
            item["id"]
            async for item in documents_coll.find(
                {"owner_email": owner, "id": {"$in": requested}}, {"_id": 0, "id": 1}
            )
        }
        missing = [item for item in requested if item not in existing]
        if missing:
            raise HTTPException(404, {"message": "Document not found", "ids": missing})
        data["document_ids"] = requested
    data["updated_at"] = now_iso()
    updated = DocumentCollection(**data)
    await collections_coll.replace_one(
        {"id": collection_id, "owner_email": owner}, updated.model_dump()
    )
    await documents_coll.update_many(
        {"owner_email": owner}, {"$pull": {"collection_ids": collection_id}}
    )
    if updated.document_ids:
        await documents_coll.update_many(
            {"owner_email": owner, "id": {"$in": updated.document_ids}},
            {"$addToSet": {"collection_ids": collection_id}, "$set": {"updated_at": now_iso()}},
        )
    return updated


@router.delete("/collections/{collection_id}")
async def delete_collection(collection_id: str, owner: str = Depends(require_owner)) -> dict:
    result = await collections_coll.delete_one({"id": collection_id, "owner_email": owner})
    if not result.deleted_count:
        raise HTTPException(404, "Collection not found")
    timestamp = now_iso()
    await collections_coll.update_many(
        {"owner_email": owner, "parent_id": collection_id},
        {"$set": {"parent_id": None, "updated_at": timestamp}},
    )
    await documents_coll.update_many(
        {"owner_email": owner},
        {"$pull": {"collection_ids": collection_id}, "$set": {"updated_at": timestamp}},
    )
    return {"ok": True, "collection_id": collection_id}


@router.get("/tags", response_model=list[DocumentTag])
async def list_tags(owner: str = Depends(require_owner)) -> list[DocumentTag]:
    return [
        DocumentTag(**doc)
        async for doc in tags_coll.find({"owner_email": owner}, {"_id": 0}).sort("name", 1)
    ]


@router.post("/tags", response_model=DocumentTag)
async def create_tag(body: dict, owner: str = Depends(require_owner)) -> DocumentTag:
    import re

    name = str(body.get("name") or "").strip()
    color = str(body.get("color") or "#B9985A").strip()
    if not name:
        raise HTTPException(400, "Tag name is required")
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        raise HTTPException(400, "Tag color must use #RRGGBB format")
    existing = await tags_coll.find_one(
        {"owner_email": owner, "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}},
        {"_id": 0},
    )
    if existing:
        raise HTTPException(409, "Tag already exists")
    tag = DocumentTag(owner_email=owner, name=name, color=color.upper())
    await tags_coll.insert_one(tag.model_dump())
    return tag


@router.get("", response_model=list[CorporateDocument])
async def list_documents(
    owner: str = Depends(require_owner),
    q: str = "",
    category: str = "",
    tag: str = "",
    folder_id: str = "",
    collection_id: str = "",
    status: str = "",
    country: str = "",
    language: str = "",
    favorite: bool | None = None,
    limit: int = 100,
) -> list[CorporateDocument]:
    query: dict = {"owner_email": owner}
    if category:
        query["category"] = category
    if tag:
        query["tags"] = tag
    if folder_id:
        query["folder_id"] = folder_id
    if collection_id:
        query["collection_ids"] = collection_id
    if status:
        query["status"] = status
    if country:
        query["country"] = country.strip().upper()
    if language:
        query["language"] = language.strip().lower()
    if favorite is not None:
        query["favorite"] = favorite
    if q.strip():
        query["$or"] = [
            {"title": {"$regex": q.strip(), "$options": "i"}},
            {"searchable_text": {"$regex": q.strip(), "$options": "i"}},
            {"tags": {"$regex": q.strip(), "$options": "i"}},
        ]
    return [
        CorporateDocument(**doc)
        async for doc in documents_coll.find(query, {"_id": 0})
        .sort("updated_at", -1)
        .limit(max(1, min(limit, 200)))
    ]


@router.get("/search", response_model=list[CorporateDocument])
async def search_documents(
    text: str = "",
    category: str = "",
    folder_id: str | None = None,
    collection_id: str = "",
    status: str = "",
    tag: str = "",
    country: str = "",
    language: str = "",
    limit: int = 100,
    owner: str = Depends(require_owner),
) -> list[CorporateDocument]:
    import re

    query: dict = {"owner_email": owner}
    if category.strip():
        query["category"] = category.strip()
    if folder_id:
        query["folder_id"] = folder_id
    if collection_id.strip():
        query["collection_ids"] = collection_id.strip()
    if status.strip():
        query["status"] = status.strip()
    if tag.strip():
        query["tags"] = tag.strip()
    if country.strip():
        query["country"] = country.strip().upper()
    if language.strip():
        query["language"] = language.strip().lower()
    if text.strip():
        escaped = re.escape(text.strip())
        query["$or"] = [
            {"title": {"$regex": escaped, "$options": "i"}},
            {"content_text": {"$regex": escaped, "$options": "i"}},
            {"searchable_text": {"$regex": escaped, "$options": "i"}},
            {"tags": {"$regex": escaped, "$options": "i"}},
        ]
    safe_limit = max(1, min(limit, 200))
    return [
        CorporateDocument(**doc)
        async for doc in documents_coll.find(query, {"_id": 0})
        .sort("updated_at", -1)
        .limit(safe_limit)
    ]


@router.post("/generate", response_model=CorporateDocument)
async def generate_document(
    body: DocumentGenerationRequest, owner: str = Depends(require_owner)
) -> CorporateDocument:
    try:
        template = get_template(body.template_id)
    except KeyError as exc:
        raise HTTPException(400, "Unknown document template") from exc
    profile = await _hydrate_profile(owner, await _profile(owner, body.company_profile_id))
    if body.creation_mode == "prompt" or body.prompt.strip():
        content_html, content_text, metadata = render_classified_document(
            profile, body.title, body.prompt
        )
        template = CorporateTemplate(
            id=metadata["template"],
            name=metadata["document_class"]["label"],
            category="Classified",
            description="Classified corporate document",
            document_type=metadata["document_class"]["key"],
        )
    else:
        content_html, content_text, metadata = render_document_html(
            template,
            profile,
            body.title,
            body.parties,
            body.fields,
            body.jurisdiction,
            body.effective_date,
        )
    title = metadata.get("document_class", {}).get("title") or body.title.strip() or template.name
    category = metadata.get("document_class", {}).get("label") or template.category
    folder_id = await _validate_folder(body.folder_id, owner)
    document = CorporateDocument(
        owner_email=owner,
        title=title,
        document_type=template.document_type,
        category=category,
        folder_id=folder_id,
        tags=[tag.strip() for tag in body.tags if tag.strip()][:20],
        country=body.country.strip().upper() or "GR",
        language=body.language.strip().lower() or "el",
        template_id=template.id,
        company_profile_id=profile.id,
        content_html=content_html,
        content_text=content_text,
        searchable_text=content_text,
        metadata=metadata,
        quality_score=metadata.get("quality_score", {}),
    )
    await documents_coll.insert_one(document.model_dump())
    await _save_version(document, owner, "Generated from corporate template")
    return document


@router.post("", response_model=CorporateDocument)
async def create_document(body: dict, owner: str = Depends(require_owner)) -> CorporateDocument:
    title = str(body.get("title") or "Untitled Document").strip() or "Untitled Document"
    content_html = str(body.get("content_html") or "")
    content_text = str(body.get("content_text") or "") or content_html
    review = legal_review_document(title, content_html, body.get("metadata") or {})
    if body.get("enforce_legal_review") and not review["passed"]:
        raise HTTPException(
            422, {"message": "Legal review rejected save", "issues": review["issues"]}
        )
    folder_id = await _validate_folder(body.get("folder_id"), owner)
    collection_ids = await _validate_collection_ids(body.get("collection_ids", []), owner)
    document = CorporateDocument(
        owner_email=owner,
        title=title,
        document_type=str(body.get("document_type") or "document"),
        category=str(body.get("category") or "General"),
        folder_id=folder_id,
        collection_ids=collection_ids,
        tags=[str(tag).strip() for tag in body.get("tags", []) if str(tag).strip()][:20],
        country=str(body.get("country") or "GR").strip().upper(),
        language=str(body.get("language") or "el").strip().lower(),
        favorite=bool(body.get("favorite", False)),
        status=str(body.get("status") or "draft"),
        template_id=body.get("template_id"),
        company_profile_id=body.get("company_profile_id"),
        content_html=content_html,
        content_text=content_text,
        searchable_text=content_text or content_html,
        metadata={**(body.get("metadata") or {}), "legal_review": review},
        design=body.get("design") or {},
        components=body.get("components") or [],
        tables=body.get("tables") or [],
        charts=body.get("charts") or [],
        quality_score=body.get("quality_score") or {},
        imported_media_id=body.get("imported_media_id"),
    )
    await documents_coll.insert_one(document.model_dump())
    if collection_ids:
        await collections_coll.update_many(
            {"owner_email": owner, "id": {"$in": collection_ids}},
            {
                "$addToSet": {"document_ids": document.id},
                "$set": {"updated_at": now_iso()},
            },
        )
    await _save_version(document, owner, "Created manually")
    return document


@router.get("/{document_id}", response_model=CorporateDocument)
async def get_document(document_id: str, owner: str = Depends(require_owner)) -> CorporateDocument:
    return await _document(document_id, owner)


@router.post("/{document_id}/{action}", response_model=CorporateDocument)
async def document_lifecycle(
    document_id: str, action: str, owner: str = Depends(require_owner)
) -> CorporateDocument:
    document = await _document(document_id, owner)
    status_map = {
        "archive": "archived",
        "trash": "trashed",
        "restore": "draft",
        "approve": "approved",
        "submit-review": "in_review",
    }
    if action not in status_map:
        raise HTTPException(400, "Unsupported document lifecycle action")
    data = document.model_dump()
    data["status"] = status_map[action]
    data["updated_at"] = now_iso()
    metadata = {**(data.get("metadata") or {})}
    metadata.setdefault("activity", [])
    metadata["activity"] = [
        {"at": data["updated_at"], "type": "lifecycle", "action": action, "actor": owner},
        *metadata["activity"],
    ][:100]
    data["metadata"] = metadata
    updated = CorporateDocument(**data)
    await documents_coll.replace_one(
        {"id": document_id, "owner_email": owner}, updated.model_dump()
    )
    return updated


@router.post("/batch")
async def batch_documents(body: dict, owner: str = Depends(require_owner)) -> dict:
    ids = [str(item) for item in body.get("document_ids", []) if str(item).strip()][:200]
    action = str(body.get("action") or "").strip()
    if not ids:
        raise HTTPException(400, "At least one document id is required")
    if action not in {
        "archive",
        "restore",
        "trash",
        "delete",
        "move",
        "tags",
        "metadata",
        "rename-prefix",
    }:
        raise HTTPException(400, "Unsupported batch action")
    docs = [
        CorporateDocument(**doc)
        async for doc in documents_coll.find({"owner_email": owner, "id": {"$in": ids}}, {"_id": 0})
    ]
    if not docs:
        raise HTTPException(404, "No matching documents found")
    now = now_iso()
    updated_ids: list[str] = []
    deleted_ids: list[str] = []
    status_map = {"archive": "archived", "restore": "draft", "trash": "trashed"}
    for document in docs:
        if action == "delete":
            await documents_coll.delete_one({"id": document.id, "owner_email": owner})
            await versions_coll.delete_many({"document_id": document.id, "owner_email": owner})
            deleted_ids.append(document.id)
            continue
        data = document.model_dump()
        if action in status_map:
            data["status"] = status_map[action]
        elif action == "move":
            folder_id = body.get("folder_id") or None
            if folder_id and not await folders_coll.find_one(
                {"id": folder_id, "owner_email": owner}
            ):
                raise HTTPException(404, "Target folder not found")
            data["folder_id"] = folder_id
        elif action == "tags":
            mode = str(body.get("mode") or "replace")
            tags = [str(tag).strip() for tag in body.get("tags", []) if str(tag).strip()][:20]
            if mode == "append":
                data["tags"] = list(dict.fromkeys([*data.get("tags", []), *tags]))[:20]
            else:
                data["tags"] = tags
        elif action == "metadata":
            data["metadata"] = {**(data.get("metadata") or {}), **(body.get("metadata") or {})}
        elif action == "rename-prefix":
            prefix = str(body.get("prefix") or "").strip()
            if prefix:
                data["title"] = f"{prefix} {data['title']}"[:240]
        metadata = {**(data.get("metadata") or {})}
        metadata["activity"] = [
            {"at": now, "type": "batch", "action": action, "actor": owner},
            *(metadata.get("activity") or []),
        ][:100]
        data["metadata"] = metadata
        data["updated_at"] = now
        updated = CorporateDocument(**data)
        await documents_coll.replace_one(
            {"id": document.id, "owner_email": owner}, updated.model_dump()
        )
        await _save_version(updated, owner, f"Batch action: {action}")
        updated_ids.append(document.id)
    return {"ok": True, "action": action, "updated_ids": updated_ids, "deleted_ids": deleted_ids}


@router.patch("/{document_id}", response_model=CorporateDocument)
async def update_document(
    document_id: str, body: dict, owner: str = Depends(require_owner)
) -> CorporateDocument:
    document = await _document(document_id, owner)
    lock = (document.metadata or {}).get("lock") or {}
    if lock.get("locked") and lock.get("owner") != owner and not body.get("force"):
        raise HTTPException(423, "Document is checked out by another reviewer")
    if body.get("expected_version") and int(body["expected_version"]) != document.version_number:
        raise HTTPException(
            409,
            {
                "message": "Document version conflict",
                "current_version": document.version_number,
                "expected_version": body.get("expected_version"),
            },
        )
    data = document.model_dump()
    if "folder_id" in body:
        body = {**body, "folder_id": await _validate_folder(body.get("folder_id"), owner)}
    content_changed = any(field in body for field in ("title", "content_html", "content_text"))
    for field in (
        "title",
        "category",
        "folder_id",
        "tags",
        "country",
        "language",
        "favorite",
        "status",
        "content_html",
        "content_text",
        "metadata",
        "design",
        "components",
        "tables",
        "charts",
        "quality_score",
    ):
        if field in body:
            data[field] = body[field]
    if "country" in body:
        data["country"] = str(body["country"]).strip().upper() or "GR"
    if "language" in body:
        data["language"] = str(body["language"]).strip().lower() or "el"
    if content_changed:
        review = legal_review_document(
            str(data.get("title") or document.title),
            str(data.get("content_html") or data.get("content_text") or ""),
            data.get("metadata") or {},
        )
        if body.get("enforce_legal_review") and not review["passed"]:
            raise HTTPException(
                422, {"message": "Legal review rejected save", "issues": review["issues"]}
            )
        data["metadata"] = {**(data.get("metadata") or {}), "legal_review": review}
        data["version_number"] = int(data.get("version_number", 1)) + 1
        data["searchable_text"] = str(data.get("content_text") or data.get("content_html") or "")
    data["updated_at"] = now_iso()
    if body.get("autosave"):
        data["autosaved_at"] = now_iso()
    updated = CorporateDocument(**data)
    await documents_coll.replace_one(
        {"id": document_id, "owner_email": owner}, updated.model_dump()
    )
    if content_changed:
        await _save_version(updated, owner, str(body.get("change_note") or "Edited document"))
    return updated


@router.post("/{document_id}/lock", response_model=CorporateDocument)
async def document_lock_action(
    document_id: str, body: DocumentLockRequest, owner: str = Depends(require_owner)
) -> CorporateDocument:
    document = await _document(document_id, owner)
    metadata = {**(document.metadata or {})}
    lock = {**(metadata.get("lock") or {})}
    action = body.action.lower().strip()
    if body.expected_version and body.expected_version != document.version_number:
        raise HTTPException(
            409,
            {
                "message": "Document version conflict",
                "current_version": document.version_number,
                "expected_version": body.expected_version,
                "resolution": body.resolution,
            },
        )
    if action in {"check-out", "lock"}:
        if lock.get("locked") and lock.get("owner") != owner:
            raise HTTPException(423, "Document already checked out")
        lock = {
            "locked": True,
            "owner": owner,
            "checked_out_at": now_iso(),
            "version_number": document.version_number,
            "note": body.note,
        }
    elif action in {"check-in", "unlock"}:
        if lock.get("locked") and lock.get("owner") != owner:
            raise HTTPException(423, "Only the lock owner can check in this document")
        lock = {
            **lock,
            "locked": False,
            "checked_in_at": now_iso(),
            "checked_in_by": owner,
            "note": body.note,
        }
    elif action == "conflict-resolution":
        lock = {
            **lock,
            "resolution": body.resolution,
            "resolved_at": now_iso(),
            "resolved_by": owner,
        }
    else:
        raise HTTPException(400, "Unsupported lock action")
    metadata["lock"] = lock
    metadata["activity"] = [
        {"at": now_iso(), "type": "lock", "action": action, "actor": owner},
        *(metadata.get("activity") or []),
    ][:100]
    data = document.model_dump()
    data.update({"metadata": metadata, "updated_at": now_iso()})
    updated = CorporateDocument(**data)
    await documents_coll.replace_one(
        {"id": document_id, "owner_email": owner}, updated.model_dump()
    )
    return updated


@router.post("/import", response_model=CorporateDocument)
async def import_document(
    file: Annotated[UploadFile, File(...)],
    title: Annotated[str, Form()] = "",
    category: Annotated[str, Form()] = "Imported",
    tags: Annotated[str, Form()] = "",
    folder_id: Annotated[str | None, Form()] = None,
    country: Annotated[str, Form()] = "GR",
    language: Annotated[str, Form()] = "el",
    owner: str = Depends(require_owner),
) -> CorporateDocument:
    mime = (file.content_type or "").lower()
    if mime not in ALLOWED_DOCUMENT_MIMES:
        raise HTTPException(400, "Unsupported document type")
    validated_folder_id = await _validate_folder(folder_id, owner)
    data = await file.read()
    if not data or len(data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(400, "Document must be between 1 byte and 50 MB")
    extracted = extract_text_from_upload(data, mime, file.filename or "document")
    filename, _, size = save_bytes(data, mime, kind="reference")
    media = MediaAsset(
        owner_email=owner,
        filename=filename,
        mime_type=mime,
        kind="reference",
        size_bytes=size,
        source_module="documents",
        edit_note="document-import",
    )
    await media_coll.insert_one(media.model_dump())
    doc_title = title.strip() or (file.filename or "Imported document")
    document = CorporateDocument(
        owner_email=owner,
        title=doc_title,
        document_type="scanned" if mime.startswith("image/") else "imported",
        category=category,
        folder_id=validated_folder_id,
        tags=[tag.strip() for tag in tags.split(",") if tag.strip()][:20],
        country=country.strip().upper() or "GR",
        language=language.strip().lower() or "el",
        content_html=_safe_import_html(doc_title, extracted),
        content_text=extracted,
        searchable_text=extracted,
        imported_media_id=media.id,
        metadata={
            "import_mime": mime,
            "original_name": file.filename or "document",
            "ocr_applied": mime.startswith("image/") or mime == "application/pdf",
        },
    )
    await documents_coll.insert_one(document.model_dump())
    await _save_version(document, owner, "Imported document")
    return document


@router.get("/{document_id}/versions", response_model=list[DocumentVersion])
async def list_versions(
    document_id: str, owner: str = Depends(require_owner)
) -> list[DocumentVersion]:
    await _document(document_id, owner)
    return [
        DocumentVersion(**doc)
        async for doc in versions_coll.find(
            {"document_id": document_id, "owner_email": owner}, {"_id": 0}
        ).sort("version_number", -1)
    ]


@router.get("/{document_id}/activity")
async def document_activity(
    document_id: str,
    owner: str = Depends(require_owner),
    action: str = "",
    limit: int = 100,
) -> dict:
    document = await _document(document_id, owner)
    metadata_events = list((document.metadata or {}).get("activity") or [])
    version_events = [
        {
            "at": version.created_at,
            "type": "version",
            "action": version.change_note,
            "actor": owner,
            "version_id": version.id,
            "version_number": version.version_number,
        }
        async for version_doc in versions_coll.find(
            {"document_id": document_id, "owner_email": owner}, {"_id": 0}
        ).sort("created_at", -1)
        for version in [DocumentVersion(**version_doc)]
    ]
    events = [*metadata_events, *version_events]
    if action.strip():
        needle = action.strip().lower()
        events = [event for event in events if needle in str(event.get("action", "")).lower()]
    events.sort(
        key=lambda event: str(event.get("at") or event.get("created_at") or ""), reverse=True
    )
    return {"document_id": document_id, "events": events[: max(1, min(limit, 200))]}


@router.get("/{document_id}/review")
async def get_document_review(document_id: str, owner: str = Depends(require_owner)) -> dict:
    document = await _document(document_id, owner)
    review = (document.metadata or {}).get("review") or {}
    return {
        "document_id": document_id,
        "status": review.get("status", document.status),
        "comments": review.get("comments", []),
        "markers": review.get("markers", []),
        "open_count": review.get("open_count", 0),
        "resolved_count": review.get("resolved_count", 0),
        "change_history": (document.metadata or {}).get("activity", []),
    }


@router.post("/{document_id}/review")
async def create_document_review_item(
    document_id: str, body: DocumentReviewRequest, owner: str = Depends(require_owner)
) -> dict:
    document = await _document(document_id, owner)
    metadata, item = create_review_item(
        document,
        owner,
        body.kind,
        body.body,
        body.anchor,
        body.parent_id,
        body.mentions,
        body.suggestion,
    )
    await documents_coll.update_one(
        {"id": document_id, "owner_email": owner},
        {"$set": {"metadata": metadata, "status": "in_review", "updated_at": now_iso()}},
    )
    return {"ok": True, "item": item, "review": metadata.get("review", {})}


@router.post("/{document_id}/review/{comment_id}")
async def document_review_action(
    document_id: str,
    comment_id: str,
    body: ReviewActionRequest,
    owner: str = Depends(require_owner),
) -> dict:
    document = await _document(document_id, owner)
    try:
        metadata = apply_review_action(document, comment_id, body.action, owner)
    except KeyError as exc:
        raise HTTPException(404, "Review item not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if body.action == "accept-suggestion":
        comment = next(
            (
                item
                for item in metadata.get("review", {}).get("comments", [])
                if item.get("id") == comment_id
            ),
            None,
        )
        if not comment or comment.get("kind") != "suggestion":
            raise HTTPException(400, "Only suggestion review items can be accepted")
        suggestion = comment.get("suggestion") or {}
        anchor = comment.get("anchor") or {}
        before = str(
            suggestion.get("before")
            or suggestion.get("selected_text")
            or anchor.get("selected_text")
            or ""
        )
        after = str(suggestion.get("after") or suggestion.get("replacement") or "")
        if not before or before == after:
            raise HTTPException(409, "Suggestion must replace existing text with new text")
        reviewed_document = CorporateDocument(
            **{**document.model_dump(), "metadata": metadata}
        )
        tracked_metadata, change = create_track_change(
            reviewed_document,
            owner,
            "replacement",
            before,
            after,
            anchor,
            metadata={"review_comment_id": comment_id},
        )
        tracked_document = CorporateDocument(
            **{**reviewed_document.model_dump(), "metadata": tracked_metadata}
        )
        try:
            content_html, content_text, final_metadata = apply_track_change_action(
                tracked_document, "accept", owner, [change["id"]]
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        data = document.model_dump()
        data.update(
            {
                "content_html": content_html,
                "content_text": content_text,
                "searchable_text": content_text,
                "metadata": final_metadata,
                "version_number": document.version_number + 1,
                "updated_at": now_iso(),
            }
        )
        updated = CorporateDocument(**data)
        await documents_coll.replace_one(
            {"id": document_id, "owner_email": owner}, updated.model_dump()
        )
        await _save_version(updated, owner, "Accepted review suggestion")
        return {
            "ok": True,
            "review": final_metadata.get("review", {}),
            "document": updated.model_dump(),
        }
    await documents_coll.update_one(
        {"id": document_id, "owner_email": owner},
        {"$set": {"metadata": metadata, "updated_at": now_iso()}},
    )
    return {"ok": True, "review": metadata.get("review", {})}


@router.get("/{document_id}/track-changes")
async def get_track_changes(
    document_id: str,
    owner: str = Depends(require_owner),
    status: str = "",
    author: str = "",
) -> dict:
    document = await _document(document_id, owner)
    track = (document.metadata or {}).get("track_changes") or {}
    changes = list(track.get("changes", []))
    if status:
        changes = [change for change in changes if change.get("status") == status]
    if author:
        changes = [change for change in changes if change.get("author") == author]
    return {"document_id": document_id, **track, "changes": changes}


@router.post("/{document_id}/track-changes")
async def add_track_change(
    document_id: str, body: TrackChangeRequest, owner: str = Depends(require_owner)
) -> dict:
    document = await _document(document_id, owner)
    metadata, change = create_track_change(
        document,
        owner,
        body.change_type,
        body.before,
        body.after,
        body.range,
        body.formatting,
        body.metadata,
    )
    await documents_coll.update_one(
        {"id": document_id, "owner_email": owner},
        {"$set": {"metadata": metadata, "updated_at": now_iso()}},
    )
    return {"ok": True, "change": change, "track_changes": metadata.get("track_changes", {})}


@router.post("/{document_id}/track-changes/actions", response_model=CorporateDocument)
async def track_change_action(
    document_id: str, body: TrackChangeActionRequest, owner: str = Depends(require_owner)
) -> CorporateDocument:
    document = await _document(document_id, owner)
    try:
        content_html, content_text, metadata = apply_track_change_action(
            document, body.action, owner, body.change_ids
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    data = document.model_dump()
    data.update(
        {
            "content_html": content_html,
            "content_text": content_text,
            "searchable_text": content_text,
            "metadata": metadata,
            "version_number": document.version_number + 1,
            "updated_at": now_iso(),
        }
    )
    updated = CorporateDocument(**data)
    await documents_coll.replace_one(
        {"id": document_id, "owner_email": owner}, updated.model_dump()
    )
    await _save_version(updated, owner, f"Track changes: {body.action}")
    return updated


@router.get("/{document_id}/diff/{version_id}")
async def document_version_diff(
    document_id: str, version_id: str, owner: str = Depends(require_owner)
) -> dict:
    document = await _document(document_id, owner)
    version_doc = await versions_coll.find_one(
        {"id": version_id, "document_id": document_id, "owner_email": owner}, {"_id": 0}
    )
    if not version_doc:
        raise HTTPException(404, "Version not found")
    version = DocumentVersion(**version_doc)
    left = CorporateDocument(
        owner_email=owner,
        title=version.title,
        content_html=version.content_html,
        content_text=version.content_text,
    )
    return compare_documents(left, document)


@router.post("/{document_id}/analysis", response_model=DocumentAnalysisResult)
async def analyze(
    document_id: str, body: DocumentAnalysisRequest, owner: str = Depends(require_owner)
) -> DocumentAnalysisResult:
    document = await _document(document_id, owner)
    comparison = (
        await _document(body.comparison_document_id, owner) if body.comparison_document_id else None
    )

    async def document_executor(runtime_job, progress):
        await progress(
            runtime_job, RuntimeJobStatus.RUNNING, 55, "Document analysis routed through runtime"
        )
        result = analyze_document(
            document, body.action, body.question, comparison, body.required_clauses
        )
        await progress(runtime_job, RuntimeJobStatus.RUNNING, 90, "Document analysis completed")
        return result

    runtime_job = RuntimeJob(
        owner_email=owner,
        studio="documents",
        task_type="llm",
        provider=None,
        payload={"document_id": document_id, "action": body.action, "question": body.question},
    )
    completed = await runtime_manager.submit(runtime_job, document_executor, run_background=False)
    if completed.status == RuntimeJobStatus.FAILED:
        raise HTTPException(502, completed.error or "Document analysis failed")
    result = completed.result
    result_dict = result.model_dump()
    result_dict.setdefault("metadata", {})["runtime_job_id"] = completed.id
    return DocumentAnalysisResult(**result_dict)


@router.post("/{document_id}/legal-review")
async def legal_review(document_id: str, owner: str = Depends(require_owner)) -> dict:
    document = await _document(document_id, owner)
    review = legal_review_document(
        document.title, document.content_html or document.content_text, document.metadata
    )
    await documents_coll.update_one(
        {"id": document_id, "owner_email": owner},
        {"$set": {"metadata.legal_review": review, "updated_at": now_iso()}},
    )
    return review


@router.post("/{document_id}/clauses/{clause_id}", response_model=CorporateDocument)
async def insert_clause(
    document_id: str, clause_id: str, owner: str = Depends(require_owner)
) -> CorporateDocument:
    document = await _document(document_id, owner)
    custom = await clauses_coll.find_one({"id": clause_id, "owner_email": owner}, {"_id": 0})
    clause = (
        ClauseTemplate(**custom)
        if custom
        else next((item for item in CLAUSE_LIBRARY if item.id == clause_id), None)
    )
    if not clause:
        raise HTTPException(404, "Clause not found")
    safe_clause_title = html.escape(clause.title, quote=True)
    safe_clause_body = html.escape(clause.body, quote=True).replace("\n", "<br/>")
    html_clause = (
        "<section class='clause-library-insert'>"
        f"<h2>{safe_clause_title}</h2><p>{safe_clause_body}</p></section>"
    )
    current_html = document.content_html or "<article></article>"
    content_html = (
        current_html.replace("</article>", f"{html_clause}</article>", 1)
        if "</article>" in current_html
        else f"{current_html}{html_clause}"
    )
    content_text = (document.content_text or "") + f"\n\n{clause.title}\n{clause.body}"
    review = legal_review_document(document.title, content_html, document.metadata)
    data = document.model_dump()
    data.update(
        {
            "content_html": content_html,
            "content_text": content_text,
            "searchable_text": content_text,
            "version_number": document.version_number + 1,
            "updated_at": now_iso(),
            "metadata": {
                **document.metadata,
                "legal_review": review,
                "last_clause_inserted": clause.title,
            },
        }
    )
    updated = CorporateDocument(**data)
    await documents_coll.replace_one(
        {"id": document_id, "owner_email": owner}, updated.model_dump()
    )
    await _save_version(updated, owner, f"Inserted clause: {clause.title}")
    return updated


@router.post("/packages", response_model=CorporateDocument)
async def create_package(
    body: PackageBuildRequest, owner: str = Depends(require_owner)
) -> CorporateDocument:
    profile = await _profile(owner)
    content_html, content_text, metadata, package_type = build_package(
        profile, body.package_type, body.title, body.client, body.fields
    )
    document = CorporateDocument(
        owner_email=owner,
        title=body.title,
        document_type=f"{package_type}_package",
        category="Executive Package",
        tags=body.tags[:20],
        company_profile_id=profile.id,
        content_html=content_html,
        content_text=content_text,
        searchable_text=content_text,
        metadata=metadata,
        quality_score=metadata.get("quality_score", {}),
    )
    await documents_coll.insert_one(document.model_dump())
    await _save_version(document, owner, f"Generated {package_type} package")
    return document


@router.patch("/{document_id}/design", response_model=CorporateDocument)
async def design_document(
    document_id: str, body: DocumentDesignRequest, owner: str = Depends(require_owner)
) -> CorporateDocument:
    document = await _document(document_id, owner)
    profile = await _profile(owner, document.company_profile_id)
    content_html, content_text, design = apply_design_system(
        document, profile, body.design, body.components, body.tables, body.charts, body.cover_style
    )
    data = document.model_dump()
    data.update(
        {
            "content_html": content_html,
            "content_text": content_text,
            "searchable_text": content_text,
            "design": design,
            "components": body.components,
            "tables": body.tables,
            "charts": body.charts,
            "version_number": document.version_number + 1,
            "updated_at": now_iso(),
        }
    )
    data["quality_score"] = quality_score(CorporateDocument(**data))
    updated = CorporateDocument(**data)
    await documents_coll.replace_one(
        {"id": document_id, "owner_email": owner}, updated.model_dump()
    )
    await _save_version(updated, owner, "Professional page designer update")
    return updated


@router.post("/{document_id}/redesign", response_model=CorporateDocument)
async def redesign_document(
    document_id: str, owner: str = Depends(require_owner)
) -> CorporateDocument:
    document = await _document(document_id, owner)
    profile = await _profile(owner, document.company_profile_id)
    components = [
        {"type": "company_information"},
        {
            "type": "confidentiality_notices",
            "text": "Confidential executive document. Distribution restricted.",
        },
        {"type": "signature_blocks"},
    ]
    tables = [
        {
            "type": "revision",
            "title": "Revision Table",
            "headers": ["Version", "Date", "Change"],
            "rows": [[str(document.version_number + 1), now_iso()[:10], "AI redesign"]],
        }
    ]
    charts = [
        {
            "type": "timeline",
            "title": "Executive Timeline",
            "data": [
                {"label": "Draft", "value": 30},
                {"label": "Review", "value": 60},
                {"label": "Execution", "value": 100},
            ],
        }
    ]
    content_html, content_text, design = apply_design_system(
        document,
        profile,
        {"columns": 1, "spacing": 1.62, "page_border": "2px solid #B9985A"},
        components,
        tables,
        charts,
        "Luxury",
    )
    data = document.model_dump()
    data.update(
        {
            "content_html": content_html,
            "content_text": content_text,
            "searchable_text": content_text,
            "design": design,
            "components": components,
            "tables": tables,
            "charts": charts,
            "version_number": document.version_number + 1,
            "updated_at": now_iso(),
            "metadata": {**document.metadata, "last_ai_operation": "redesign"},
        }
    )
    data["quality_score"] = quality_score(CorporateDocument(**data))
    updated = CorporateDocument(**data)
    await documents_coll.replace_one(
        {"id": document_id, "owner_email": owner}, updated.model_dump()
    )
    await _save_version(updated, owner, "AI redesign without meaning change")
    return updated


@router.get("/{document_id}/quality")
async def get_quality(document_id: str, owner: str = Depends(require_owner)) -> dict:
    document = await _document(document_id, owner)
    score = quality_score(document)
    await documents_coll.update_one(
        {"id": document_id, "owner_email": owner}, {"$set": {"quality_score": score}}
    )
    return score


@router.get("/{document_id}/compare/{right_document_id}")
async def compare(
    document_id: str, right_document_id: str, owner: str = Depends(require_owner)
) -> dict:
    return compare_documents(
        await _document(document_id, owner), await _document(right_document_id, owner)
    )


@router.get("/{document_id}/preview")
async def preview_document(document_id: str, owner: str = Depends(require_owner)) -> Response:
    document = await _document(document_id, owner)
    return Response(content=document.content_html, media_type="text/html")


@router.post("/{document_id}/operate", response_model=CorporateDocument)
async def operate_document(
    document_id: str, body: DocumentOperationRequest, owner: str = Depends(require_owner)
) -> CorporateDocument:
    document = await _document(document_id, owner)
    sources = [await _document(source_id, owner) for source_id in body.source_document_ids[:10]]

    async def document_executor(runtime_job, progress):
        await progress(
            runtime_job, RuntimeJobStatus.RUNNING, 25, f"Queued {body.operation} operation"
        )
        content_html, content_text, metadata, note = apply_document_operation(
            document, body.operation, body.instruction, body.target_style, body.language, sources
        )
        await progress(runtime_job, RuntimeJobStatus.RUNNING, 85, "AI document operation completed")
        return {
            "content_html": content_html,
            "content_text": content_text,
            "metadata": metadata,
            "note": note,
        }

    runtime_job = RuntimeJob(
        owner_email=owner,
        studio="documents",
        task_type="llm",
        provider=None,
        payload={"document_id": document_id, "operation": body.operation},
    )
    completed = await runtime_manager.submit(runtime_job, document_executor, run_background=False)
    if completed.status == RuntimeJobStatus.FAILED:
        raise HTTPException(502, completed.error or "Document operation failed")
    data = document.model_dump()
    data.update(completed.result)
    data.pop("note", None)
    data["version_number"] = document.version_number + 1
    data["searchable_text"] = data["content_text"]
    data["updated_at"] = now_iso()
    data["metadata"] = {**data.get("metadata", {}), "runtime_job_id": completed.id}
    updated = CorporateDocument(**data)
    await documents_coll.replace_one(
        {"id": document_id, "owner_email": owner}, updated.model_dump()
    )
    await _save_version(updated, owner, completed.result.get("note") or body.operation)
    return updated


@router.post("/{document_id}/versions/{version_id}")
async def version_action(
    document_id: str,
    version_id: str,
    body: VersionActionRequest,
    owner: str = Depends(require_owner),
) -> dict:
    document = await _document(document_id, owner)
    version_doc = await versions_coll.find_one(
        {"id": version_id, "document_id": document_id, "owner_email": owner}, {"_id": 0}
    )
    if not version_doc:
        raise HTTPException(404, "Version not found")
    version = DocumentVersion(**version_doc)
    if body.action == "restore":
        data = document.model_dump()
        data.update(
            {
                "title": version.title,
                "content_html": version.content_html,
                "content_text": version.content_text,
                "searchable_text": version.content_text,
                "version_number": document.version_number + 1,
                "updated_at": now_iso(),
            }
        )
        updated = CorporateDocument(**data)
        await documents_coll.replace_one(
            {"id": document_id, "owner_email": owner}, updated.model_dump()
        )
        new_version = await _save_version(
            updated, owner, f"Restored version {version.version_number}"
        )
        return {"ok": True, "document_id": updated.id, "version_id": new_version.id}
    if body.action == "rename":
        await versions_coll.update_one(
            {"id": version_id, "owner_email": owner},
            {"$set": {"change_note": body.name or version.change_note}},
        )
        return {"ok": True, "version_id": version_id}
    if body.action == "duplicate":
        existing_numbers = [
            int(item.get("version_number") or 0)
            async for item in versions_coll.find(
                {"document_id": document_id, "owner_email": owner},
                {"_id": 0, "version_number": 1},
            )
        ]
        copy = version.model_copy(
            update={
                "id": DocumentVersion(
                    document_id=document_id, owner_email=owner, title=version.title
                ).id,
                "version_number": max(existing_numbers, default=0) + 1,
                "change_note": body.name or f"Copy of {version.change_note}",
                "created_at": now_iso(),
            }
        )
        await versions_coll.insert_one(copy.model_dump())
        return {"ok": True, "version_id": copy.id}
    if body.action == "delete":
        await versions_coll.delete_one({"id": version_id, "owner_email": owner})
        return {"ok": True, "version_id": version_id}
    raise HTTPException(400, "Unsupported version action")


@router.get("/{document_id}/export/{fmt}")
async def export_document(
    document_id: str, fmt: str, owner: str = Depends(require_owner)
) -> Response:
    document = await _document(document_id, owner)
    profile = await _profile(owner, document.company_profile_id)
    fmt = fmt.lower()
    if fmt == "pdf":
        data, mime, ext = render_pdf_bytes(document, profile), "application/pdf", "pdf"
    elif fmt == "docx":
        data, mime, ext = (
            render_docx_bytes(document, profile),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "docx",
        )
    elif fmt == "html":
        data, mime, ext = document.content_html.encode("utf-8"), "text/html", "html"
    elif fmt in {"markdown", "md", "rtf", "txt"}:
        data, mime, ext = render_text_export(document, fmt)
    else:
        raise HTTPException(400, "Export format must be pdf, docx, html, markdown, rtf or txt")
    filename, _, size = save_bytes(data, mime, kind="generated")
    media = MediaAsset(
        owner_email=owner,
        filename=filename,
        mime_type=mime,
        kind="generated",
        size_bytes=size,
        source_module="documents",
        edit_note=f"document-export:{fmt}",
        parent_media_id=document.imported_media_id,
    )
    await media_coll.insert_one(media.model_dump())
    await documents_coll.update_one(
        {"id": document_id, "owner_email": owner},
        {"$addToSet": {"export_media_ids": media.id}, "$set": {"updated_at": now_iso()}},
    )
    headers = {
        "Content-Disposition": _download_content_disposition(document.title, ext),
        "X-Lumina-Media-Id": media.id,
    }
    return Response(content=data, media_type=mime, headers=headers)


def _render_export_bytes(
    document: CorporateDocument, profile: CompanyProfile, fmt: str
) -> tuple[bytes, str, str]:
    fmt = fmt.lower()
    if fmt == "pdf":
        return render_pdf_bytes(document, profile), "application/pdf", "pdf"
    if fmt == "docx":
        return (
            render_docx_bytes(document, profile),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "docx",
        )
    if fmt == "html":
        return document.content_html.encode(), "text/html", "html"
    if fmt in {"markdown", "md", "rtf", "txt"}:
        return render_text_export(document, fmt)
    raise HTTPException(400, "Export format must be pdf, docx, html, markdown, rtf or txt")


@router.post("/export-jobs")
async def create_export_job(body: ExportJobRequest, owner: str = Depends(require_owner)) -> dict:
    ids = [str(item) for item in body.document_ids if str(item).strip()]
    if not ids:
        raise HTTPException(400, "At least one document id is required")
    formats = [
        fmt.lower()
        for fmt in body.formats
        if fmt.lower() in {"pdf", "docx", "html", "markdown", "md", "rtf", "txt"}
    ]
    if not formats:
        raise HTTPException(400, "At least one supported export format is required")
    docs = [
        CorporateDocument(**doc)
        async for doc in documents_coll.find({"owner_email": owner, "id": {"$in": ids}}, {"_id": 0})
    ]
    if not docs:
        raise HTTPException(404, "No matching documents found")
    job_id = f"export-{abs(hash((owner, ids, formats, now_iso()))) % 100000000:08d}"
    buffer = io.BytesIO()
    manifest = []
    profile_cache: dict[str, CompanyProfile] = {}
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, document in enumerate(docs, 1):
            profile_id = document.company_profile_id or "default"
            if profile_id not in profile_cache:
                profile_cache[profile_id] = await _profile(owner, document.company_profile_id)
            for fmt in formats:
                data, mime, ext = _render_export_bytes(document, profile_cache[profile_id], fmt)
                safe_title = "".join(
                    ch if ch.isalnum() or ch in "-_" else "_" for ch in document.title
                )[:80]
                name = f"{index:03d}-{safe_title}.{ext}"
                archive.writestr(name, data)
                manifest.append({"document_id": document.id, "filename": name, "mime_type": mime})
        archive.writestr(
            "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
        )
    data = buffer.getvalue()
    filename, _, size = save_bytes(data, "application/zip", kind="generated")
    media = MediaAsset(
        owner_email=owner,
        filename=filename,
        mime_type="application/zip",
        kind="generated",
        size_bytes=size,
        source_module="documents",
        edit_note=f"document-export-job:{job_id}",
    )
    await media_coll.insert_one(media.model_dump())
    progress = {"percent": 100, "status": "completed", "retry_of": body.retry_of}
    for document in docs:
        metadata = {**(document.metadata or {})}
        metadata["export_jobs"] = [
            {
                "id": job_id,
                "media_id": media.id,
                "formats": formats,
                "progress": progress,
                "created_at": now_iso(),
            },
            *(metadata.get("export_jobs") or []),
        ][:50]
        await documents_coll.update_one(
            {"id": document.id, "owner_email": owner},
            {
                "$set": {"metadata": metadata, "updated_at": now_iso()},
                "$addToSet": {"export_media_ids": media.id},
            },
        )
    return {
        "ok": True,
        "job_id": job_id,
        "status": "completed",
        "progress": progress,
        "media_id": media.id,
        "manifest": manifest,
    }


@router.get("/library/index")
async def document_library_index(owner: str = Depends(require_owner), limit: int = 500) -> dict:
    docs = [
        CorporateDocument(**doc)
        async for doc in documents_coll.find({"owner_email": owner}, {"_id": 0}).sort(
            "updated_at", -1
        )
    ]
    terms: dict[str, int] = {}
    for document in docs[: max(1, min(limit, 2000))]:
        for token in set(
            (document.searchable_text or document.content_text or document.title).lower().split()
        ):
            if len(token) > 2:
                terms[token] = terms.get(token, 0) + 1
    return {
        "document_count": len(docs),
        "indexed_at": now_iso(),
        "top_terms": sorted(terms.items(), key=lambda item: item[1], reverse=True)[:100],
        "virtualization": {
            "recommended_page_size": 50,
            "lazy_preview": True,
            "background_indexing": True,
        },
    }


@router.delete("/{document_id}")
async def delete_document(document_id: str, owner: str = Depends(require_owner)) -> dict:
    result = await documents_coll.delete_one({"id": document_id, "owner_email": owner})
    if not result.deleted_count:
        raise HTTPException(404, "Document not found")
    await versions_coll.delete_many({"document_id": document_id, "owner_email": owner})
    return {"ok": True}
