from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from .models import FrameworkType, Project, ProjectStatus
from .ollama import OllamaClient


ROOT = Path(__file__).resolve().parent.parent.parent
PROJECTS_ROOT = ROOT / "generated_projects"
PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("CODE_MODEL", "qwen2.5-coder:7b")
MAX_FILES = 80
MAX_FILE_BYTES = 500_000


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return value[:50] or f"project-{uuid.uuid4().hex[:8]}"


def _safe_project(project_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", project_id):
        raise ValueError("Invalid project id")
    path = (PROJECTS_ROOT / project_id).resolve()
    if PROJECTS_ROOT.resolve() not in path.parents:
        raise ValueError("Unsafe project path")
    return path


def _safe_file(project: Path, relative: str) -> Path:
    relative = relative.replace("\\", "/").lstrip("/")
    if not relative or ".." in Path(relative).parts:
        raise ValueError("Unsafe file path")
    target = (project / relative).resolve()
    if project.resolve() not in target.parents:
        raise ValueError("Unsafe file path")
    return target


def ollama_status() -> dict[str, Any]:
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=4)
        response.raise_for_status()
        models = [m.get("name") for m in response.json().get("models", [])]
        return {"online": True, "model": OLLAMA_MODEL, "installed": OLLAMA_MODEL in models, "models": models}
    except Exception:
        return {"online": False, "model": OLLAMA_MODEL, "installed": False, "models": []}


def _generate(prompt: str, timeout: int = 600) -> str:
    response = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "options": {"temperature": 0.15}},
        timeout=timeout,
    )
    response.raise_for_status()
    return str(response.json().get("response") or "")


def _extract_json(text: str) -> dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(candidate)


def detect_framework(files: list[dict[str, Any]]) -> FrameworkType:
    paths = [f.get("path", "") for f in files]
    has_package_json = any(p.endswith("package.json") for p in paths)
    has_next_config = any(p.startswith("next.config") for p in paths)
    has_vite_config = any(p.startswith("vite.config") for p in paths)
    has_pyproject = any(p.endswith("pyproject.toml") for p in paths)
    has_requirements = any(p.endswith("requirements.txt") for p in paths)
    has_main_py = any(p.endswith("main.py") or p.endswith("app.py") for p in paths)

    if has_package_json and has_next_config:
        return FrameworkType.nextjs
    if has_package_json and has_vite_config:
        return FrameworkType.react_vite
    if has_package_json:
        return FrameworkType.react_vite
    if has_pyproject or has_requirements:
        if has_main_py:
            return FrameworkType.python_fastapi
        return FrameworkType.python_flask
    return FrameworkType.vanilla_js


def create_project_from_prompt(
    prompt: str,
    project_name: str | None = None,
    framework_hint: str | None = None,
) -> Project:
    status = ollama_status()
    if not status["online"] or not status["installed"]:
        raise RuntimeError(f"Ollama or model {OLLAMA_MODEL} is not available")

    name = project_name or "Generated Project"
    project_id = _slug(name)
    base = project_id
    index = 2
    while (PROJECTS_ROOT / project_id).exists():
        project_id = f"{base}-{index}"
        index += 1

    project = _safe_project(project_id)
    project.mkdir(parents=True)

    framework_instruction = ""
    if framework_hint:
        framework_instruction = f"\nPreferred framework: {framework_hint}\n"

    generation_prompt = f"""You are LUMINA Code Builder, a senior full-stack engineer.
Create a complete, runnable application for local development.
Project name: {name}
Description: {prompt}
{framework_instruction}

Return ONLY valid JSON with this exact shape:
{{
  "summary": "one sentence description",
  "run_instructions": ["command 1", "command 2"],
  "framework": "react_vite|nextjs|python_fastapi|python_flask|vanilla_js",
  "files": [{{"path": "relative/path.ext", "content": "full file content"}}]
}}
Rules:
- Maximum {MAX_FILES} files.
- Use only relative safe paths.
- Include all configuration files needed (package.json, pyproject.toml, etc.).
- Include a README.md with run instructions.
- Prefer simple, maintainable technologies.
- For React: use Vite, TypeScript, functional components.
- For Python: use FastAPI with uvicorn, include requirements.txt.
- Do not include binaries, base64, secrets, .env credentials, node_modules or virtual environments.
- Make the first generated version focused and runnable.
- The app must start with a single command and serve on localhost.
"""

    raw = _generate(generation_prompt)
    payload = _extract_json(raw)
    files = payload.get("files") or []
    if not isinstance(files, list) or not files or len(files) > MAX_FILES:
        raise ValueError("The model returned an invalid number of files")

    framework_str = payload.get("framework", "").lower()
    try:
        framework = FrameworkType(framework_str)
    except ValueError:
        framework = detect_framework(files)

    written = []
    for item in files:
        relative = str(item.get("path") or "")
        content = str(item.get("content") or "")
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_FILE_BYTES:
            raise ValueError(f"Generated file is too large: {relative}")
        target = _safe_file(project, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(relative.replace("\\", "/"))

    project_obj = Project(
        id=project_id,
        name=name,
        workspace_root=str(project),
        status=ProjectStatus.generating,
        framework=framework,
        metadata={
            "summary": str(payload.get("summary") or "Application generated."),
            "run_instructions": payload.get("run_instructions") or [],
            "original_prompt": prompt,
        },
    )

    (project / ".lumina-project.json").write_text(json.dumps(project_obj.model_dump(mode="json"), indent=2), encoding="utf-8")
    return project_obj


def install_dependencies(project: Project) -> tuple[bool, str]:
    project_path = Path(project.workspace_root)
    if not project_path.exists():
        return False, "Project workspace does not exist"

    commands_to_try = []

    if (project_path / "package.json").exists():
        if (project_path / "package-lock.json").exists():
            commands_to_try.append(["npm", "ci"])
        else:
            commands_to_try.append(["npm", "install"])

    if (project_path / "requirements.txt").exists():
        commands_to_try.append(["pip", "install", "-r", "requirements.txt"])

    if (project_path / "pyproject.toml").exists():
        commands_to_try.append(["pip", "install", "-e", "."])

    if not commands_to_try:
        return True, "No dependencies to install"

    all_output = []
    for cmd in commands_to_try:
        try:
            result = subprocess.run(
                cmd,
                cwd=project_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                shell=False,
            )
            all_output.append(f"$ {' '.join(cmd)}\n{result.stdout}\n{result.stderr}")
            if result.returncode != 0:
                return False, "\n".join(all_output)
        except subprocess.TimeoutExpired:
            return False, f"Timeout installing dependencies: {' '.join(cmd)}"
        except Exception as exc:
            return False, f"Error running {' '.join(cmd)}: {exc}"

    return True, "\n".join(all_output)


def get_dev_server_command(project: Project) -> tuple[str, int] | None:
    project_path = Path(project.workspace_root)
    framework = project.framework

    if framework == FrameworkType.react_vite:
        return ("npm run dev -- --host 0.0.0.0 --port {port}", 5173)
    if framework == FrameworkType.nextjs:
        return ("npm run dev -- --port {port}", 3000)
    if framework == FrameworkType.python_fastapi:
        return ("uvicorn main:app --host 0.0.0.0 --port {port} --reload", 8000)
    if framework == FrameworkType.python_flask:
        return ("flask run --host 0.0.0.0 --port {port}", 5000)
    if framework == FrameworkType.vanilla_js:
        return ("npx serve . -l {port}", 3000)

    if (project_path / "package.json").exists():
        return ("npm run dev -- --host 0.0.0.0 --port {port}", 5173)
    if (project_path / "requirements.txt").exists() or (project_path / "pyproject.toml").exists():
        return ("uvicorn main:app --host 0.0.0.0 --port {port} --reload", 8000)

    return None


def find_free_port(start: int = 3000, end: int = 9999) -> int:
    import socket
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port available")