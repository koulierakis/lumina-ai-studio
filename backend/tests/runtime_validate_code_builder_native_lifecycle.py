"""Real end-to-end NATIVE Code Builder lifecycle validator.

Executes the genuine production pipeline on this machine:

    instruction
    -> planning (real Ollama model, real PlanningService)
    -> awaiting_approval (preparation: analysis, plan, patch dry-run)
    -> approval (prepared patch bound, no re-planning)
    -> backup (real BackupService snapshot)
    -> patch/apply (real PatchService transactional apply)
    -> build validation (real BuildService python_compile)
    -> completed
    -> manual rollback (API)
    -> byte-identical restoration (sha256 of the probe file and of the
       whole probe tree, excluding build/backup artifact directories)

Safety model
------------
- The pipeline runs against a disposable temporary repository root; the real
  LUMINA repository is never a patch target.
- The real git working tree is snapshotted (``git status --porcelain``) before
  and after the run and must be identical.
- Probe artifacts are removed after the run unless ``--keep`` is passed.
- Results are written outside the tracked tree by default
  (``.lumina-runtime/`` is git-ignored).
- Every stage must be genuinely reached; failures are never converted into
  PASS. The exit code is 0 only for a full PASS verdict.

Usage
-----
    python backend/tests/runtime_validate_code_builder_native_lifecycle.py \
        [--model qwen2.5-coder:7b] [--num-ctx 8192] \
        [--planning-timeout 900] [--output PATH] [--keep]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import uvicorn
from code_builder.backup_service import BackupService
from code_builder.build_service import BuildService, BuildServiceConfiguration
from code_builder.ollama_adapter import create_ollama_task_adapter
from code_builder.ollama_service import (
    OllamaClientConfiguration,
    OllamaService,
    OllamaTimeoutConfiguration,
)
from code_builder.patch_service import PatchService
from code_builder.persistent_task_store import PersistentTaskStore
from code_builder.planning_service import (
    PlanningConfiguration,
    PlanningService,
)
from code_builder.repository_service import (
    RepositoryConfiguration,
    RepositoryService,
)
from code_builder.router import create_code_builder_router
from code_builder.task_service import create_task_service
from fastapi import FastAPI

PROBE_FILE = "probe_module.py"
PROBE_ORIGINAL = (
    b'"""LUMINA Code Builder native lifecycle probe module."""\n'
    b"FLAG = False\n"
    b"\n"
    b"\n"
    b"def get_flag() -> bool:\n"
    b"    return FLAG\n"
)
INSTRUCTION = (
    "Update probe_module.py so that FLAG is set to True instead of False. "
    "Do not change anything else and do not create new files."
)
TERMINAL_PHASES = {
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "rolled_back",
    "rollback_failed",
}
EXPECTED_STAGES = (
    "preflight",
    "services_bootstrap",
    "instruction_to_awaiting_approval",
    "approval_backup_apply_build",
    "rollback_restoration",
    "postflight",
)
REQUIRED_EVENT_STAGES = {"analysis", "planning", "backup", "patch_application", "build"}
EXCLUDED_DIR_NAMES = {"__pycache__", ".lumina"}
EXCLUDED_FILE_NAMES = {"tasks.db", "tasks.db-shm", "tasks.db-wal"}
CONTENT_KEYS = ("content", "new_content", "new_text")
OLLAMA_BASE_URL = "http://127.0.0.1:11434"

class ValidatorStageError(RuntimeError):
    """Raised when a lifecycle stage fails or cannot be reached."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_fingerprint(root: Path) -> dict[str, str]:
    """Map relative POSIX path -> sha256 for every probe file.

    Build caches (``__pycache__``) and backup snapshots (``.lumina``) are
    excluded: they are artifacts of validation/build, not of the patch.
    """
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


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def norm_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").lstrip("./")


def extract_operations(preparation: dict[str, Any]) -> list[dict[str, Any]]:
    patch = preparation.get("patch")
    if isinstance(patch, dict):
        operations = patch.get("operations")
        if isinstance(operations, list):
            return [op for op in operations if isinstance(op, dict)]
        request = patch.get("request")
        if isinstance(request, dict):
            operations = request.get("operations")
            if isinstance(operations, list):
                return [op for op in operations if isinstance(op, dict)]
    return []


def expected_content(operations: list[dict[str, Any]]) -> bytes | None:
    for operation in operations:
        if norm_path(operation.get("path")) != PROBE_FILE:
            continue
        for key in CONTENT_KEYS:
            value = operation.get(key)
            if isinstance(value, str) and value:
                return value.encode("utf-8")
    return None


class Validator:
    """Strict stage recorder: failures are collected and never hidden."""

    def __init__(self) -> None:
        self.stages: dict[str, dict[str, Any]] = {}
        self.failures: list[str] = []
        self.current: str | None = None

    def stage(self, name: str) -> None:
        self.current = name
        self.stages[name] = {
            "status": "reached",
            "started_at": utc_now(),
            "finished_at": None,
            "evidence": {},
            "failures": [],
        }

    def evidence(self, key: str, value: Any) -> None:
        self.stages[self.current]["evidence"][key] = value

    def ok(self) -> None:
        self.stages[self.current]["status"] = "passed"
        self.stages[self.current]["finished_at"] = utc_now()

    def fail(self, message: str) -> None:
        self.failures.append(f"{self.current}: {message}")
        self.stages[self.current]["failures"].append(message)
        self.stages[self.current]["status"] = "failed"
        self.stages[self.current]["finished_at"] = utc_now()
        raise ValidatorStageError(message)

    def mark_unreached(self) -> None:
        for name in EXPECTED_STAGES:
            self.stages.setdefault(
                name,
                {
                    "status": "not_reached",
                    "started_at": None,
                    "finished_at": None,
                    "evidence": {},
                    "failures": [],
                },
            )


def wait_for_port(host: str, port: int, timeout_s: float = 30.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"uvicorn did not open {host}:{port} within {timeout_s:.0f}s")

def get_json(client: httpx.Client, path: str) -> dict[str, Any]:
    response = client.get(path)
    if response.status_code != 200:
        raise RuntimeError(
            f"GET {path} -> {response.status_code}: {response.text[:500]}"
        )
    return response.json()


def wait_phase(
    client: httpx.Client,
    task_id: str,
    wanted: set[str],
    timeout_s: float,
    validator: Validator,
    phase_log: list[dict[str, Any]],
) -> dict[str, Any]:
    """Poll the task until one of ``wanted`` phases is reached."""
    deadline = time.time() + timeout_s
    last_phase: str | None = None
    while True:
        detail = get_json(client, f"/api/code-builder/tasks/{task_id}")
        phase = str(detail.get("phase") or "")
        if phase != last_phase:
            phase_log.append({"at": utc_now(), "phase": phase})
            validator.evidence("phase_timeline", list(phase_log))
            last_phase = phase
        if phase in wanted:
            return detail
        if phase in TERMINAL_PHASES:
            validator.fail(
                f"task reached terminal phase {phase!r} while waiting for "
                f"{sorted(wanted)}; error={detail.get('result', {}).get('error_message')!r}"
            )
        if time.time() >= deadline:
            validator.fail(
                f"phase did not reach {sorted(wanted)} within {timeout_s:.0f}s "
                f"(last={phase!r})"
            )
        time.sleep(2.0)


def run_validation(args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    validator = Validator()
    phase_log: list[dict[str, Any]] = []
    probe_dir: Path | None = None
    server: uvicorn.Server | None = None
    server_thread: threading.Thread | None = None
    client: httpx.Client | None = None
    git_before = git_porcelain()
    results: dict[str, Any] = {
        "validator": "runtime_validate_code_builder_native_lifecycle",
        "started_at": utc_now(),
        "configuration": {
            "model": args.model,
            "num_ctx": args.num_ctx,
            "planning_timeout_seconds": args.planning_timeout,
            "probe_file": PROBE_FILE,
            "lifecycle": [
                "instruction",
                "planning",
                "awaiting_approval",
                "approval",
                "backup",
                "apply",
                "build_validation",
                "completed",
                "rollback",
                "byte_identical_restoration",
            ],
        },
        "git_status_before": git_before,
        "stages": validator.stages,
        "failures": validator.failures,
        "verdict": "FAIL",
    }

    try:
        # ---------------- stage 1: preflight ----------------
        validator.stage("preflight")
        probe_dir = Path(tempfile.mkdtemp(prefix="lumina-cb-native-"))
        validator.evidence("probe_repository", str(probe_dir))
        probe_path = probe_dir / PROBE_FILE
        probe_path.write_bytes(PROBE_ORIGINAL)
        original_sha = sha256_bytes(PROBE_ORIGINAL)
        pre_apply_fingerprint = tree_fingerprint(probe_dir)
        validator.evidence("probe_original_sha256", original_sha)
        with httpx.Client(timeout=10.0) as tags_client:
            tags_response = tags_client.get(f"{OLLAMA_BASE_URL}/api/tags")
            tags_response.raise_for_status()
            model_names = [
                str(model.get("name"))
                for model in tags_response.json().get("models", [])
            ]
        if args.model not in model_names:
            validator.fail(
                f"model {args.model!r} is not present in Ollama "
                f"(installed: {model_names})"
            )
        validator.evidence("ollama_models", model_names)
        validator.ok()

        # ---------------- stage 2: services_bootstrap ----------------
        validator.stage("services_bootstrap")
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
        backup_service = BackupService(repository_root=str(probe_dir))
        patch_service = PatchService(repository_root=str(probe_dir))
        build_service = BuildService(
            BuildServiceConfiguration(repository_root=str(probe_dir))
        )
        task_service = create_task_service(
            repository_root=probe_dir,
            repository_service=repository_service,
            planning_service=planning_service,
            backup_service=backup_service,
            patch_service=patch_service,
            build_service=build_service,
            ollama_service=create_ollama_task_adapter(
                ollama_service,
                model=args.model,
            ),
        )
        task_store = PersistentTaskStore(path=probe_dir / "tasks.db")
        app = FastAPI()
        app.include_router(
            create_code_builder_router(
                task_service=task_service,
                repository_service=repository_service,
                backup_service=task_service.backup_service,
                task_store=task_store,
            )
        )
        port = free_port()
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                log_level="warning",
                lifespan="off",
            )
        )
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()
        wait_for_port("127.0.0.1", port)
        client = httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=60.0
        )
        validator.evidence("api_base", str(client.base_url))
        validator.ok()

        # -------- stage 3: instruction -> planning -> awaiting_approval --------
        validator.stage("instruction_to_awaiting_approval")
        created = client.post(
            "/api/code-builder/tasks",
            json={
                "instruction": INSTRUCTION,
                "target_paths": [PROBE_FILE],
                "require_approval": True,
                "auto_start_after_approval": True,
                "allow_file_creation": True,
                "backup_policy": "required",
                "build_policy": "required",
                "rollback_policy": "on_any_failure",
                "task_timeout_seconds": 3600.0,
                "build_commands": [
                    {
                        "command_id": "probe-compile",
                        "kind": "python_compile",
                        "arguments": [PROBE_FILE],
                        "working_directory": ".",
                    }
                ],
                "metadata": {},
            },
        )
        if created.status_code != 202:
            validator.fail(
                f"task creation returned {created.status_code}: "
                f"{created.text[:500]}"
            )
        task_id = str(created.json()["task"]["task_id"])
        validator.evidence("task_id", task_id)
        detail = wait_phase(
            client,
            task_id,
            {"awaiting_approval"},
            args.preparation_timeout,
            validator,
            phase_log,
        )
        preparation = detail.get("preparation_result") or {}
        plan = preparation.get("plan") or {}
        operations = extract_operations(preparation)
        validator.evidence("plan_title", plan.get("title"))
        validator.evidence("patch_operations", operations)
        if not plan:
            validator.fail("preparation_result carries no plan")
        if not operations:
            validator.fail("preparation_result carries no patch operations")
        unexpected = [
            operation.get("path")
            for operation in operations
            if norm_path(operation.get("path")) != PROBE_FILE
        ]
        if unexpected:
            validator.fail(
                f"patch operations target unexpected paths: {unexpected}"
            )
        review = detail.get("review_result") or {}
        validator.evidence("review_status", review.get("status"))
        validator.evidence("review_verdict", review.get("verdict"))
        validator.ok()

        # ---- stage 4: approval -> backup -> apply -> build -> completed ----
        validator.stage("approval_backup_apply_build")
        approved = client.post(
            f"/api/code-builder/tasks/{task_id}/approve",
            json={
                "decision": "approve",
                "comment": "Native lifecycle validator approval",
                "start_immediately": True,
            },
        )
        if approved.status_code not in (200, 202):
            validator.fail(
                f"approve returned {approved.status_code}: "
                f"{approved.text[:500]}"
            )
        detail = wait_phase(
            client,
            task_id,
            {"completed"},
            args.execution_timeout,
            validator,
            phase_log,
        )
        phase = str(detail.get("phase") or "")
        result = detail.get("result") or {}
        if phase != "completed":
            validator.fail(
                f"execution ended in phase {phase!r} (expected completed); "
                f"result.status={result.get('status')!r} "
                f"rollback_attempted={result.get('rollback_attempted')!r} "
                f"error={result.get('error_message')!r}"
            )
        events = detail.get("events") or []
        stage_sequence = [
            str(event.get("stage"))
            for event in events
            if event.get("stage")
        ]
        observed_stages = list(dict.fromkeys(stage_sequence))
        validator.evidence("event_stages", observed_stages)
        missing_stages = REQUIRED_EVENT_STAGES - set(observed_stages)
        if missing_stages:
            validator.fail(
                f"event timeline does not prove stages "
                f"{sorted(missing_stages)} (observed: {observed_stages})"
            )
        if not result.get("backup"):
            validator.fail("completed result carries no backup evidence")
        validator.evidence("backup", result.get("backup"))
        patch_application = result.get("patch_application")
        if not patch_application:
            validator.fail(
                "completed result carries no patch_application evidence"
            )
        build_result = result.get("build_result") or {}
        build_status = str(build_result.get("status"))
        validator.evidence("build_result_status", build_status)
        if "succeed" not in build_status:
            validator.fail(
                f"build validation did not succeed (status={build_status!r})"
            )
        command_results = build_result.get("commands") or []
        compile_entries = [
            entry
            for entry in command_results
            if str(entry.get("command_id")) == "probe-compile"
        ]
        if not compile_entries:
            validator.fail("build sequence has no probe-compile result")
        compile_status = str(compile_entries[0].get("status"))
        validator.evidence("probe_compile_status", compile_status)
        if "succeed" not in compile_status:
            validator.fail(
                f"probe compile command did not succeed "
                f"(status={compile_status!r})"
            )
        changed = [str(path) for path in (result.get("changed_paths") or [])]
        validator.evidence("changed_paths", changed)
        if not any(norm_path(path) == PROBE_FILE for path in changed):
            validator.fail(
                f"changed_paths do not include {PROBE_FILE}: {changed}"
            )
        applied = probe_path.read_bytes()
        validator.evidence("applied_sha256", sha256_bytes(applied))
        if applied == PROBE_ORIGINAL:
            validator.fail("probe file was not modified by apply")
        wanted_content = expected_content(operations)
        if wanted_content is not None:
            validator.evidence(
                "content_matches_prepared_patch",
                applied == wanted_content,
            )
            if applied != wanted_content:
                validator.fail(
                    "applied probe content does not match the prepared "
                    "patch content"
                )
        if tree_fingerprint(probe_dir) == pre_apply_fingerprint:
            validator.fail("apply did not change the probe tree")
        validator.evidence("apply_changed_tree", True)
        validator.ok()

        # -------- stage 5: rollback -> byte-identical restoration --------
        validator.stage("rollback_restoration")
        rolled = client.post(
            f"/api/code-builder/tasks/{task_id}/rollback",
            json={
                "reason": "Native lifecycle validator rollback",
                "force": False,
            },
        )
        if rolled.status_code != 200:
            validator.fail(
                f"rollback returned {rolled.status_code}: "
                f"{rolled.text[:500]}"
            )
        detail = wait_phase(
            client,
            task_id,
            {"rolled_back"},
            args.rollback_timeout,
            validator,
            phase_log,
        )
        phase = str(detail.get("phase") or "")
        if phase != "rolled_back":
            validator.fail(
                f"rollback ended in phase {phase!r}; "
                f"rollback_succeeded="
                f"{(detail.get('result') or {}).get('rollback_succeeded')!r}"
            )
        restored = probe_path.read_bytes()
        validator.evidence("restored_sha256", sha256_bytes(restored))
        if sha256_bytes(restored) != original_sha:
            validator.fail(
                "rollback did not restore the probe file byte-identically"
            )
        post_rollback = tree_fingerprint(probe_dir)
        if post_rollback != pre_apply_fingerprint:
            difference = sorted(
                set(post_rollback) ^ set(pre_apply_fingerprint)
            )[:10]
            validator.fail(
                f"post-rollback tree differs from the pre-apply tree "
                f"(e.g. {difference})"
            )
        validator.evidence("byte_identical_restoration", True)
        validator.ok()

        # ---------------- stage 6: postflight ----------------
        validator.stage("postflight")
        git_after = git_porcelain()
        results["git_status_after"] = git_after
        if git_after != git_before:
            difference = sorted(set(git_after) ^ set(git_before))[:10]
            validator.fail(
                f"real repository git status changed during the run: "
                f"{difference}"
            )
        validator.evidence("real_repository_untouched", True)
        validator.ok()

    except ValidatorStageError:
        pass

    finally:
        cleanup: dict[str, Any] = {
            "server_stopped": False,
            "probe_removed": False,
            "error": None,
        }
        try:
            if server is not None:
                server.should_exit = True
            if server_thread is not None:
                server_thread.join(timeout=10)
            cleanup["server_stopped"] = True
        except Exception as exc:  # pragma: no cover - defensive
            cleanup["error"] = f"server shutdown: {exc}"
        if client is not None:
            client.close()
        if probe_dir is not None:
            if args.keep:
                cleanup["kept_path"] = str(probe_dir)
            else:
                try:
                    shutil.rmtree(probe_dir)
                    cleanup["probe_removed"] = True
                except Exception as exc:  # pragma: no cover - defensive
                    cleanup["error"] = f"probe cleanup: {exc}"
        validator.mark_unreached()
        all_passed = (not validator.failures) and all(
            validator.stages[name]["status"] == "passed"
            for name in EXPECTED_STAGES
        )
        results["stages"] = validator.stages
        results["failures"] = validator.failures
        results["cleanup"] = cleanup
        results["finished_at"] = utc_now()
        results["duration_seconds"] = round(time.time() - started, 3)
        results["verdict"] = "PASS" if all_passed else "FAIL"
        if args.output:
            output_path = Path(args.output)
        else:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            output_path = (
                REPOSITORY_ROOT
                / ".lumina-runtime"
                / "validation"
                / f"native_lifecycle_results_{stamp}.json"
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(results, indent=2, default=str),
            encoding="utf-8",
        )
        results["output_file"] = str(output_path)
        print(json.dumps(results, indent=2, default=str))
        raise SystemExit(0 if all_passed else 1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run the real native Code Builder lifecycle (instruction -> "
            "planning -> approval -> backup -> apply -> build -> completed "
            "-> rollback -> restoration) against a disposable probe "
            "repository and a real Ollama model."
        )
    )
    parser.add_argument(
        "--model",
        default="qwen2.5-coder:7b",
        help="Ollama planning model (default: qwen2.5-coder:7b)",
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
        "--preparation-timeout",
        type=float,
        default=2400.0,
        help="Wall clock budget for reaching awaiting_approval",
    )
    parser.add_argument(
        "--execution-timeout",
        type=float,
        default=900.0,
        help="Wall clock budget for reaching completed",
    )
    parser.add_argument(
        "--rollback-timeout",
        type=float,
        default=300.0,
        help="Wall clock budget for reaching rolled_back",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Results JSON path (default: .lumina-runtime/validation/, "
            "outside the tracked tree)"
        ),
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the disposable probe repository for inspection",
    )
    run_validation(parser.parse_args())


if __name__ == "__main__":
    main()
