"""One-command runtime validation for LUMINA Documents AI.

Run from the repository root:
    python backend/tests/runtime_validate_documents_ai.py

This script never marks Documents AI ready unless the focused automated suite
passes and the configured provider status can be checked successfully.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"

FOCUSED_TESTS = [
    "backend/tests/test_document_studio_import_hardening_completion.py",
    "backend/tests/test_document_studio_greek_export_acceptance.py",
    "backend/tests/test_document_studio_greek_persistence_acceptance.py",
    "backend/tests/test_document_studio_ollama_adapter.py",
    "backend/tests/test_document_studio_provider_status.py",
    "backend/tests/test_document_studio_pdf_fonts.py",
    "backend/tests/test_document_studio_safe_smart_fields.py",
    "backend/tests/test_document_studio_source_facts_unicode.py",
    "backend/tests/test_natural_creation_foundation.py",
    "backend/tests/test_pack_advisor_foundation.py",
]


def run_tests() -> dict[str, object]:
    command = [sys.executable, "-m", "pytest", "-q", *FOCUSED_TESTS]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "passed": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-12000:],
        "stderr": completed.stderr[-6000:],
    }


async def provider_status() -> dict[str, object]:
    sys.path.insert(0, str(BACKEND_ROOT))
    from document_studio.provider_status import collect_document_provider_status

    try:
        payload = await collect_document_provider_status()
        return {"checked": True, "payload": payload}
    except Exception as exc:
        return {
            "checked": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def main() -> int:
    tests = run_tests()
    providers = asyncio.run(provider_status())
    payload = providers.get("payload") if providers.get("checked") else {}
    any_ready = bool(payload.get("any_ready")) if isinstance(payload, dict) else False
    ready = bool(tests["passed"] and providers["checked"] and any_ready)

    report = {
        "focused_tests_passed": tests["passed"],
        "provider_status_checked": providers["checked"],
        "any_provider_ready": any_ready,
        "documents_ai_ready": ready,
        "manual_checks_still_required": [
            "Import one real Greek DOCX and visually verify headings/paragraphs.",
            "Import one real Greek PDF with a text layer and verify Greek text.",
            "Export one Greek document to PDF and visually verify Greek glyphs.",
        ],
        "test_output": tests["stdout"],
        "test_errors": tests["stderr"],
        "provider_status": providers,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"\nDOCUMENTS AI AUTOMATED GATE: {'PASS' if ready else 'FAIL'}")
    print("DOCUMENTS AI READY: NO" if ready else "DOCUMENTS AI READY: NO")
    print("Reason: final READY also requires the listed real document visual checks.")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
