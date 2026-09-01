"""Hardened helpers for Document Studio imports."""
from __future__ import annotations
import html
import importlib
import re
from pathlib import Path

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def resolve_document_mime(content_type: str | None, filename: str | None) -> str:
    mime = str(content_type or "").strip().lower()
    suffix = Path(str(filename or "")).suffix.lower()
    if suffix == ".docx" and mime in {"", "application/octet-stream", "application/zip", DOCX_MIME}:
        return DOCX_MIME
    return mime


def html_to_plain_text(markup: str) -> str:
    value = str(markup or "")
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"</(?:p|h[1-6]|li|tr|section|article|table|blockquote)>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"</(?:td|th)>", "\t", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    lines = [" ".join(line.split()) for line in value.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def strip_pdf_page_markers(value: str) -> str:
    return re.sub(r"^\s*\[\[LUMINA_PAGE:\d+\]\]\s*$", "", value, flags=re.MULTILINE).strip()


def safe_text_html(title: str, text: str) -> str:
    safe_title = html.escape(str(title or "Imported document"), quote=True)
    paragraphs = [f"<p>{html.escape(line, quote=True)}</p>" for line in str(text or "").splitlines() if line.strip()]
    return f"<article><h1>{safe_title}</h1>{''.join(paragraphs) or '<p></p>'}</article>"


def prepare_import_content(data: bytes, mime: str, filename: str, title: str) -> tuple[str, str, str, str, bool]:
    service = importlib.import_module("document_studio.service")
    if mime == DOCX_MIME:
        content_html = service._parse_docx_to_html(data)
        if not content_html:
            raise ValueError("The Word document is damaged or cannot be parsed safely.")
        content_text = html_to_plain_text(content_html)
        if not content_text:
            raise ValueError("The Word document does not contain readable document content.")
        return content_html, content_text, content_text, "docx_structure", False
    extracted = service.extract_text_from_upload(data, mime, filename)
    if mime == "application/pdf":
        content_text = strip_pdf_page_markers(extracted)
        return safe_text_html(title, content_text), content_text, extracted, "pdf_text_layer", False
    if mime.startswith("image/"):
        content_text = str(extracted or "").strip()
        return safe_text_html(title, content_text), content_text, content_text, "ocr", True
    content_text = html_to_plain_text(extracted) if mime == "text/html" else str(extracted or "").strip()
    return safe_text_html(title, content_text), content_text, content_text, "text", False
