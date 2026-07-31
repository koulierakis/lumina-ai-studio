"""Local Code Creator service for LUMINA.

Creates isolated application projects under backend/generated_projects and uses the
local Ollama HTTP API. It never writes outside that directory.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent
PROJECTS_ROOT = ROOT / "generated_projects"
PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("CODE_MODEL", "qwen2.5-coder:7b")
MAX_FILES = 60
MAX_FILE_BYTES = 300_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def list_projects() -> list[dict[str, Any]]:
    results = []
    for path in sorted(PROJECTS_ROOT.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        meta = path / ".lumina-project.json"
        if path.is_dir() and meta.exists():
            try:
                results.append(json.loads(meta.read_text(encoding="utf-8")))
            except Exception:
                continue
    return results


def create_project(name: str, description: str, stack: str = "auto") -> dict[str, Any]:
    project_id = _slug(name)
    base = project_id
    index = 2
    while (PROJECTS_ROOT / project_id).exists():
        project_id = f"{base}-{index}"
        index += 1
    project = _safe_project(project_id)
    project.mkdir(parents=True)
    metadata = {
        "id": project_id,
        "name": name.strip() or project_id,
        "description": description.strip(),
        "stack": stack,
        "status": "created",
        "created_at": _now(),
        "updated_at": _now(),
        "files": 0,
    }
    (project / ".lumina-project.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def get_project(project_id: str) -> dict[str, Any]:
    project = _safe_project(project_id)
    meta = project / ".lumina-project.json"
    if not meta.exists():
        raise FileNotFoundError(project_id)
    data = json.loads(meta.read_text(encoding="utf-8"))
    files = []
    for file in project.rglob("*"):
        if file.is_file() and file.name != ".lumina-project.json":
            files.append(str(file.relative_to(project)).replace("\\", "/"))
    data["file_list"] = sorted(files)
    return data


def generate_project(project_id: str) -> dict[str, Any]:
    project = _safe_project(project_id)
    metadata = get_project(project_id)
    status = ollama_status()
    if not status["online"] or not status["installed"]:
        raise RuntimeError(f"Ollama or model {OLLAMA_MODEL} is not available")

    prompt = f"""You are LUMINA Code Creator, a senior full-stack engineer.
Create a small but complete, runnable application for personal local use.
Project name: {metadata['name']}
Description: {metadata['description']}
Preferred stack: {metadata['stack']}

Return ONLY valid JSON with this exact shape:
{{
  "summary": "one sentence",
  "run_instructions": ["command 1", "command 2"],
  "files": [{{"path": "relative/path.ext", "content": "full file content"}}]
}}
Rules:
- Maximum {MAX_FILES} files.
- Use only relative safe paths.
- Include README.md and all configuration files needed.
- Prefer simple, maintainable technologies and SQLite for data when suitable.
- Do not include binaries, base64, secrets, .env credentials, node_modules or virtual environments.
- Make the first generated version focused and runnable.
"""
    raw = _generate(prompt)
    payload = _extract_json(raw)
    files = payload.get("files") or []
    if not isinstance(files, list) or not files or len(files) > MAX_FILES:
        raise ValueError("The model returned an invalid number of files")

    backup = project / ".lumina-backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
    backup.mkdir(parents=True, exist_ok=True)
    for existing in project.iterdir():
        if existing.name not in {".lumina-project.json", ".lumina-backups"}:
            destination = backup / existing.name
            shutil.move(str(existing), str(destination))

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

    metadata.update({
        "status": "generated",
        "summary": str(payload.get("summary") or "Application generated."),
        "run_instructions": payload.get("run_instructions") or [],
        "updated_at": _now(),
        "files": len(written),
    })
    (project / ".lumina-project.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    metadata["file_list"] = sorted(written)
    return metadata


def read_file(project_id: str, relative: str) -> dict[str, str]:
    project = _safe_project(project_id)
    target = _safe_file(project, relative)
    if not target.is_file() or target.stat().st_size > MAX_FILE_BYTES:
        raise FileNotFoundError(relative)
    return {"path": relative, "content": target.read_text(encoding="utf-8", errors="replace")}


def run_safe_check(project_id: str) -> dict[str, Any]:
    project = _safe_project(project_id)
    commands: list[list[str]] = []
    if (project / "package.json").exists():
        commands.append(["npm", "run", "build", "--if-present"])
    if any(project.rglob("*.py")):
        commands.append(["python", "-m", "compileall", "-q", "."])
    if not commands:
        return {"ok": True, "checks": [{"command": "none", "code": 0, "output": "No automatic check was applicable."}]}
    checks = []
    for command in commands:
        try:
            result = subprocess.run(command, cwd=project, capture_output=True, text=True, timeout=180, shell=False)
            checks.append({"command": " ".join(command), "code": result.returncode, "output": (result.stdout + result.stderr)[-8000:]})
        except Exception as exc:
            checks.append({"command": " ".join(command), "code": -1, "output": str(exc)})
    return {"ok": all(item["code"] == 0 for item in checks), "checks": checks}
