"""Robust Unicode PDF extraction for Document Studio imports."""

from __future__ import annotations

import io
import re


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def extract_pdf_text(data: bytes, *, max_chars: int = 50_000) -> str:
    """Extract text from a PDF while preserving Unicode where the PDF exposes a text layer.

    pypdf follows embedded ToUnicode maps used by normal exported PDFs. A narrow raw-PDF
    fallback remains for old/simple PDFs that do not parse cleanly.
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data), strict=False)
        page_text: list[str] = []
        for page_number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            if text.strip():
                page_text.append(f"[[LUMINA_PAGE:{page_number}]]\n{text}")
            if sum(len(item) for item in page_text) >= max_chars:
                break
        extracted = "\n".join(page_text).strip()
        if extracted:
            return extracted[:max_chars]
    except Exception:
        pass

    # Compatibility fallback for legacy/simple literal-string PDFs.
    raw = data.decode("latin-1", errors="ignore")
    chunks = re.findall(r"\(([^()]{2,})\)\s*Tj", raw)
    candidate = " ".join(chunks)
    return _normalize_text(candidate)[:max_chars]
