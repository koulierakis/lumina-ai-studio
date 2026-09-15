from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "backend" / "code_builder" / "router.py"


def main() -> None:
    text = ROUTER.read_text(encoding="utf-8")
    old = '''def _phase_allows_approval(\n    phase: CodeBuilderTaskPhase,\n) -> bool:\n    return phase in {\n        CodeBuilderTaskPhase.AWAITING_APPROVAL,\n        CodeBuilderTaskPhase.QUEUED,\n    }\n'''
    new = '''def _phase_allows_approval(\n    phase: CodeBuilderTaskPhase,\n) -> bool:\n    return phase is CodeBuilderTaskPhase.AWAITING_APPROVAL\n'''
    if new in text:
        print("CODE BUILDER APPROVAL PHASE GUARD ALREADY APPLIED")
        return
    if old not in text:
        raise RuntimeError("Could not find Code Builder approval-phase guard")
    ROUTER.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("CODE BUILDER APPROVAL PHASE GUARD APPLIED")


if __name__ == "__main__":
    main()
