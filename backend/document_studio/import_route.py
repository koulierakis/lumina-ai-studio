"""Hardened Document Studio import endpoint."""
from __future__ import annotations
import importlib
from typing import Annotated
from auth import require_owner
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from models import MediaAsset
from storage import save_bytes
from .import_hardening import prepare_import_content, resolve_document_mime
from .models import CorporateDocument
from .source_facts import extract_source_corporate_facts

router = APIRouter(prefix="/api/documents", tags=["documents"])

@router.post("/import", response_model=CorporateDocument)
async def import_document_hardened(
    file: Annotated[UploadFile, File(...)],
    title: Annotated[str, Form()] = "",
    category: Annotated[str, Form()] = "Imported",
    tags: Annotated[str, Form()] = "",
    folder_id: Annotated[str | None, Form()] = None,
    country: Annotated[str, Form()] = "GR",
    language: Annotated[str, Form()] = "el",
    owner: str = Depends(require_owner),
) -> CorporateDocument:
    document_router = importlib.import_module("document_studio.router")
    original_name = file.filename or "document"
    mime = resolve_document_mime(file.content_type, original_name)
    if mime not in document_router.ALLOWED_DOCUMENT_MIMES:
        raise HTTPException(400, "Unsupported document type")
    validated_folder_id = await document_router._validate_folder(folder_id, owner)
    data = await file.read()
    if not data or len(data) > document_router.MAX_DOCUMENT_BYTES:
        raise HTTPException(400, "Document must be between 1 byte and 50 MB")
    doc_title = title.strip() or original_name
    try:
        content_html, content_text, fact_source, extraction_method, ocr_applied = prepare_import_content(data, mime, original_name, doc_title)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    filename, _, size = save_bytes(data, mime, kind="reference")
    media = MediaAsset(owner_email=owner, filename=filename, mime_type=mime, kind="reference", size_bytes=size, source_module="documents", edit_note="document-import")
    await document_router.media_coll.insert_one(media.model_dump())
    source_facts = extract_source_corporate_facts(fact_source, source_document_id=media.id, source_document_name=original_name, extraction_method=extraction_method)
    document = CorporateDocument(
        owner_email=owner,
        title=doc_title,
        document_type="scanned" if mime.startswith("image/") else "imported",
        category=category,
        folder_id=validated_folder_id,
        tags=[tag.strip() for tag in tags.split(",") if tag.strip()][:20],
        country=country.strip().upper() or "GR",
        language=language.strip().lower() or "el",
        content_html=content_html,
        content_text=content_text,
        searchable_text=content_text,
        imported_media_id=media.id,
        metadata={"import_mime": mime, "original_name": original_name, "ocr_applied": ocr_applied, "extraction_method": extraction_method, "source_facts": [fact.model_dump(mode="json") for fact in source_facts]},
    )
    await document_router.documents_coll.insert_one(document.model_dump())
    await document_router._save_version(document, owner, "Imported document")
    return document
