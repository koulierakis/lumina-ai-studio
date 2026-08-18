from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "frontend" / "src" / "pages" / "CodeBuilder.jsx"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"Could not find {label} anchor in {PAGE}")
    return text.replace(old, new, 1)


def main() -> None:
    text = PAGE.read_text(encoding="utf-8")

    old = "  const canApprove = task?.phase === 'awaiting_approval' && Boolean(preparation?.patch) && Boolean(preparation?.patch_validation) && Boolean(review);"
    new = "  const reviewAllowsApproval = review?.status === 'completed' && ['pass', 'warn'].includes(review?.verdict);\n  const reviewBlocked = review?.verdict === 'block';\n  const reviewUnavailable = Boolean(review) && !reviewAllowsApproval && !reviewBlocked;\n  const canApprove = task?.phase === 'awaiting_approval' && Boolean(preparation?.patch) && Boolean(preparation?.patch_validation) && reviewAllowsApproval;"
    text = replace_once(text, old, new, "approval availability")

    old_notice = "                <p className=\"mt-2 text-xs leading-relaxed text-white/45\">Approve only the prepared, validated and reviewed patch shown here. Approval starts the protected backup → apply → verification pipeline.</p>"
    new_notice = old_notice + "\n                {reviewBlocked && <div data-testid=\"code-builder-review-blocked\" className=\"mt-3 rounded-md border border-red-400/20 bg-red-400/5 px-3 py-2 text-xs leading-relaxed text-red-100\">The independent review blocked this change. Revise the task before approval.</div>}\n                {reviewUnavailable && <div data-testid=\"code-builder-review-unavailable\" className=\"mt-3 rounded-md border border-amber-300/20 bg-amber-300/5 px-3 py-2 text-xs leading-relaxed text-amber-100\">The independent review did not complete successfully. Approval stays locked until a valid review is available.</div>}"
    text = replace_once(text, old_notice, new_notice, "review gate notices")

    PAGE.write_text(text, encoding="utf-8")
    print("CODE BUILDER UI HARDENING APPLIED")


if __name__ == "__main__":
    main()
