"""Hardened Document Studio import route with structure-preserving DOCX handling."""

from __future__ import annotations

import html
import importlib
import re
from pathlib import Path
from typing import Annotated

from auth import require_owner
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from models import MediaAsset
from storage import save_bytes

from .models import CorporateDocument
from .source_facts import extract_source_corporate_facts

router = APIRouter(prefix="/api/documents", tags=["documents"])

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def resolve_document_mime(content_type: str | None, filename: str | None) -> str:
    """Normalize browser upload MIME values without treating DOCX bytes as plain/binary text."""
    mime = str(content_type or "").strip().lower()
    suffix = Path(str(filename or "")).suffix.lower()
    if suffix == ".docx" and mime in {"", "application/octet-stream", "application/zip", DOCX_MIME}:
        return DOCX_MIME
    return mime


def html_to_plain_text(markup: str) -> str:
    """Convert imported document HTML to readable plain text without losing block boundaries."""
    value = str(markup or "")
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(
        r"</(?:p|h[1-6]|li|tr|section|article|table|blockquote)>",
        "\n",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"</(?:td|th)>", "\t", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    lines = [" ".join(line.split()) for line in value.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _strip_pdf_page_markers(value: str) -> str:
    return re.sub(r"^\s*\[\[LUMINA_PAGE:\d+\]\]\s*$", "", value, flags=re.MULTILINE).strip()


def _safe_text_html(title: str, text: str) -> str:
    safe_title = html.escape(str(title or "Imported document"), quote=True)
    paragraphs = [
        f"<p>{html.escape(line, quote=True)}</p>"
        for line in str(text or "").splitlines()
        if line.strip()
    ]
    return f"<article><h1>{safe_title}</h1>{''.join(paragraphs) or '<p></p>'}</article>"


def prepare_import_content(
    data: bytes,
    mime: str,
    filename: str,
    title: str,
) -> tuple[str, str, str, str, bool]:
    """Return HTML, visible text, fact-source text, extraction method, OCR flag."""
    service = importlib.import_module("document_studio.service")

    if mime == DOCX_MIME:
        # Never fall back to decoding DOCX ZIP/XML bytes as latin-1. That legacy path
        # is exactly what can produce scrambled-looking characters in the editor.
        content_html = service._parse_docx_to_html(data)
        if not content_html:
            raise ValueError("The Word document is damaged or cannot be parsed safely.")
        content_text = html_to_plain_text(content_html)
        if not content_text:
            raise ValueError("The Word document does not contain readable document content.")
        return content_html, content_text, content_text, "docx_structure", False

    extracted = service.extract_text_from_upload(data, mime, filename)

    if mime == "application/pdf":
        fact_source = extracted
        content_text = _strip_pdf_page_markers(extracted)
        return _safe_text_html(title, content_text), content_text, fact_source, "pdf_text_layer", False

    if mime.startswith("image/"):
        content_text = str(extracted or "").strip()
        return _safe_text_html(title, content_text), content_text, content_text, "ocr", True

    content_text = html_to_plain_text(extracted) if mime == "text/html" else str(extracted or "").strip()
    return _safe_text_html(title, content_text), content_text, content_text, "text", False


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
        content_html, content_text, fact_source, extraction_method, ocr_applied = prepare_import_content(
            data, mime, original_name, doc_title
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

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
    await document_router.media_coll.insert_one(media.model_dump())

    source_facts = extract_source_corporate_facts(
        fact_source,
        source_document_id=media.id,
        source_document_name=original_name,
        extraction_method=extraction_method,
    )
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
        metadata={
            "import_mime": mime,
            "original_name": original_name,
            "ocr_applied": ocr_applied,
            "extraction_method": extraction_method,
            "source_facts": [fact.model_dump(mode="json") for fact in source_facts],
        },
    )
    await document_router.documents_coll.insert_one(document.model_dump())
    await document_router._save_version(document, owner, "Imported document")
    return document
