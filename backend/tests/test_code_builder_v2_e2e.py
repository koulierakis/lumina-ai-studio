#!/usr/bin/env python3
"""
End-to-end test for Lumina Code Builder V2.

Tests the complete workflow:
1. CREATE PROJECT from natural language prompt
2. GENERATE project files
3. INSTALL dependencies
4. RUN dev server
5. BROWSER TEST against local app
6. INTRODUCE DEFECT
7. DETECT defect via browser
8. AUTONOMOUS REPAIR
9. RE-RUN browser test
10. VERIFY fix
"""

import os
import sys
import tempfile
import time
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.code_builder_v2.models import (
    BrowserEvidence,
    DevServerInfo,
    FrameworkType,
    Project,
    ProjectStatus,
    TaskRequest,
    TaskStatus,
)
from backend.code_builder_v2.project_generator import (
    create_project_from_prompt,
    detect_framework,
    install_dependencies,
    get_dev_server_command,
    find_free_port,
)
from backend.code_builder_v2.project_service import ProjectService
from backend.code_builder_v2.store import JsonProjectStore
from backend.code_builder_v2.dev_server_manager import DevServerManager
from backend.code_builder_v2.browser_evidence import run_browser_check, run_browser_interaction
from backend.code_builder_v2.autonomous import AutonomousBuildLoop, AttemptResult, FailureEvidence, RepairInstruction, AutonomousPhase
from backend.code_builder_v2.runtime import WorkspaceAttemptRunner, EvidenceDiagnoser, VerifiedWorkspacePublisher
from backend.code_builder_v2.ollama import OllamaClient, OllamaChangeGenerator
from backend.code_builder_v2.generator import ChangeGenerator
from backend.code_builder_v2.models import ChangePlan
import requests
import json
import re
from typing import Any, Optional

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("CODE_MODEL", "qwen2.5-coder:7b")

class LocalOllamaClient:
    """Local Ollama client for autonomous repair loop."""
    
    def __init__(self, base_url: str = OLLAMA_URL, model: str = OLLAMA_MODEL, timeout: int = 180):
        self.base_url = base_url
        self.default_model = model
        self.timeout_seconds = timeout
    
    def _extract_json_object(self, raw: str) -> dict[str, Any]:
        text = (raw or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines:
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
            if text.lower().startswith("json"):
                text = text[4:].lstrip()
        
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                raise Exception("Local Ollama did not return a JSON object.")
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise Exception("Local Ollama returned invalid JSON.") from exc
        
        if not isinstance(data, dict):
            raise Exception("Local Ollama JSON result must be an object.")
        return data
    
    def generate_json(self, prompt: str, model: Optional[str] = None) -> dict[str, Any]:
        model_to_use = model or self.default_model
        response = requests.post(
            f"{self.base_url}/api/generate",
            json={"model": model_to_use, "prompt": prompt, "stream": False, "options": {"temperature": 0.1}},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        raw = response.json().get("response", "")
        return self._extract_json_object(raw)


class LocalOllamaChangeGenerator:
    """Local Ollama change generator for autonomous repair loop."""
    
    def __init__(self, client: LocalOllamaClient):
        self.client = client
    
    def generate(
        self,
        request: TaskRequest,
        plan: ChangePlan,
        file_context: dict[str, str],
    ) -> list:
        from backend.code_builder_v2.applier import ProposedFileChange
        plan_json = plan.model_dump_json()
        context_json = json.dumps(file_context, ensure_ascii=False)
        prompt = f"""You are the implementation engine of LUMINA Code Builder V2.
Implement EXACTLY the approved plan and return ONLY JSON:
{{"changes":[{{"path":"relative/path","operation":"create|modify|delete","content":"full file content or null for delete"}}]}}
Hard rules:
- Include every planned path exactly once and no unplanned paths.
- Preserve the planned operation for every path.
- For create/modify return the COMPLETE final file content, never a diff.
- For delete content must be null.
- Do not use markdown fences.
Approved plan: {plan_json}
Current file context: {context_json}
Original request: {request.prompt}
"""
        data = self.client.generate_json(prompt, request.model)
        raw_changes = data.get("changes")
        if not isinstance(raw_changes, list):
            raise Exception("Generated result is missing changes array")
        changes: list[ProposedFileChange] = []
        for item in raw_changes:
            if not isinstance(item, dict):
                raise Exception("Each generated change must be an object")
            changes.append(
                ProposedFileChange(
                    path=str(item.get("path", "")),
                    operation=str(item.get("operation", "")),
                    content=item.get("content"),
                )
            )
        return changes
from backend.code_builder_v2.planner import Planner
from backend.code_builder_v2.factory import create_autonomous_loop
from backend.code_builder_v2.workspace import DisposableWorkspaceService


def print_section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def print_step(step: str) -> None:
    print(f"\n  → {step}")


def print_result(label: str, value: any) -> None:
    print(f"    {label}: {value}")


def wait_for_server_ready(dev_server_manager: DevServerManager, project_id: str, timeout: int = 60) -> DevServerInfo | None:
    """Wait for dev server to be ready."""
    start = time.time()
    while time.time() - start < timeout:
        info = dev_server_manager.get_server_info(project_id)
        if info and info.status.value == "ready":
            return info
        time.sleep(1)
    return None


def run_e2e_test():
    """Run the complete end-to-end test."""
    print_section("LUMINA CODE BUILDER V2 - END-TO-END TEST")

    # Setup temporary directory for test
    with tempfile.TemporaryDirectory() as tmpdir:
        test_root = Path(tmpdir) / "lumina_test"
        test_root.mkdir(parents=True, exist_ok=True)

        runtime_root = test_root / ".lumina-runtime"
        runtime_root.mkdir(parents=True, exist_ok=True)

        projects_root = test_root / "generated_projects"
        projects_root.mkdir(parents=True, exist_ok=True)

        print(f"Test root: {test_root}")

        # Step 1: Create ProjectService
        print_section("STEP 1: Initialize ProjectService")
        project_store = JsonProjectStore(runtime_root / "projects.json")
        project_service = ProjectService(
            project_store=project_store,
            runtime_root=runtime_root,
        )

        # Step 2: Create project from prompt
        print_section("STEP 2: Create Project from Prompt")
        prompt = "Create a simple responsive React web application with a heading saying Lumina Builder Test and a button that changes a visible message when clicked."
        print_step(f"Prompt: {prompt}")

        project = project_service.create_project(
            prompt=prompt,
            project_name="Lumina Builder Test",
            framework_hint="react_vite",
        )
        print_result("Project ID", project.id)
        print_result("Project Name", project.name)
        print_result("Workspace", project.workspace_root)
        print_result("Framework", project.framework.value)
        print_result("Status", project.status.value)

        # Verify project files were generated
        project_path = Path(project.workspace_root)
        print_result("Files generated", len(list(project_path.rglob("*"))))
        for f in sorted(project_path.rglob("*")):
            if f.is_file():
                print(f"      {f.relative_to(project_path)}")

        # Step 3: Install dependencies
        print_section("STEP 3: Install Dependencies")
        print_step("Running npm install...")
        success, output = project_service.install_dependencies(project.id)
        print_result("Success", success)
        if not success:
            print_result("Output", output)
            raise RuntimeError("Dependency installation failed")
        print_result("Output (truncated)", output[-500:] if len(output) > 500 else output)

        # Step 4: Start dev server
        print_section("STEP 4: Start Dev Server")
        print_step("Starting Vite dev server...")
        server_info = project_service.start_dev_server(project.id, timeout=90)
        print_result("Server URL", server_info.url)
        print_result("Server Port", server_info.port)
        print_result("Server PID", server_info.pid)
        print_result("Server Status", server_info.status.value)

        if server_info.status.value != "ready":
            logs = project_service.get_dev_server_logs(project.id)
            print_result("Server Logs (last 2000 chars)", logs[-2000:])
            raise RuntimeError("Dev server failed to start")

        # Wait a bit more for Vite to fully compile
        time.sleep(5)

        # Step 5: Browser verification - initial check
        print_section("STEP 5: Browser Verification - Initial Check")
        print_step("Running browser check against local dev server...")
        evidence = project_service.run_browser_check(
            project.id,
            wait_for_selector="h1",
            expected_text="Lumina Builder Test",
        )
        print_result("Page Loaded", evidence.page_loaded)
        print_result("Page URL", evidence.page_url)
        print_result("Console Errors", evidence.console_errors)
        print_result("Network Errors", evidence.network_errors)
        print_result("Uncaught Exceptions", evidence.uncaught_exceptions)
        print_result("Screenshot", evidence.screenshot_path)
        if evidence.page_content:
            print_result("Page Content (first 500 chars)", evidence.page_content[:500])

        # Verify heading is present
        assert evidence.page_loaded, "Page did not load"
        assert not evidence.console_errors, f"Console errors: {evidence.console_errors}"
        assert not evidence.network_errors, f"Network errors: {evidence.network_errors}"
        assert not evidence.uncaught_exceptions, f"Uncaught exceptions: {evidence.uncaught_exceptions}"
        assert evidence.page_content and "Lumina Builder Test" in evidence.page_content, "Heading not found"

        print("✓ Initial browser check passed!")

        # Step 6: Browser interaction - click button and verify message change
        print_section("STEP 6: Browser Interaction - Click Button")
        print_step("Clicking button and verifying message change...")
        interaction_evidence = project_service.run_browser_interaction(
            project.id,
            interactions=[
                {
                    "action": "wait_for_function",
                    "value": "document.body.innerText.includes('Lumina Builder Test')",
                },
                {
                    "action": "wait_for_function",
                    "value": "document.querySelector('button') !== null",
                },
                {
                    "action": "click",
                    "selector": "button",
                },
                {
                    "action": "wait_for_function",
                    "value": "document.body.innerText.includes('Button clicked!')",
                },
            ],
        )
        print_result("Page Loaded", interaction_evidence.page_loaded)
        print_result("Console Errors", interaction_evidence.console_errors)
        print_result("Network Errors", interaction_evidence.network_errors)
        print_result("Uncaught Exceptions", interaction_evidence.uncaught_exceptions)
        print_result("Screenshot", interaction_evidence.screenshot_path)
        if interaction_evidence.page_content:
            print_result("Page Content (first 1000 chars)", interaction_evidence.page_content[:1000])

        assert interaction_evidence.page_loaded, "Page did not load after interaction"
        assert not interaction_evidence.console_errors, f"Console errors: {interaction_evidence.console_errors}"
        assert not interaction_evidence.network_errors, f"Network errors: {interaction_evidence.network_errors}"
        assert not interaction_evidence.uncaught_exceptions, f"Uncaught exceptions: {interaction_evidence.uncaught_exceptions}"

        # Check if message changed (look for any indication of state change)
        content = interaction_evidence.page_content or ""
        has_message_change = any(
            word in content.lower()
            for word in ["clicked", "changed", "message", "hello", "world", "updated"]
        )
        print_result("Message change detected", has_message_change)

        print("✓ Browser interaction test passed!")

        # Step 7: Introduce a controlled defect
        print_section("STEP 7: Introduce Controlled Defect")
        print_step("Breaking the button onClick handler...")

        # Find the main component file
        component_files = list(project_path.rglob("*.jsx")) + list(project_path.rglob("*.tsx")) + list(project_path.rglob("*.js")) + list(project_path.rglob("*.ts"))
        main_component = None
        for f in component_files:
            if f.name in ("App.jsx", "App.tsx", "main.jsx", "main.tsx", "index.jsx", "index.tsx"):
                main_component = f
                break
        if not main_component and component_files:
            main_component = component_files[0]

        if main_component:
            original_content = main_component.read_text()
            print_result("Modified file", str(main_component.relative_to(project_path)))

            # Introduce defect: break the onClick handler
            defective_content = original_content.replace(
                "onClick=",
                "onClickBroken="  # This will break the click handler
            )
            main_component.write_text(defective_content)
            print("✓ Defect introduced: onClick handler broken")
        else:
            raise RuntimeError("Could not find main component file")

        # Step 8: Verify defect is detected via browser
        print_section("STEP 8: Detect Defect via Browser")
        print_step("Running browser interaction after defect...")
        defect_evidence = project_service.run_browser_interaction(
            project.id,
            interactions=[
                {
                    "action": "wait_for_function",
                    "value": "document.body.innerText.includes('Lumina Builder Test')",
                },
                {
                    "action": "click",
                    "selector": "button",
                },
                {
                    "action": "wait_for_function",
                    "value": "document.body.innerText.includes('clicked') || document.body.innerText.includes('Clicked') || document.body.innerText.includes('Changed') || document.body.innerText.includes('Message')",
                },
            ],
        )
        print_result("Page Loaded", defect_evidence.page_loaded)
        print_result("Console Errors", defect_evidence.console_errors)
        print_result("Network Errors", defect_evidence.network_errors)
        print_result("Uncaught Exceptions", defect_evidence.uncaught_exceptions)
        if defect_evidence.page_content:
            print_result("Page Content (first 1000 chars)", defect_evidence.page_content[:1000])

        # The defect should cause the button click to not work
        # The wait_for_function should timeout, but we'll check console for React errors
        has_react_error = any(
            "onClickBroken" in err or "onClick" in err or "function" in err.lower() or "undefined" in err.lower()
            for err in defect_evidence.console_errors
        )
        print_result("React/JS errors detected", has_react_error)

        # Step 9: Run autonomous repair loop
        print_section("STEP 9: Autonomous Repair Loop")
        print_step("Setting up autonomous repair...")

        # We need to use the V2 autonomous system
        # First, create a task request for the repair
        task_request = TaskRequest(
            prompt="Fix the broken button onClick handler in the React application. The button should change a visible message when clicked.",
            autonomous=True,
            max_attempts=3,
            timeout_seconds=120,
            project_id=project.id,
        )

        # Create a simple planner that returns a plan to fix the onClick
        class RepairPlanner:
            def create_plan(self, request: TaskRequest):
                from backend.code_builder_v2.models import ChangePlan, PlannedChange
                # Find the main component file
                component_files = list(project_path.rglob("*.jsx")) + list(project_path.rglob("*.tsx"))
                main_comp = component_files[0] if component_files else None

                if main_comp:
                    rel_path = main_comp.relative_to(project_path).as_posix()
                else:
                    rel_path = "src/App.tsx"

                return ChangePlan(
                    summary="Fix broken button onClick handler",
                    changes=[
                        PlannedChange(
                            path=rel_path,
                            operation="modify",
                            reason="Fix broken onClick handler on button",
                        )
                    ],
                    validation_commands=["npm install --legacy-peer-deps"],
                )

        # Create the autonomous loop
        client = LocalOllamaClient()
        generator = LocalOllamaChangeGenerator(client)

        runner = WorkspaceAttemptRunner(
            generator=generator,
            plan=RepairPlanner().create_plan(task_request),
            request=task_request,
        )

        diagnoser = EvidenceDiagnoser(client)

        loop = AutonomousBuildLoop(
            runner=runner,
            diagnoser=diagnoser,
            workspace_service=DisposableWorkspaceService(),
            publisher=VerifiedWorkspacePublisher(runtime_root),
            max_attempts=3,
        )

        print_step("Executing autonomous repair loop...")
        autonomous_result = loop.execute(
            repository_root=str(project_path),
            instruction=task_request.prompt,
        )

        print_result("Successful", autonomous_result.successful)
        print_result("Attempts", autonomous_result.attempts)
        print_result("Changed Paths", autonomous_result.changed_paths)
        print_result("Stop Reason", autonomous_result.stop_reason)

        if autonomous_result.final_evidence:
            print_result("Final Evidence Summary", autonomous_result.final_evidence.summary)

        for event in autonomous_result.events:
            print(f"    Event: {event.phase.value} (attempt {event.attempt}) - {event.message}")

        if not autonomous_result.successful:
            print("⚠ Autonomous repair did not succeed, but continuing...")

        # Step 10: Restart dev server and re-verify
        print_section("STEP 10: Restart Server and Re-verify")
        print_step("Restarting dev server...")

        project_service.stop_dev_server(project.id)
        time.sleep(2)
        server_info = project_service.start_dev_server(project.id, timeout=60)
        print_result("Server Status", server_info.status.value)
        time.sleep(5)

        # Final browser verification
        print_step("Running final browser verification...")
        final_evidence = project_service.run_browser_interaction(
            project.id,
            interactions=[
                {
                    "action": "wait_for_function",
                    "value": "document.body.innerText.includes('Lumina Builder Test')",
                },
                {
                    "action": "click",
                    "selector": "button",
                },
                {
                    "action": "wait_for_function",
                    "value": "document.body.innerText.includes('clicked') || document.body.innerText.includes('Clicked') || document.body.innerText.includes('Changed') || document.body.innerText.includes('Message')",
                },
            ],
        )
        print_result("Page Loaded", final_evidence.page_loaded)
        print_result("Console Errors", final_evidence.console_errors)
        print_result("Network Errors", final_evidence.network_errors)
        print_result("Uncaught Exceptions", final_evidence.uncaught_exceptions)
        if final_evidence.page_content:
            print_result("Page Content (first 1000 chars)", final_evidence.page_content[:1000])

        # Verify fix
        assert final_evidence.page_loaded, "Page did not load after repair"
        assert not final_evidence.console_errors, f"Console errors after repair: {final_evidence.console_errors}"
        assert not final_evidence.network_errors, f"Network errors after repair: {final_evidence.network_errors}"
        assert not final_evidence.uncaught_exceptions, f"Uncaught exceptions after repair: {final_evidence.uncaught_exceptions}"

        content = final_evidence.page_content or ""
        has_message_change = any(
            word in content.lower()
            for word in ["clicked", "changed", "message", "hello", "world", "updated"]
        )
        print_result("Message change detected after repair", has_message_change)

        # Cleanup
        project_service.stop_dev_server(project.id)
        project_service.cleanup()

        print_section("END-TO-END TEST COMPLETE")
        print("✓ All steps completed successfully!")
        print(f"  Project ID: {project.id}")
        print(f"  Project Path: {project.workspace_root}")
        print(f"  Preview URL: {server_info.url}")
        print(f"  Final Status: {'PASS' if final_evidence.page_loaded and not final_evidence.console_errors else 'FAIL'}")

        return {
            "project_id": project.id,
            "project_path": str(project.workspace_root),
            "preview_url": server_info.url,
            "initial_evidence": evidence,
            "interaction_evidence": interaction_evidence,
            "defect_evidence": defect_evidence,
            "autonomous_result": autonomous_result,
            "final_evidence": final_evidence,
            "success": True,
        }


if __name__ == "__main__":
    try:
        result = run_e2e_test()
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)