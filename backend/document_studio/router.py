from __future__ import annotations

from typing import Annotated

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
    DocumentDesignRequest,
    DocumentFolder,
    DocumentGenerationRequest,
    DocumentOperationRequest,
    DocumentTag,
    DocumentVersion,
    PackageBuildRequest,
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
    build_package,
    classify_document_request,
    compare_documents,
    extract_smart_fields,
    extract_text_from_upload,
    get_template,
    legal_review_document,
    quality_score,
    render_classified_document,
    render_document_html,
    render_docx_bytes,
    render_pdf_bytes,
    render_text_export,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])

documents_coll = versions_coll = profiles_coll = company_versions_coll = folders_coll = (
    tags_coll
) = people_coll = banks_coll = clauses_coll = media_coll = notifications_coll = None

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


def configure_document_studio_router(
    persistence_provider, media_collection, notifications_collection
) -> None:
    global \
        documents_coll, \
        versions_coll, \
        profiles_coll, \
        company_versions_coll, \
        folders_coll, \
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
    document = CorporateDocument(
        owner_email=owner,
        title=title,
        document_type=template.document_type,
        category=category,
        folder_id=body.folder_id,
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
    if not review["passed"]:
        raise HTTPException(
            422, {"message": "Legal review rejected save", "issues": review["issues"]}
        )
    document = CorporateDocument(
        owner_email=owner,
        title=title,
        document_type=str(body.get("document_type") or "document"),
        category=str(body.get("category") or "General"),
        folder_id=body.get("folder_id"),
        tags=[str(tag).strip() for tag in body.get("tags", []) if str(tag).strip()][:20],
        country=str(body.get("country") or "GR").strip().upper(),
        language=str(body.get("language") or "el").strip().lower(),
        content_html=content_html,
        content_text=content_text,
        searchable_text=content_text or content_html,
        metadata={**(body.get("metadata") or {}), "legal_review": review},
    )
    await documents_coll.insert_one(document.model_dump())
    await _save_version(document, owner, "Created manually")
    return document


@router.get("/{document_id}", response_model=CorporateDocument)
async def get_document(document_id: str, owner: str = Depends(require_owner)) -> CorporateDocument:
    return await _document(document_id, owner)


@router.patch("/{document_id}", response_model=CorporateDocument)
async def update_document(
    document_id: str, body: dict, owner: str = Depends(require_owner)
) -> CorporateDocument:
    document = await _document(document_id, owner)
    data = document.model_dump()
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
        if not review["passed"]:
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
        folder_id=folder_id,
        tags=[tag.strip() for tag in tags.split(",") if tag.strip()][:20],
        country=country.strip().upper() or "GR",
        language=language.strip().lower() or "el",
        content_html=f"<article><h1>{doc_title}</h1><p>{extracted}</p></article>",
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
    html_clause = f"<section class='clause-library-insert'><h2>{clause.title}</h2><p>{clause.body}</p></section>"
    content_html = (document.content_html or "") + html_clause
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
        copy = version.model_copy(
            update={
                "id": DocumentVersion(
                    document_id=document_id, owner_email=owner, title=version.title
                ).id,
                "change_note": body.name or f"Copy of {version.change_note}",
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
        "Content-Disposition": f'attachment; filename="{document.title}.{ext}"',
        "X-Lumina-Media-Id": media.id,
    }
    return Response(content=data, media_type=mime, headers=headers)


@router.delete("/{document_id}")
async def delete_document(document_id: str, owner: str = Depends(require_owner)) -> dict:
    result = await documents_coll.delete_one({"id": document_id, "owner_email": owner})
    if not result.deleted_count:
        raise HTTPException(404, "Document not found")
    await versions_coll.delete_many({"document_id": document_id, "owner_email": owner})
    return {"ok": True}
