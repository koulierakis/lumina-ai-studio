from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "backend" / "code_builder" / "router.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"Could not find {label} anchor in {ROUTER}")
    return text.replace(old, new, 1)


def main() -> None:
    text = ROUTER.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''class CodeBuilderTaskPhase(str, enum.Enum):\n    QUEUED = "queued"\n    ANALYZING = "analyzing"\n    AWAITING_APPROVAL = "awaiting_approval"\n    APPROVED = "approved"\n    EXECUTING = "executing"\n    ROLLING_BACK = "rolling_back"''',
        '''class CodeBuilderTaskPhase(str, enum.Enum):\n    QUEUED = "queued"\n    ANALYZING = "analyzing"\n    PLANNING = "planning"\n    VALIDATING = "validating"\n    AWAITING_APPROVAL = "awaiting_approval"\n    APPROVED = "approved"\n    APPLYING = "applying"\n    VERIFYING = "verifying"\n    # Backward-compatible aggregate retained for stored/legacy clients.\n    EXECUTING = "executing"\n    ROLLING_BACK = "rolling_back"''',
        "CodeBuilderTaskPhase enum",
    )

    text = replace_once(
        text,
        '''        TaskStatus.PLANNING.value: (\n            CodeBuilderTaskPhase.ANALYZING\n        ),\n        TaskStatus.BACKING_UP.value: (\n            CodeBuilderTaskPhase.EXECUTING\n        ),\n        TaskStatus.GENERATING_PATCH.value: (\n            CodeBuilderTaskPhase.EXECUTING\n        ),\n        TaskStatus.VALIDATING_PATCH.value: (\n            CodeBuilderTaskPhase.EXECUTING\n        ),\n        TaskStatus.APPLYING_PATCH.value: (\n            CodeBuilderTaskPhase.EXECUTING\n        ),\n        TaskStatus.BUILDING.value: (\n            CodeBuilderTaskPhase.EXECUTING\n        ),''',
        '''        TaskStatus.PLANNING.value: (\n            CodeBuilderTaskPhase.PLANNING\n        ),\n        TaskStatus.BACKING_UP.value: (\n            CodeBuilderTaskPhase.APPLYING\n        ),\n        TaskStatus.GENERATING_PATCH.value: (\n            CodeBuilderTaskPhase.VALIDATING\n        ),\n        TaskStatus.VALIDATING_PATCH.value: (\n            CodeBuilderTaskPhase.VALIDATING\n        ),\n        TaskStatus.APPLYING_PATCH.value: (\n            CodeBuilderTaskPhase.APPLYING\n        ),\n        TaskStatus.BUILDING.value: (\n            CodeBuilderTaskPhase.VERIFYING\n        ),''',
        "status phase mapping",
    )

    text = replace_once(
        text,
        '''        if normalized_stage in {\n            "analysis",\n            "planning",\n        }:\n            new_phase = CodeBuilderTaskPhase.ANALYZING\n        elif normalized_stage in {\n            "backup",\n            "patch_generation",\n            "patch_validation",\n            "patch_application",\n            "build",\n        }:\n            new_phase = CodeBuilderTaskPhase.EXECUTING''',
        '''        if normalized_stage == "analysis":\n            new_phase = CodeBuilderTaskPhase.ANALYZING\n        elif normalized_stage == "planning":\n            new_phase = CodeBuilderTaskPhase.PLANNING\n        elif normalized_stage in {\n            "patch_generation",\n            "patch_validation",\n        }:\n            new_phase = CodeBuilderTaskPhase.VALIDATING\n        elif normalized_stage in {\n            "backup",\n            "patch_application",\n        }:\n            new_phase = CodeBuilderTaskPhase.APPLYING\n        elif normalized_stage == "build":\n            new_phase = CodeBuilderTaskPhase.VERIFYING''',
        "stage phase mapping",
    )

    text = replace_once(
        text,
        '''        and new_phase in {\n            CodeBuilderTaskPhase.EXECUTING,\n            CodeBuilderTaskPhase.COMPLETED,\n        }\n    ):\n        new_phase = CodeBuilderTaskPhase.ANALYZING''',
        '''        and new_phase in {\n            CodeBuilderTaskPhase.APPLYING,\n            CodeBuilderTaskPhase.VERIFYING,\n            CodeBuilderTaskPhase.EXECUTING,\n            CodeBuilderTaskPhase.COMPLETED,\n        }\n    ):\n        # Preparation may generate/validate a diff, but public phase must never\n        # imply repository mutation before explicit approval.\n        new_phase = CodeBuilderTaskPhase.VALIDATING''',
        "pre-approval write boundary guard",
    )

    text = replace_once(
        text,
        '''        stored_task.phase = (\n            CodeBuilderTaskPhase.ANALYZING\n            if preparing\n            else CodeBuilderTaskPhase.EXECUTING\n        )''',
        '''        stored_task.phase = (\n            CodeBuilderTaskPhase.ANALYZING\n            if preparing\n            else CodeBuilderTaskPhase.APPLYING\n        )''',
        "execution start phase",
    )

    text = replace_once(
        text,
        '''        if stored_task.phase in {\n            CodeBuilderTaskPhase.EXECUTING,\n            CodeBuilderTaskPhase.COMPLETED,''',
        '''        if stored_task.phase in {\n            CodeBuilderTaskPhase.APPLYING,\n            CodeBuilderTaskPhase.VERIFYING,\n            CodeBuilderTaskPhase.EXECUTING,\n            CodeBuilderTaskPhase.COMPLETED,''',
        "duplicate execution guard",
    )

    text = replace_once(
        text,
        '''    return phase in {\n        CodeBuilderTaskPhase.QUEUED,\n        CodeBuilderTaskPhase.ANALYZING,\n        CodeBuilderTaskPhase.AWAITING_APPROVAL,\n        CodeBuilderTaskPhase.APPROVED,\n        CodeBuilderTaskPhase.EXECUTING,\n    }''',
        '''    return phase in {\n        CodeBuilderTaskPhase.QUEUED,\n        CodeBuilderTaskPhase.ANALYZING,\n        CodeBuilderTaskPhase.PLANNING,\n        CodeBuilderTaskPhase.VALIDATING,\n        CodeBuilderTaskPhase.AWAITING_APPROVAL,\n        CodeBuilderTaskPhase.APPROVED,\n        CodeBuilderTaskPhase.APPLYING,\n        CodeBuilderTaskPhase.VERIFYING,\n        CodeBuilderTaskPhase.EXECUTING,\n    }''',
        "cancellation phase guard",
    )

    text = replace_once(
        text,
        '''        if stored_task.phase in {\n            CodeBuilderTaskPhase.ANALYZING,\n            CodeBuilderTaskPhase.EXECUTING,\n            CodeBuilderTaskPhase.ROLLING_BACK,\n        }:''',
        '''        if stored_task.phase in {\n            CodeBuilderTaskPhase.ANALYZING,\n            CodeBuilderTaskPhase.PLANNING,\n            CodeBuilderTaskPhase.VALIDATING,\n            CodeBuilderTaskPhase.APPLYING,\n            CodeBuilderTaskPhase.VERIFYING,\n            CodeBuilderTaskPhase.EXECUTING,\n            CodeBuilderTaskPhase.ROLLING_BACK,\n        }:''',
        "active task deletion guard",
    )

    text = replace_once(
        text,
        '''        try:\n            stored_task.request = _bind_prepared_patch_to_request(\n                stored_task\n            )''',
        '''        review_payload = _serialize_value(stored_task.review_result)\n        if isinstance(review_payload, Mapping) and str(\n            review_payload.get("verdict") or ""\n        ).strip().casefold() == "block":\n            raise HTTPException(\n                status_code=status.HTTP_409_CONFLICT,\n                detail={\n                    "error": "ai_review_blocked",\n                    "message": (\n                        "The independent AI review marked this prepared change "\n                        "as BLOCK. Resolve the review findings and prepare a new "\n                        "patch before approval."\n                    ),\n                    "task_id": normalized_task_id,\n                },\n            )\n\n        try:\n            stored_task.request = _bind_prepared_patch_to_request(\n                stored_task\n            )''',
        "AI review approval gate",
    )

    ROUTER.write_text(text, encoding="utf-8")
    print("CODE BUILDER PHASE CONTRACT APPLIED")


if __name__ == "__main__":
    main()
