# LUMINA Documents AI Hardening Status

Implemented on `work/documents-import-hardening` from the current completion branch:

- Unicode-aware PDF text extraction through `pypdf`, with legacy fallback.
- Cross-platform PDF font aliases for Greek/Unicode export where a suitable system font exists.
- Credential-safe AI provider readiness endpoint that strips key/secret/token fields.
- Fact-safe smart field extraction that uses supplied/profile facts and placeholders instead of invented company data.
- Hardened DOCX import preparation that preserves semantic HTML structure instead of decoding ZIP/XML bytes as text.
- DOCX MIME normalization for browsers that upload `.docx` as octet-stream or zip.
- Hardened PDF import handling that preserves page markers for source-fact provenance while removing them from visible document text.
- Existing `/api/documents/import` POST route is replaced at package bootstrap only; all other Document Studio routes remain unchanged.
- Focused tests added for MIME normalization, HTML-to-text conversion, Unicode DOCX structure preservation, PDF marker handling and damaged DOCX rejection.

## Safety

The hardening is additive and keeps the existing persistence/versioning lifecycle. The old import route is removed only from the in-memory router at startup and the hardened route is inserted in its place.

## Validation gate

The GitHub connector cannot execute the repository test suite. Do not mark Documents AI READY from these commits alone. Required runtime proof:

1. Import a real Greek DOCX and verify readable Greek, headings and paragraphs.
2. Import a real Greek PDF with a text layer and verify Unicode extraction.
3. Export the imported/generated Greek document to PDF and confirm Greek glyphs render correctly.
4. Verify `/api/documents/ai/providers/status` returns no credentials and reports actual readiness.
5. Run the focused backend tests plus the existing Document Studio test suite.

Current status: IMPLEMENTED, RUNTIME VALIDATION PENDING.
