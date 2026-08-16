from pathlib import Path

ROOT = Path.cwd()
TARGET = ROOT / "backend" / "code_builder" / "planning_service.py"
TEST = ROOT / "backend" / "tests" / "test_code_builder_small_model_planning.py"

text = TARGET.read_text(encoding="utf-8")

anchor = '''class GeneratedChangePlan(BaseModel):\n    """Canonical structured schema requested from Ollama."""\n'''
if anchor not in text:
    raise SystemExit("GeneratedChangePlan anchor not found; refusing unsafe patch")

# Insert compact model definitions immediately before the canonical model.
compact_models = '''class CompactGeneratedPlanStep(BaseModel):\n    """Small-model-friendly planning step returned by Ollama."""\n\n    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)\n\n    order: int = Field(ge=1, le=MAX_PLAN_STEPS)\n    title: str = Field(min_length=1, max_length=1_000)\n    description: str = Field(min_length=1, max_length=MAX_TEXT_FIELD_CHARACTERS)\n    file_paths: list[str] = Field(default_factory=list, max_length=MAX_FILE_CHANGES)\n\n\nclass CompactGeneratedFileChange(BaseModel):\n    """Small-model-friendly file change returned by Ollama."""\n\n    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)\n\n    path: str = Field(min_length=1, max_length=MAX_PATH_CHARACTERS)\n    operation: str = Field(min_length=1, max_length=50)\n    destination_path: str | None = Field(default=None, max_length=MAX_PATH_CHARACTERS)\n    summary: str = Field(min_length=1, max_length=MAX_TEXT_FIELD_CHARACTERS)\n    rationale: str = Field(min_length=1, max_length=MAX_TEXT_FIELD_CHARACTERS)\n\n\nclass CompactGeneratedChangePlan(BaseModel):\n    """Reduced schema used for reliable planning on small local models."""\n\n    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)\n\n    title: str = Field(min_length=1, max_length=1_000)\n    summary: str = Field(min_length=1, max_length=MAX_TEXT_FIELD_CHARACTERS)\n    objective: str = Field(min_length=1, max_length=MAX_TEXT_FIELD_CHARACTERS)\n    files: list[CompactGeneratedFileChange] = Field(min_length=1, max_length=MAX_FILE_CHANGES)\n    steps: list[CompactGeneratedPlanStep] = Field(min_length=1, max_length=MAX_PLAN_STEPS)\n    acceptance_criteria: list[str] = Field(default_factory=list, max_length=MAX_ACCEPTANCE_CRITERIA)\n    test_plan: list[str] = Field(default_factory=list, max_length=MAX_ACCEPTANCE_CRITERIA)\n\n\ndef _expand_compact_generated_plan(plan: CompactGeneratedChangePlan) -> "GeneratedChangePlan":\n    """Expand a compact model response into the canonical planner schema."""\n\n    files = [\n        GeneratedFileChange(\n            path=item.path,\n            operation=item.operation,\n            destination_path=item.destination_path,\n            summary=item.summary,\n            rationale=item.rationale,\n            implementation_notes=[],\n            affected_symbols=[],\n            dependencies=[],\n            tests=list(plan.test_plan),\n            risk_level="low",\n            breaking_change=False,\n        )\n        for item in plan.files\n    ]\n    steps = [\n        GeneratedPlanStep(\n            order=item.order,\n            title=item.title,\n            description=item.description,\n            file_paths=list(item.file_paths),\n            depends_on=[],\n            validation=list(plan.acceptance_criteria),\n        )\n        for item in plan.steps\n    ]\n    acceptance = list(plan.acceptance_criteria) or [\n        "The requested repository change is present and matches the approved plan."\n    ]\n    tests = list(plan.test_plan) or [\n        "Validate the affected files and run the repository's applicable verification checks."\n    ]\n    return GeneratedChangePlan(\n        title=plan.title,\n        summary=plan.summary,\n        objective=plan.objective,\n        assumptions=[],\n        risk_level="low",\n        breaking_changes=False,\n        requires_user_action=False,\n        required_user_actions=[],\n        files=files,\n        steps=steps,\n        acceptance_criteria=acceptance,\n        test_plan=tests,\n        rollback_plan=["Restore the pre-apply backup if post-apply verification fails."],\n        warnings=[],\n    )\n\n\n'''
if "class CompactGeneratedChangePlan" not in text:
    text = text.replace(anchor, compact_models + anchor, 1)

old_call = '''            result = await self.ollama_service.generate_structured(\n                model=self.configuration.model,\n                prompt=effective_prompt,\n                system_prompt=system_prompt,\n                response_model=GeneratedChangePlan,\n                options=self.build_ollama_options(),\n'''
new_call = '''            # Use a deliberately compact schema for local small models.\n            # The response is expanded into the canonical schema immediately\n            # afterwards and still passes all repository/path validation.\n            result = await self.ollama_service.generate_structured(\n                model=self.configuration.model,\n                prompt=effective_prompt,\n                system_prompt=system_prompt,\n                response_model=CompactGeneratedChangePlan,\n                options=self.build_ollama_options(),\n'''
if old_call in text:
    text = text.replace(old_call, new_call, 1)
elif "response_model=CompactGeneratedChangePlan" not in text:
    raise SystemExit("generate_structured anchor not found; refusing unsafe patch")

old_validation = '''        validated_model = result.validated_model\n\n        if isinstance(validated_model, GeneratedChangePlan):\n            return validated_model\n\n        try:\n            return GeneratedChangePlan.model_validate(\n                result.data\n            )\n        except ValidationError as exc:\n            raise PlanningValidationError(\n                "The generated change plan failed final schema "\n                "validation."\n            ) from exc\n'''
new_validation = '''        validated_model = result.validated_model\n\n        if isinstance(validated_model, CompactGeneratedChangePlan):\n            return _expand_compact_generated_plan(validated_model)\n        if isinstance(validated_model, GeneratedChangePlan):\n            return validated_model\n\n        try:\n            compact_plan = CompactGeneratedChangePlan.model_validate(result.data)\n            return _expand_compact_generated_plan(compact_plan)\n        except ValidationError as exc:\n            raise PlanningValidationError(\n                "The generated change plan failed final compact-schema "\n                "validation."\n            ) from exc\n'''
if old_validation in text:
    text = text.replace(old_validation, new_validation, 1)
elif "_expand_compact_generated_plan(validated_model)" not in text:
    raise SystemExit("final validation anchor not found; refusing unsafe patch")

# The repair prompt must describe the schema actually being requested.
old_contract = '''            f"{_generated_change_plan_contract()}"\n        )\n'''
new_contract = '''            "CompactGeneratedChangePlan required fields:\\n"\n            "- title, summary, objective\\n"\n            "- files: [{path, operation, destination_path?, summary, rationale}]\\n"\n            "- steps: [{order, title, description, file_paths}]\\n"\n            "- acceptance_criteria: [string]\\n"\n            "- test_plan: [string]"\n        )\n'''
# Replace only in _build_repair_instruction, using the last occurrence before create_normalized_change_plan.
repair_start = text.find("    def _build_repair_instruction(")
repair_end = text.find("    async def create_normalized_change_plan(", repair_start)
if repair_start >= 0 and repair_end > repair_start:
    repair_block = text[repair_start:repair_end]
    if old_contract in repair_block:
        repair_block = repair_block.replace(old_contract, new_contract, 1)
        text = text[:repair_start] + repair_block + text[repair_end:]

TARGET.write_text(text, encoding="utf-8")

TEST.write_text('''from backend.code_builder.planning_service import (\n    CompactGeneratedChangePlan,\n    _expand_compact_generated_plan,\n)\n\n\ndef test_compact_plan_expands_to_canonical_schema():\n    compact = CompactGeneratedChangePlan.model_validate({\n        "title": "Create smoke file",\n        "summary": "Create one repository-root smoke file.",\n        "objective": "Verify controlled Code Builder planning.",\n        "files": [{\n            "path": "CODE_BUILDER_SMOKE_TEST.txt",\n            "operation": "create",\n            "summary": "Create smoke file.",\n            "rationale": "Exercise the approval pipeline."\n        }],\n        "steps": [{\n            "order": 1,\n            "title": "Create file",\n            "description": "Create the requested repository-root file.",\n            "file_paths": ["CODE_BUILDER_SMOKE_TEST.txt"]\n        }],\n        "acceptance_criteria": ["File contains the requested text."],\n        "test_plan": ["Verify exact file contents."]\n    })\n    expanded = _expand_compact_generated_plan(compact)\n    assert expanded.files[0].path == "CODE_BUILDER_SMOKE_TEST.txt"\n    assert expanded.files[0].operation == "create"\n    assert expanded.steps[0].file_paths == ["CODE_BUILDER_SMOKE_TEST.txt"]\n    assert expanded.acceptance_criteria\n    assert expanded.test_plan\n    assert expanded.rollback_plan\n''', encoding="utf-8")

print("SMALL_MODEL_PLANNING_PATCH_APPLIED")
