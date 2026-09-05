"""Real end-to-end NATIVE Code Builder acceptance scenarios.

Drives the genuine production pipeline on this machine with a real Ollama
model against disposable probe repositories:

    instruction -> real repository analysis -> real planning (Ollama)
    -> backup -> real AI patch generation (Ollama) -> approved-plan coverage
    -> dry-run -> transactional apply -> build validation -> terminal state
    (+ automatic rollback for the failure scenario)

Scenarios
---------
1. CREATE            : hello_lumina.py with a greet(name) function.
2. MODIFY            : probe_module.py FLAG False -> True (replace_text).
3. MULTI-FILE        : coordinated constant rename across two existing files.
4. CREATE + MODIFY   : one new module plus an edit of an existing module.
5. FAILURE + ROLLBACK: build validation fails after apply; the repository
                       must be restored byte-identically.

Safety model
------------
- Every scenario runs in a disposable temporary repository; the real LUMINA
  repository is never a patch target.
- The real git working tree is snapshotted before and after and must be
  identical.
- Results are written to .lumina-runtime/validation/ (git-ignored) unless
  --output is passed.
- Exit code is 0 only when every scenario passes.

Usage
-----
    python backend/tests/runtime_validate_code_builder_scenarios.py \
        [--model qwen2.5-coder:7b] [--num-ctx 8192] \
        [--planning-timeout 900] [--patch-timeout 900]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from code_builder.backup_service import BackupService
from code_builder.build_service import (
    BuildCommandKind,
    BuildCommandSpec,
    BuildService,
    BuildServiceConfiguration,
)
from code_builder.ollama_adapter import create_ollama_task_adapter
from code_builder.ollama_service import (
    OllamaClientConfiguration,
    OllamaService,
    OllamaTimeoutConfiguration,
)
from code_builder.patch_service import PatchService
from code_builder.planning_service import (
    PlanningConfiguration,
    PlanningService,
)
from code_builder.repository_service import (
    RepositoryConfiguration,
    RepositoryService,
)
from code_builder.task_service import (
    BackupPolicy,
    BuildPolicy,
    RollbackPolicy,
    TaskRequest,
    TaskService,
    TaskStatus,
    create_task_service,
)

EXCLUDED_DIR_NAMES = {"__pycache__", ".pytest_cache", ".lumina"}
EXCLUDED_FILE_NAMES = {"tasks.db", "tasks.db-shm", "tasks.db-wal"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_fingerprint(root: Path) -> dict[str, str]:
    fingerprint: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if set(relative.split("/")) & EXCLUDED_DIR_NAMES:
            continue
        if path.name in EXCLUDED_FILE_NAMES:
            continue
        fingerprint[relative] = sha256_bytes(path.read_bytes())
    return fingerprint


def git_porcelain() -> list[str]:
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(REPOSITORY_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    return sorted(line for line in completed.stdout.splitlines() if line.strip())


def write_text(root: Path, relative: str, content: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _line_contains(path: Path, needle: str) -> bool:
    """True when any logical line of the file contains the needle."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return any(needle in line for line in lines)


def _line_equals(path: Path, needle: str) -> bool:
    """True when any logical line of the file equals the needle exactly."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return any(line.strip() == needle for line in lines)


def compile_spec(arguments: tuple[str, ...], command_id: str) -> BuildCommandSpec:
    return BuildCommandSpec(
        command_id=command_id,
        kind=BuildCommandKind.PYTHON_COMPILE,
        arguments=arguments,
        timeout_seconds=120,
    )


HELLO_LUMINA_EXPECTED = (
    "def greet(name):\n"
    '    return f"Hello, {name}!"\n'
    '\n'
    'if __name__ == "__main__":\n'
    '    print(greet("Lumina"))\n'
)


def scenario_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "scenario1_create",
            "instruction": (
                "Create a new file named hello_lumina.py in the repository "
                "root. The file must contain:\n\n"
                "def greet(name):\n"
                '    return f"Hello, {name}!"\n'
                "\n"
                'if __name__ == "__main__":\n'
                '    print(greet("Lumina"))\n'
                "\n"
                "Do not change any other file."
            ),
            "files": {},
            "expected_terminal": TaskStatus.SUCCEEDED,
            "verify": lambda root: (
                (root / "hello_lumina.py").read_text(encoding="utf-8").strip()
                == HELLO_LUMINA_EXPECTED.strip()
            ),
            "verify_message": "hello_lumina.py does not contain the exact greet() implementation",
            "build_commands": (
                compile_spec(("hello_lumina.py",), "hello-compile"),
            ),
        },
        {
            "name": "scenario2_modify",
            "instruction": (
                "Open the file probe_module.py and change the line "
                "'FLAG = False' to 'FLAG = True'. Do not change anything "
                "else and do not create new files."
            ),
            "files": {
                "probe_module.py": (
                    '"""Probe module."""\n'
                    "FLAG = False\n"
                    "\n"
                    "\n"
                    "def get_flag() -> bool:\n"
                    "    return FLAG\n"
                ),
            },
            "expected_terminal": TaskStatus.SUCCEEDED,
            "verify": lambda root: (
                "FLAG = True" in (root / "probe_module.py").read_text(encoding="utf-8")
            ),
            "verify_message": "probe_module.py still contains FLAG = False",
            "build_commands": (
                compile_spec(("probe_module.py",), "probe-compile"),
            ),
        },
        {
            "name": "scenario3_multi_file",
            "instruction": (
                "Both config_a.py and config_b.py define the same timeout "
                "constant TIMEOUT_SECONDS = 30. Rename that constant to "
                "REQUEST_TIMEOUT_SECONDS in BOTH files consistently, so each "
                "file keeps a working configuration module. Change only "
                "these two files."
            ),
            "files": {
                "config_a.py": "TIMEOUT_SECONDS = 30\n",
                "config_b.py": "TIMEOUT_SECONDS = 30\n",
            },
            "expected_terminal": TaskStatus.SUCCEEDED,
            "verify": lambda root: (
                _line_equals(root / "config_a.py", "REQUEST_TIMEOUT_SECONDS = 30")
                and _line_equals(root / "config_b.py", "REQUEST_TIMEOUT_SECONDS = 30")
                and not _line_equals(root / "config_a.py", "TIMEOUT_SECONDS = 30")
                and not _line_equals(root / "config_b.py", "TIMEOUT_SECONDS = 30")
            ),
            "verify_message": "both config files were not updated consistently",
            "build_commands": (
                compile_spec(("config_a.py", "config_b.py"), "configs-compile"),
            ),
        },
        {
            "name": "scenario4_create_and_modify",
            "instruction": (
                "Create a small module named helpers.py in the repository "
                "root with a function double(value) that returns value * 2. "
                "Then edit the existing math_utils.py so it imports double "
                "from helpers and uses it inside its existing "
                "double_all(numbers) function. Change exactly these two "
                "files: create helpers.py and modify math_utils.py."
            ),
            "files": {
                "math_utils.py": (
                    "def double_all(numbers):\n"
                    "    return [number * 2 for number in numbers]\n"
                ),
            },
            "expected_terminal": TaskStatus.SUCCEEDED,
            "verify": lambda root: (
                (root / "helpers.py").exists()
                and "def double(value)" in (root / "helpers.py").read_text(encoding="utf-8")
                and "from helpers import double" in (root / "math_utils.py").read_text(encoding="utf-8")
            ),
            "verify_message": "helpers.py and/or the math_utils.py import were not produced",
            "build_commands": (
                compile_spec(("helpers.py", "math_utils.py"), "create-modify-compile"),
            ),
        },
        {
            "name": "scenario5_failure_and_rollback",
            "instruction": (
                "In version.py change VERSION from '1.0.0' to '1.1.0'. Do "
                "not create new files."
            ),
            "files": {
                "version.py": "VERSION = '1.0.0'\n",
                "tests/test_fail.py": "def test_always_fails():\n    assert False\n",
            },
            "expected_terminal": TaskStatus.ROLLED_BACK,
            # The model change is applied, then the always-failing pytest
            # command fails build validation, which must trigger automatic
            # rollback to the byte-identical pre-apply tree.
            "build_commands": (
                BuildCommandSpec(
                    command_id="fail-gate",
                    kind=BuildCommandKind.PYTEST,
                    arguments=("test_fail.py",),
                    timeout_seconds=120,
                ),
            ),
            "verify": lambda root: (
                "VERSION = '1.0.0'" in (root / "version.py").read_text(encoding="utf-8")
            ),
            "verify_message": "version.py was not restored after failed build validation",
        },
    ]


def build_scenario_services(
    probe_dir: Path,
    args: argparse.Namespace,
) -> TaskService:
    ollama_service = OllamaService(
        OllamaClientConfiguration(
            timeouts=OllamaTimeoutConfiguration(
                read_seconds=900.0,
                write_seconds=60.0,
            ),
        )
    )
    repository_service = RepositoryService(
        RepositoryConfiguration(repository_root=str(probe_dir))
    )
    planning_service = PlanningService(
        ollama_service=ollama_service,
        configuration=PlanningConfiguration(
            model=args.model,
            fallback_model="",
            context_window=args.num_ctx,
            maximum_output_tokens=2048,
            temperature=0.1,
            top_p=0.9,
            input_token_safety_margin=0,
            timeout_seconds=float(args.planning_timeout),
        ),
    )
    return create_task_service(
        repository_root=probe_dir,
        repository_service=repository_service,
        planning_service=planning_service,
        backup_service=BackupService(repository_root=str(probe_dir)),
        patch_service=PatchService(repository_root=str(probe_dir)),
        build_service=BuildService(
            BuildServiceConfiguration(repository_root=str(probe_dir))
        ),
        ollama_service=create_ollama_task_adapter(
            ollama_service,
            model=args.model,
        ),
        analysis_timeout_seconds=300.0,
        planning_timeout_seconds=float(args.planning_timeout),
        patch_timeout_seconds=float(args.patch_timeout),
        build_timeout_seconds=600.0,
        use_default_build_sequence=False,
    )


def run_scenario(
    scenario: dict[str, Any],
    index: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    started = time.time()
    result: dict[str, Any] = {
        "scenario": scenario["name"],
        "index": index,
        "started_at": utc_now(),
        "failures": [],
        "verdict": "FAIL",
    }
    probe_dir = Path(tempfile.mkdtemp(prefix=f"lumina-cb-{scenario['name']}-"))
    result["probe_repository"] = str(probe_dir)
    service: TaskService | None = None
    try:
        for relative, content in (scenario["files"] or {}).items():
            write_text(probe_dir, relative, content)
        pre_apply_fingerprint = tree_fingerprint(probe_dir)

        service = build_scenario_services(probe_dir, args)
        request = TaskRequest(
            instruction=scenario["instruction"],
            target_paths=(),
            allow_file_creation=True,
            require_clean_repository=False,
            backup_policy=BackupPolicy.REQUIRED,
            build_policy=BuildPolicy.REQUIRED,
            rollback_policy=RollbackPolicy.ON_ANY_FAILURE,
            build_commands=scenario["build_commands"],
            task_timeout_seconds=float(args.task_timeout),
        )

        outcome = service.execute_internal(request)
        result["task_id"] = outcome.task_id
        result["status"] = outcome.status.value if outcome.status else None
        result["generated_content"] = capture_patch_contents(outcome.patch)
        result["error_type"] = outcome.error_type
        result["error_message"] = outcome.error_message
        result["changed_paths"] = list(outcome.changed_paths or ())
        result["plan_model"] = (
            type(outcome.plan).__name__ if outcome.plan is not None else None
        )
        result["plan_file_count"] = _plan_file_count(outcome.plan)
        result["patch_operation_count"] = _patch_operation_count(outcome.patch)
        result["rollback_attempted"] = outcome.rollback_attempted
        result["rollback_succeeded"] = outcome.rollback_succeeded
        result["duration_seconds"] = round(time.time() - started, 3)

        expected = scenario["expected_terminal"]
        if outcome.status is not expected:
            result["failures"].append(
                f"expected terminal status {expected.value}, got "
                f"{outcome.status.value if outcome.status else None}: "
                f"{outcome.error_message}"
            )

        verify = scenario.get("verify")
        if verify is not None:
            try:
                ok = bool(verify(probe_dir))
            except Exception as exc:  # pragma: no cover - defensive
                ok = False
                result["failures"].append(f"verification raised: {exc}")
            result["content_verified"] = ok
            if not ok:
                result["failures"].append(
                    scenario["verify_message"]
                    + "; generated_content="
                    + json.dumps(result.get("generated_content"), default=str)[:1500]
                )

        if outcome.status is TaskStatus.SUCCEEDED:
            post_fingerprint = tree_fingerprint(probe_dir)
            if post_fingerprint == pre_apply_fingerprint:
                result["failures"].append("apply did not change the probe tree")
        if outcome.status is TaskStatus.ROLLED_BACK:
            restored_fingerprint = tree_fingerprint(probe_dir)
            differing_paths = sorted(
                path
                for path in set(restored_fingerprint) | set(pre_apply_fingerprint)
                if restored_fingerprint.get(path) != pre_apply_fingerprint.get(path)
            )
            result["byte_identical_restoration"] = not differing_paths
            if differing_paths:
                result["failures"].append(
                    "post-rollback tree differs from pre-apply tree: "
                    f"{differing_paths[:5]}"
                )
        else:
            result["byte_identical_restoration"] = None

        result["verdict"] = "PASS" if not result["failures"] else "FAIL"
        result["finished_at"] = utc_now()
        return result
    except Exception as exc:  # noqa: BLE001 - aggregate every failure
        result["failures"].append(f"{type(exc).__name__}: {exc}")
        result["verdict"] = "FAIL"
        result["finished_at"] = utc_now()
        return result
    finally:
        if service is not None:
            ollama = getattr(service, "ollama_service", None)
            wrapped = getattr(ollama, "wrapped_service", None)
            closer = getattr(wrapped or ollama, "close", None)
            if callable(closer):
                try:
                    close_result = closer()
                    if inspect.isawaitable(close_result):
                        asyncio.run(close_result)
                except Exception:  # pragma: no cover - defensive
                    pass
        if args.keep:
            result["kept_path"] = str(probe_dir)
        else:
            try:
                shutil.rmtree(probe_dir)
            except Exception as exc:  # pragma: no cover - defensive
                result["failures"].append(f"probe cleanup: {exc}")


def _plan_file_count(plan: Any) -> int:
    if plan is None:
        return 0
    for attribute in ("changes", "files"):
        value = getattr(plan, attribute, None)
        if isinstance(value, (list, tuple)):
            return len(value)
    return 0


def _patch_operation_count(patch: Any) -> int:
    operations = getattr(patch, "operations", None)
    if isinstance(operations, (list, tuple)):
        return len(operations)
    return 0


def capture_patch_contents(patch: Any) -> dict[str, str]:
    """Snapshot what the AI actually proposed (path -> content summary)."""

    captured: dict[str, str] = {}
    operations = getattr(patch, "operations", None)
    if not isinstance(operations, (list, tuple)):
        return captured
    for operation in operations:
        operation_name = getattr(operation, "operation", "")
        path = getattr(operation, "path", "")
        content = getattr(operation, "content", None)
        search_text = getattr(operation, "search_text", None)
        replacement_text = getattr(operation, "replacement_text", None)
        if operation_name == "rename":
            captured[path] = (
                f"rename -> {getattr(operation, 'destination_path', '')}"
            )
        elif operation_name == "delete":
            captured[path] = "delete"
        elif operation_name == "replace_text":
            captured[path] = (
                f"replace_text {str(search_text)[:500]!r} -> "
                f"{str(replacement_text)[:500]!r}"
            )
        elif content is None:
            captured[path] = f"{operation_name} (no text captured)"
        else:
            captured[path] = str(content)[:2000]
    return captured


def run_all(args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    git_before = git_porcelain()
    results: dict[str, Any] = {
        "validator": "runtime_validate_code_builder_scenarios",
        "started_at": utc_now(),
        "configuration": {
            "model": args.model,
            "num_ctx": args.num_ctx,
            "planning_timeout_seconds": args.planning_timeout,
            "patch_timeout_seconds": args.patch_timeout,
            "task_timeout_seconds": args.task_timeout,
            "only": args.only,
            "git_status_before": git_before,
        },
        "scenarios": [],
        "verdict": "FAIL",
    }
    scenarios = scenario_definitions()
    if args.only:
        wanted = {token.strip() for token in args.only.split(",")}
        scenarios = [
            scenario
            for position, scenario in enumerate(scenarios, start=1)
            if scenario["name"] in wanted or str(position) in wanted
        ]
    for index, scenario in enumerate(scenarios, start=1):
        print(
            f"\n===== SCENARIO {index}/{len(scenarios)}: "
            f"{scenario['name']} =====",
            flush=True,
        )
        print(f"instruction: {scenario['instruction']}", flush=True)
        scenario_result = run_scenario(scenario, index, args)
        results["scenarios"].append(scenario_result)
        print(
            json.dumps(scenario_result, indent=2, default=str),
            flush=True,
        )

    git_after = git_porcelain()
    results["git_status_after"] = git_after
    if git_after != git_before:
        difference = sorted(set(git_after) ^ set(git_before))[:10]
        results["failures"] = [
            "real repository git status changed during the run: "
            + ", ".join(difference)
        ]
    else:
        results["failures"] = []
    results["duration_seconds"] = round(time.time() - started, 3)
    results["finished_at"] = utc_now()
    all_passed = (
        not results["failures"]
        and all(
            scenario_result["verdict"] == "PASS"
            for scenario_result in results["scenarios"]
        )
        and len(results["scenarios"]) == len(scenarios)
    )
    results["verdict"] = "PASS" if all_passed else "FAIL"

    if args.output:
        output_path = Path(args.output)
    else:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output_path = (
            REPOSITORY_ROOT
            / ".lumina-runtime"
            / "validation"
            / f"code_builder_scenarios_results_{stamp}.json"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(results, indent=2, default=str),
        encoding="utf-8",
    )
    results["output_file"] = str(output_path)
    print(json.dumps(results, indent=2, default=str), flush=True)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run real Code Builder acceptance scenarios (create, modify, "
            "multi-file, create+modify, failure+rollback) against disposable "
            "probe repositories and a real Ollama model."
        )
    )
    parser.add_argument(
        "--model",
        default="qwen2.5-coder:7b",
        help="Ollama planning/patch model (default: qwen2.5-coder:7b)",
    )
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=8192,
        help="Ollama context window (default: 8192)",
    )
    parser.add_argument(
        "--planning-timeout",
        type=float,
        default=900.0,
        help="Planning stage budget in seconds (default: 900)",
    )
    parser.add_argument(
        "--patch-timeout",
        type=float,
        default=900.0,
        help="Patch generation stage budget in seconds (default: 900)",
    )
    parser.add_argument(
        "--task-timeout",
        type=float,
        default=3600.0,
        help="Overall task budget in seconds (default: 3600)",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="Comma-separated scenario names or positions to run",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Results JSON path (default: .lumina-runtime/validation/)",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep disposable probe repositories for inspection",
    )
    args = parser.parse_args()
    results = run_all(args)
    raise SystemExit(0 if results["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
