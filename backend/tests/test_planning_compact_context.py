from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from code_builder.models import (
    CodebaseAnalysis,
    CodeSymbol,
    FileMetadata,
    FileRole,
    FileType,
    ImportReference,
    RepositoryStatistics,
    SourceLocation,
)
from code_builder.ollama_service import OllamaClientConfiguration, OllamaService
from code_builder.planning_service import (
    PlanningConfiguration,
    PlanningService,
)


def _file(path: str, role: FileRole = FileRole.SOURCE) -> FileMetadata:
    return FileMetadata(
        relative_path=path,
        file_name=Path(path).name,
        extension=Path(path).suffix,
        file_type=FileType.PYTHON if path.endswith(".py") else FileType.JSON,
        role=role,
        size_bytes=2400,
        line_count=80,
        language="Python" if path.endswith(".py") else "JSON",
    )


def _symbol(path: str, name: str, kind: str = "class") -> CodeSymbol:
    return CodeSymbol(
        name=name,
        qualified_name=name,
        symbol_type=kind,
        location=SourceLocation(relative_path=path, start_line=1),
    )


def _analysis(extra_files: int = 0) -> CodebaseAnalysis:
    files = [
        _file("backend/code_builder/router.py"),
        _file("backend/code_builder/task_service.py"),
        _file("backend/code_builder/planning_service.py"),
        _file("backend/code_builder/models.py"),
        _file("backend/tests/test_code_builder.py", FileRole.TEST),
        _file("backend/requirements.txt", FileRole.CONFIGURATION),
    ]
    files.extend(
        _file(f"backend/unrelated/module_{index}.py")
        for index in range(extra_files)
    )
    symbols = [
        _symbol("backend/code_builder/router.py", "create_code_builder_task", "route"),
        _symbol("backend/code_builder/task_service.py", "TaskService"),
        _symbol("backend/code_builder/planning_service.py", "PlanningService"),
        _symbol("backend/code_builder/models.py", "ChangePlan"),
    ]
    imports = [
        ImportReference(
            source_path="backend/code_builder/router.py",
            module="code_builder.task_service",
            resolved_path="backend/code_builder/task_service.py",
        ),
        ImportReference(
            source_path="backend/code_builder/task_service.py",
            module="code_builder.planning_service",
            resolved_path="backend/code_builder/planning_service.py",
        ),
        ImportReference(
            source_path="backend/tests/test_code_builder.py",
            module="code_builder.task_service",
            resolved_path="backend/code_builder/task_service.py",
        ),
    ]
    return CodebaseAnalysis(
        analysis_id=uuid4(),
        repository_root=str(Path.cwd()),
        repository_name="LUMINA",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        statistics=RepositoryStatistics(
            total_files=len(files),
            indexed_files=len(files),
        ),
        files=files,
        symbols=symbols,
        imports=imports,
        backend_detected=True,
        frontend_detected=True,
        backend_framework="FastAPI",
        frontend_framework="React",
        package_managers=["pip", "npm"],
        test_frameworks=["pytest"],
        build_commands=["python -m py_compile"],
        test_commands=["pytest"],
    )


def _service(**overrides: int) -> PlanningService:
    configuration = PlanningConfiguration(**overrides)
    return PlanningService(
        ollama_service=OllamaService(
            configuration=OllamaClientConfiguration()
        ),
        configuration=configuration,
    )


def test_compact_context_selects_exact_paths_symbols_dependencies_and_tests() -> None:
    context = _service().build_context(
        user_request=(
            "Update backend/code_builder/router.py and TaskService so "
            "create_code_builder_task plans ChangePlan validation and requirements.txt configuration."
        ),
        analysis=_analysis(extra_files=220),
    )

    payload = context.to_dict()
    paths = [item["relative_path"] for item in payload["selected_files"]]

    assert "backend/code_builder/router.py" in paths
    assert "backend/code_builder/task_service.py" in paths
    assert "backend/code_builder/planning_service.py" in paths
    assert "backend/tests/test_code_builder.py" in paths
    assert "backend/requirements.txt" in paths
    assert len(paths) == len(set(paths))
    assert payload["context_metadata"]["dependency_expanded_file_count"] > 0
    assert payload["context_metadata"]["omitted_candidate_count"] > 0
    assert any(
        "symbol_match" in item["relevance_reasons"]
        for item in payload["selected_files"]
    )


def test_prompt_budget_keeps_valid_json_and_reserves_output_tokens() -> None:
    service = _service(
        maximum_context_input_tokens=2_000,
        maximum_selected_context_files=12,
    )
    package = service.build_prompt_package(
        user_request="Change PlanningService budget handling.",
        analysis=_analysis(extra_files=120),
    )

    serialized_context = json.dumps(
        package["context"],
        ensure_ascii=False,
        sort_keys=False,
        default=str,
    )
    parsed = json.loads(serialized_context)

    assert parsed["context_metadata"]["context_budget_tokens"] == 2_000
    assert parsed["context_metadata"]["estimated_prompt_tokens"] <= 2_000
    assert len(parsed["selected_files"]) <= 12
    assert "[truncated]" not in serialized_context[-30:]


def test_compact_context_omits_empty_and_verbose_file_fields() -> None:
    context = _service().build_context(
        user_request="Plan router and TaskService change.",
        analysis=_analysis(),
    )
    first_file = context.to_dict()["selected_files"][0]

    assert "sha256" not in first_file
    assert "encoding" not in first_file
    assert "size_bytes" not in first_file
    assert "is_generated" not in first_file
    assert "is_protected" not in first_file
    assert "relevance_reasons" in first_file


def test_logging_summary_does_not_expose_source(caplog) -> None:
    service = _service()
    with caplog.at_level("INFO", logger="code_builder.planning_service"):
        service.build_context(
            user_request="Plan TaskService change.",
            analysis=_analysis(extra_files=5),
        )

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "Planning context built" in messages
    assert "class TaskService" not in messages
    assert "def create_code_builder_task" not in messages
