from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def local_tools_dir() -> Path:
    return repo_root() / "tools"


def local_ffmpeg_dir() -> Path:
    return local_tools_dir() / "ffmpeg"


def local_ffmpeg_path() -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return local_ffmpeg_dir() / f"ffmpeg{suffix}"


def local_ffprobe_path() -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return local_ffmpeg_dir() / f"ffprobe{suffix}"


def resolve_executable(name: str, *, local_first: bool = True) -> str | None:
    candidates: list[Path] = []
    lowered = name.lower()
    if local_first and lowered in {"ffmpeg", "ffmpeg.exe"}:
        candidates.append(local_ffmpeg_path())
    if local_first and lowered in {"ffprobe", "ffprobe.exe"}:
        candidates.append(local_ffprobe_path())
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    names = [name]
    if os.name == "nt" and not name.lower().endswith((".exe", ".cmd", ".bat")):
        names.extend([f"{name}.cmd", f"{name}.exe"])
    for item in names:
        found = shutil.which(item)
        if found:
            return found
    return None


def run_version(executable: str, *args: str, timeout: float = 8.0) -> dict[str, Any]:
    path = resolve_executable(executable)
    if not path:
        return {"available": False, "path": None, "version": None, "stdout": "", "stderr": ""}
    try:
        completed = subprocess.run(
            [path, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        output = (completed.stdout or completed.stderr or "").strip().splitlines()
        return {
            "available": completed.returncode == 0,
            "path": path,
            "version": output[0].strip() if output else None,
            "stdout": completed.stdout[-2000:],
            "stderr": completed.stderr[-2000:],
            "returncode": completed.returncode,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "path": path, "version": None, "error": str(exc)}


def tool_env() -> dict[str, str]:
    env = os.environ.copy()
    ffmpeg_dir = str(local_ffmpeg_dir())
    if local_ffmpeg_dir().exists():
        env["PATH"] = ffmpeg_dir + os.pathsep + env.get("PATH", "")
        env["LUMINA_FFMPEG"] = str(local_ffmpeg_path())
        env["LUMINA_FFPROBE"] = str(local_ffprobe_path())
    return env
