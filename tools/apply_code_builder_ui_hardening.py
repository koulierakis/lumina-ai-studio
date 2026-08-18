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

    if "const reviewAllowsApproval =" not in text:
        old = "  const canApprove = task?.phase === 'awaiting_approval' && Boolean(preparation?.patch) && Boolean(preparation?.patch_validation) && Boolean(review);"
        new = "  const reviewAllowsApproval = review?.status === 'completed' && ['pass', 'warn'].includes(review?.verdict);\n  const reviewBlocked = review?.verdict === 'block';\n  const reviewUnavailable = Boolean(review) && !reviewAllowsApproval && !reviewBlocked;\n  const canApprove = task?.phase === 'awaiting_approval' && Boolean(preparation?.patch) && Boolean(preparation?.patch_validation) && reviewAllowsApproval;"
        text = replace_once(text, old, new, "approval availability")

    current_approve = "  const canApprove = task?.phase === 'awaiting_approval' && Boolean(preparation?.patch) && Boolean(preparation?.patch_validation) && reviewAllowsApproval;"
    if "const canReject =" not in text:
        with_reject = "  const canReject = task?.phase === 'awaiting_approval';\n" + current_approve
        text = replace_once(text, current_approve, with_reject, "rejection availability")

    if "const taskFailureMessage =" not in text:
        anchor = "  const canRollback = ['completed', 'failed', 'cancelled', 'timed_out', 'rollback_failed'].includes(task?.phase);"
        replacement = anchor + "\n  const taskFailureMessage = task?.error_message || task?.result?.error_message || '';\n  const taskFailureType = task?.result?.error_type || '';"
        text = replace_once(text, anchor, replacement, "task failure details")

    if 'data-testid="code-builder-review-blocked"' not in text:
        old_notice = "                <p className=\"mt-2 text-xs leading-relaxed text-white/45\">Approve only the prepared, validated and reviewed patch shown here. Approval starts the protected backup → apply → verification pipeline.</p>"
        new_notice = old_notice + "\n                {reviewBlocked && <div data-testid=\"code-builder-review-blocked\" className=\"mt-3 rounded-md border border-red-400/20 bg-red-400/5 px-3 py-2 text-xs leading-relaxed text-red-100\">The independent review blocked this change. Revise the task before approval.</div>}\n                {reviewUnavailable && <div data-testid=\"code-builder-review-unavailable\" className=\"mt-3 rounded-md border border-amber-300/20 bg-amber-300/5 px-3 py-2 text-xs leading-relaxed text-amber-100\">The independent review did not complete successfully. Approval stays locked until a valid review is available.</div>}"
        text = replace_once(text, old_notice, new_notice, "review gate notices")

    if 'data-testid="code-builder-task-failure"' not in text:
        error_anchor = "        {error && <div className=\"mt-5 flex items-start gap-2 rounded-lg border border-red-400/20 bg-red-400/5 px-4 py-3 text-sm text-red-100\"><CircleAlert className=\"mt-0.5 h-4 w-4 shrink-0\" />{error}</div>}"
        failure_notice = error_anchor + "\n        {task && TERMINAL_PHASES.has(task.phase) && taskFailureMessage && <div data-testid=\"code-builder-task-failure\" className=\"mt-5 rounded-lg border border-red-400/20 bg-red-400/5 px-4 py-3 text-sm text-red-100\"><div className=\"flex items-start gap-2\"><CircleAlert className=\"mt-0.5 h-4 w-4 shrink-0\" /><div><div className=\"font-medium\">Task failed</div>{taskFailureType && <div className=\"mt-1 text-xs text-red-100/60\">{taskFailureType}</div>}<div className=\"mt-1 leading-relaxed\">{taskFailureMessage}</div></div></div></div>}"
        text = replace_once(text, error_anchor, failure_notice, "task failure notice")

    old_reject = '<button data-testid="code-builder-reject" onClick={() => decide(\'reject\')} disabled={!canApprove || busy}'
    new_reject = '<button data-testid="code-builder-reject" onClick={() => decide(\'reject\')} disabled={!canReject || busy}'
    if new_reject not in text:
        text = replace_once(text, old_reject, new_reject, "reject button gate")

    PAGE.write_text(text, encoding="utf-8")
    print("CODE BUILDER UI HARDENING APPLIED")


if __name__ == "__main__":
    main()
