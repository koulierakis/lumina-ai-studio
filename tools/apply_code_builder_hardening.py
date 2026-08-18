from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "backend" / "code_builder" / "router.py"
TASK_SERVICE = ROOT / "backend" / "code_builder" / "task_service.py"


def replace_once(text: str, old: str, new: str, label: str, path: Path) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"Could not find {label} anchor in {path}")
    return text.replace(old, new, 1)


def harden_router() -> None:
    text = ROUTER.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''class CodeBuilderTaskPhase(str, enum.Enum):\n    QUEUED = "queued"\n    ANALYZING = "analyzing"\n    AWAITING_APPROVAL = "awaiting_approval"\n    APPROVED = "approved"\n    EXECUTING = "executing"\n    ROLLING_BACK = "rolling_back"''',
        '''class CodeBuilderTaskPhase(str, enum.Enum):\n    QUEUED = "queued"\n    ANALYZING = "analyzing"\n    PLANNING = "planning"\n    VALIDATING = "validating"\n    AWAITING_APPROVAL = "awaiting_approval"\n    APPROVED = "approved"\n    APPLYING = "applying"\n    VERIFYING = "verifying"\n    # Backward-compatible aggregate retained for stored/legacy clients.\n    EXECUTING = "executing"\n    ROLLING_BACK = "rolling_back"''',
        "CodeBuilderTaskPhase enum",
        ROUTER,
    )

    text = replace_once(
        text,
        '''        TaskStatus.PLANNING.value: (\n            CodeBuilderTaskPhase.ANALYZING\n        ),\n        TaskStatus.BACKING_UP.value: (\n            CodeBuilderTaskPhase.EXECUTING\n        ),\n        TaskStatus.GENERATING_PATCH.value: (\n            CodeBuilderTaskPhase.EXECUTING\n        ),\n        TaskStatus.VALIDATING_PATCH.value: (\n            CodeBuilderTaskPhase.EXECUTING\n        ),\n        TaskStatus.APPLYING_PATCH.value: (\n            CodeBuilderTaskPhase.EXECUTING\n        ),\n        TaskStatus.BUILDING.value: (\n            CodeBuilderTaskPhase.EXECUTING\n        ),''',
        '''        TaskStatus.PLANNING.value: (\n            CodeBuilderTaskPhase.PLANNING\n        ),\n        TaskStatus.BACKING_UP.value: (\n            CodeBuilderTaskPhase.APPLYING\n        ),\n        TaskStatus.GENERATING_PATCH.value: (\n            CodeBuilderTaskPhase.VALIDATING\n        ),\n        TaskStatus.VALIDATING_PATCH.value: (\n            CodeBuilderTaskPhase.VALIDATING\n        ),\n        TaskStatus.APPLYING_PATCH.value: (\n            CodeBuilderTaskPhase.APPLYING\n        ),\n        TaskStatus.BUILDING.value: (\n            CodeBuilderTaskPhase.VERIFYING\n        ),''',
        "status phase mapping",
        ROUTER,
    )

    text = replace_once(
        text,
        '''        if normalized_stage in {\n            "analysis",\n            "planning",\n        }:\n            new_phase = CodeBuilderTaskPhase.ANALYZING\n        elif normalized_stage in {\n            "backup",\n            "patch_generation",\n            "patch_validation",\n            "patch_application",\n            "build",\n        }:\n            new_phase = CodeBuilderTaskPhase.EXECUTING''',
        '''        if normalized_stage == "analysis":\n            new_phase = CodeBuilderTaskPhase.ANALYZING\n        elif normalized_stage == "planning":\n            new_phase = CodeBuilderTaskPhase.PLANNING\n        elif normalized_stage in {\n            "patch_generation",\n            "patch_validation",\n        }:\n            new_phase = CodeBuilderTaskPhase.VALIDATING\n        elif normalized_stage in {\n            "backup",\n            "patch_application",\n        }:\n            new_phase = CodeBuilderTaskPhase.APPLYING\n        elif normalized_stage == "build":\n            new_phase = CodeBuilderTaskPhase.VERIFYING''',
        "stage phase mapping",
        ROUTER,
    )

    text = replace_once(
        text,
        '''        and new_phase in {\n            CodeBuilderTaskPhase.EXECUTING,\n            CodeBuilderTaskPhase.COMPLETED,\n        }\n    ):\n        new_phase = CodeBuilderTaskPhase.ANALYZING''',
        '''        and new_phase in {\n            CodeBuilderTaskPhase.APPLYING,\n            CodeBuilderTaskPhase.VERIFYING,\n            CodeBuilderTaskPhase.EXECUTING,\n            CodeBuilderTaskPhase.COMPLETED,\n        }\n    ):\n        # Preparation may generate/validate a diff, but public state must never\n        # imply repository mutation before explicit approval.\n        new_phase = CodeBuilderTaskPhase.VALIDATING''',
        "pre-approval write boundary guard",
        ROUTER,
    )

    text = replace_once(
        text,
        '''        stored_task.phase = (\n            CodeBuilderTaskPhase.ANALYZING\n            if preparing\n            else CodeBuilderTaskPhase.EXECUTING\n        )''',
        '''        stored_task.phase = (\n            CodeBuilderTaskPhase.ANALYZING\n            if preparing\n            else CodeBuilderTaskPhase.APPLYING\n        )''',
        "execution start phase",
        ROUTER,
    )

    text = replace_once(
        text,
        '''        if stored_task.phase in {\n            CodeBuilderTaskPhase.EXECUTING,\n            CodeBuilderTaskPhase.COMPLETED,''',
        '''        if stored_task.phase in {\n            CodeBuilderTaskPhase.APPLYING,\n            CodeBuilderTaskPhase.VERIFYING,\n            CodeBuilderTaskPhase.EXECUTING,\n            CodeBuilderTaskPhase.COMPLETED,''',
        "duplicate execution guard",
        ROUTER,
    )

    text = replace_once(
        text,
        '''        CodeBuilderTaskPhase.QUEUED,\n        CodeBuilderTaskPhase.ANALYZING,\n        CodeBuilderTaskPhase.AWAITING_APPROVAL,\n        CodeBuilderTaskPhase.APPROVED,\n        CodeBuilderTaskPhase.EXECUTING,''',
        '''        CodeBuilderTaskPhase.QUEUED,\n        CodeBuilderTaskPhase.ANALYZING,\n        CodeBuilderTaskPhase.PLANNING,\n        CodeBuilderTaskPhase.VALIDATING,\n        CodeBuilderTaskPhase.AWAITING_APPROVAL,\n        CodeBuilderTaskPhase.APPROVED,\n        CodeBuilderTaskPhase.APPLYING,\n        CodeBuilderTaskPhase.VERIFYING,\n        CodeBuilderTaskPhase.EXECUTING,''',
        "cancellation active phases",
        ROUTER,
    )

    text = replace_once(
        text,
        '''            CodeBuilderTaskPhase.ANALYZING,\n            CodeBuilderTaskPhase.EXECUTING,\n            CodeBuilderTaskPhase.ROLLING_BACK,''',
        '''            CodeBuilderTaskPhase.ANALYZING,\n            CodeBuilderTaskPhase.PLANNING,\n            CodeBuilderTaskPhase.VALIDATING,\n            CodeBuilderTaskPhase.APPLYING,\n            CodeBuilderTaskPhase.VERIFYING,\n            CodeBuilderTaskPhase.EXECUTING,\n            CodeBuilderTaskPhase.ROLLING_BACK,''',
        "delete active phases",
        ROUTER,
    )

    approval_anchor = '''        try:\n            stored_task.request = _bind_prepared_patch_to_request(\n                stored_task\n            )\n        except CodeBuilderApprovalError as exc:'''
    approval_guard = '''        serialized_review = _serialize_value(stored_task.review_result)\n        if isinstance(serialized_review, Mapping):\n            verdict = str(serialized_review.get("verdict") or "").strip().casefold()\n            if verdict == "block":\n                raise HTTPException(\n                    status_code=status.HTTP_409_CONFLICT,\n                    detail={\n                        "error": "ai_review_blocked",\n                        "message": "AI review blocked this prepared change. Revise the task before approval.",\n                        "task_id": normalized_task_id,\n                    },\n                )\n\n        try:\n            stored_task.request = _bind_prepared_patch_to_request(\n                stored_task\n            )\n        except CodeBuilderApprovalError as exc:'''
    text = replace_once(text, approval_anchor, approval_guard, "AI review approval guard", ROUTER)

    ROUTER.write_text(text, encoding="utf-8")


def harden_task_service() -> None:
    text = TASK_SERVICE.read_text(encoding="utf-8")
    old = '''        except asyncio.TimeoutError as exc:\n            raise TaskTimeoutError(\n                f"{operation_name} timed out."\n            ) from exc'''
    new = '''        except asyncio.TimeoutError as exc:\n            raise TaskTimeoutError(\n                f"{operation_name} timed out.",\n                timeout_seconds=timeout_seconds,\n            ) from exc'''
    text = replace_once(text, old, new, "async timeout translation", TASK_SERVICE)
    TASK_SERVICE.write_text(text, encoding="utf-8")


def main() -> None:
    harden_router()
    harden_task_service()
    print("CODE BUILDER HARDENING APPLIED")


if __name__ == "__main__":
    main()
