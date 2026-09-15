"""Asynchronous LivePortrait installer with persistent job state and logs."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .liveportrait_provider import LivePortraitProvider

INSTALL_STAGES = [
    "preflight",
    "locating_python",
    "validating_python_version",
    "checking_git",
    "checking_ffmpeg",
    "checking_disk_space",
    "cloning_repository",
    "creating_virtual_environment",
    "upgrading_pip",
    "installing_torch",
    "installing_dependencies",
    "preparing_checkpoint_directories",
    "downloading_checkpoints",
    "verifying_checkpoints",
    "verifying_liveportrait_import",
    "detecting_gpu",
    "validating_cpu_fallback",
    "validating_inference_entrypoint",
    "running_smoke_test",
    "completed",
    "failed",
    "cancelled",
]

ACTIVE_INSTALL_STATES = {"queued", "running"}
TERMINAL_INSTALL_STATES = {"completed", "failed", "cancelled"}
COMPATIBLE_PYTHON = {(3, 10), (3, 11), (3, 12), (3, 13)}


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def runtime_root() -> Path:
    configured = os.environ.get("LUMINA_RUNTIME_DIR", "").strip()
    root = Path(configured) if configured else Path(__file__).resolve().parents[2] / "runtime"
    root.mkdir(parents=True, exist_ok=True)
    return root


def installations_root() -> Path:
    root = runtime_root() / "talking_portrait" / "installations"
    root.mkdir(parents=True, exist_ok=True)
    return root


def job_dir(job_id: str) -> Path:
    root = installations_root() / job_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def recent_log_lines(job_id: str, limit: int = 80) -> list[str]:
    path = job_dir(job_id) / "installer.log"
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except OSError:
        return []


@dataclass
class InstallerError(RuntimeError):
    error_code: str
    user_message: str
    technical: dict[str, Any]


class LivePortraitInstaller:
    def __init__(self, job_id: str, update: Callable[[dict[str, Any]], None], should_cancel: Callable[[], bool]) -> None:
        self.job_id = job_id
        self.update = update
        self.should_cancel = should_cancel
        self.dir = job_dir(job_id)
        self.install_log = self.dir / "installer.log"
        self.stdout_log = self.dir / "stdout.log"
        self.stderr_log = self.dir / "stderr.log"
        self.diagnostics_file = self.dir / "diagnostics.json"
        self.install_file = self.dir / "install.json"
        self.root = LivePortraitProvider.install_root()
        self.venv_python = LivePortraitProvider.venv_python()
        self.python: str | None = None
        self.git: str | None = None
        self.ffmpeg: str | None = None
        self.compute_mode = "cpu"
        self.gpu_name: str | None = None
        self.torch_version: str | None = None

    def log(self, line: str) -> None:
        timestamped = f"{utc_now()} {line}"
        with self.install_log.open("a", encoding="utf-8") as handle:
            handle.write(timestamped + "\n")

    def persist(self, payload: dict[str, Any]) -> None:
        self.install_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.update(payload)

    def stage(self, stage: str, progress: int, message: str, **extra: Any) -> None:
        if self.should_cancel():
            raise InstallerError("cancelled", "LivePortrait installation was cancelled.", {"stage": stage})
        payload = {
            "status": "running" if stage not in {"completed", "failed", "cancelled"} else stage,
            "stage": stage,
            "step": message,
            "progress": max(0, min(int(progress), 100)),
            "current_message": message,
            "updated_at": utc_now(),
            "recent_log_lines": recent_log_lines(self.job_id),
            **extra,
        }
        self.log(f"[{stage}] {message}")
        self.persist(payload)

    def run_command(self, command: list[str], cwd: Path | None = None, stage: str = "preflight", timeout: int | None = None) -> subprocess.CompletedProcess[str]:
        self.log("Running command: " + " ".join(command))
        try:
            result = subprocess.run(command, cwd=str(cwd) if cwd else None, text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, shell=False)
        except PermissionError as exc:
            raise InstallerError("permission_or_antivirus_block", "Antivirus or permission block detected while running installer command.", {"stage": stage, "command": command, "exception": repr(exc)}) from exc
        except subprocess.TimeoutExpired as exc:
            raise InstallerError("command_timeout", "Installer command timed out.", {"stage": stage, "command": command, "timeout": timeout, "stdout": exc.stdout, "stderr": exc.stderr}) from exc
        self.stdout_log.open("a", encoding="utf-8").write(result.stdout or "")
        self.stderr_log.open("a", encoding="utf-8").write(result.stderr or "")
        if result.returncode != 0:
            user = {
                "checking_git": "Git is not installed or is not working.",
                "cloning_repository": "Repository clone failed.",
                "upgrading_pip": "Pip upgrade failed.",
                "installing_torch": "PyTorch installation failed.",
                "installing_dependencies": "LivePortrait dependency installation failed.",
                "running_smoke_test": "LivePortrait smoke test failed.",
            }.get(stage, "LivePortrait installer command failed.")
            raise InstallerError(f"{stage}_failed", user, {"stage": stage, "command": command, "exit_code": result.returncode, "stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:]})
        return result

    def locate_python(self) -> str:
        candidates = [sys.executable]
        if os.name == "nt":
            candidates += [["py", "-3.11"], ["py", "-3.10"], ["py", "-3.12"], ["py", "-3.13"]]  # type: ignore[list-item]
        for candidate in candidates:
            command = candidate if isinstance(candidate, list) else [candidate]
            try:
                result = subprocess.run(command + ["-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.executable}')"], text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, shell=False)
                if result.returncode != 0:
                    continue
                major, minor, executable = result.stdout.strip().split(".", 2)
                version = (int(major), int(minor))
                if version in COMPATIBLE_PYTHON:
                    return executable
            except Exception:
                continue
        raise InstallerError("compatible_python_not_found", "Compatible Python not found. Install Python 3.10, 3.11, 3.12, or 3.13 and retry.", {"compatible_versions": sorted([f"{a}.{b}" for a, b in COMPATIBLE_PYTHON])})

    def find_ffmpeg(self) -> str:
        repo = Path(__file__).resolve().parents[2]
        local = list((repo / "tools" / "ffmpeg").glob("**/bin/ffmpeg.exe")) + list((repo / "tools" / "ffmpeg").glob("**/ffmpeg.exe"))
        for item in local:
            if item.exists():
                return str(item)
        found = shutil.which("ffmpeg")
        if found:
            return found
        raise InstallerError("ffmpeg_not_found", "FFmpeg is not installed. Install FFmpeg or use the project-local FFmpeg package.", {"stage": "checking_ffmpeg"})

    def checkpoint_inventory(self) -> list[dict[str, Any]]:
        base = LivePortraitProvider.checkpoint_root()
        return [
            {"path": str(base / "liveportrait"), "required": True, "source": "https://huggingface.co/KwaiVGI/LivePortrait", "patterns": ["*.pth", "*.onnx", "*.safetensors"]},
            {"path": str(base / "insightface"), "required": True, "source": "https://huggingface.co/KwaiVGI/LivePortrait", "patterns": ["*.onnx"]},
        ]

    def download_checkpoints(self) -> None:
        root = LivePortraitProvider.checkpoint_root()
        root.mkdir(parents=True, exist_ok=True)
        marker = root / ".lumina_checkpoint_inventory.json"
        inventory = self.checkpoint_inventory()
        marker.write_text(json.dumps({"inventory": inventory, "validated_at": utc_now()}, indent=2), encoding="utf-8")
        # Official LivePortrait checkpoints are managed by the upstream HuggingFace helper.
        helper = self.root / "huggingface_download.py"
        if helper.exists():
            for attempt in range(3):
                try:
                    self.run_command([str(self.venv_python), str(helper)], cwd=self.root, stage="downloading_checkpoints", timeout=3600)
                    return
                except InstallerError:
                    if attempt == 2:
                        raise
                    time.sleep(2 ** attempt)
            return
        self.run_command([str(self.venv_python), "-m", "pip", "install", "huggingface_hub"], cwd=self.root, stage="downloading_checkpoints", timeout=600)
        code = "from huggingface_hub import snapshot_download; snapshot_download(repo_id='KwaiVGI/LivePortrait', local_dir='pretrained_weights', local_dir_use_symlinks=False); print('checkpoints-ok')"
        self.run_command([str(self.venv_python), "-c", code], cwd=self.root, stage="downloading_checkpoints", timeout=7200)

    def verify_checkpoints(self) -> None:
        root = LivePortraitProvider.checkpoint_root()
        if not LivePortraitProvider._checkpoints_ready(root):
            raise InstallerError("checkpoint_download_failed", "Checkpoint download failed. Required LivePortrait checkpoint files were not found.", {"stage": "verifying_checkpoints", "checkpoint_root": str(root), "inventory": self.checkpoint_inventory()})

    def install_torch(self) -> None:
        nvidia = shutil.which("nvidia-smi")
        if nvidia:
            probe = subprocess.run([nvidia, "--query-gpu=name", "--format=csv,noheader"], text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, shell=False)
            if probe.returncode == 0 and probe.stdout.strip():
                self.gpu_name = probe.stdout.strip().splitlines()[0]
                self.run_command([str(self.venv_python), "-m", "pip", "install", "torch", "torchvision", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cu121"], cwd=self.root, stage="installing_torch", timeout=3600)
                return
        self.compute_mode = "cpu"
        self.run_command([str(self.venv_python), "-m", "pip", "install", "torch", "torchvision", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cpu"], cwd=self.root, stage="installing_torch", timeout=3600)

    def verify_runtime(self) -> None:
        code = "import torch, sys; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
        result = self.run_command([str(self.venv_python), "-c", code], cwd=self.root, stage="detecting_gpu", timeout=60)
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        self.torch_version = lines[0] if lines else None
        cuda = len(lines) > 1 and lines[1].lower() == "true"
        self.compute_mode = "cuda" if cuda else "cpu"
        if cuda:
            self.gpu_name = lines[2] if len(lines) > 2 else self.gpu_name

    def smoke_test(self) -> None:
        imports = "import torch; import cv2; import numpy; import imageio; print('imports-ok')"
        self.run_command([str(self.venv_python), "-c", imports], cwd=self.root, stage="verifying_liveportrait_import", timeout=60)
        self.run_command([str(self.venv_python), "inference.py", "--help"], cwd=self.root, stage="validating_inference_entrypoint", timeout=120)
        self.run_command([self.ffmpeg or "ffmpeg", "-version"], stage="running_smoke_test", timeout=20)

    def run(self) -> None:
        started = utc_now()
        try:
            self.stage("preflight", 1, "Starting LivePortrait installation preflight", started_at=started)
            self.stage("locating_python", 5, "Locating compatible Python")
            self.python = self.locate_python()
            self.stage("validating_python_version", 10, f"Using Python executable: {self.python}")
            self.stage("checking_git", 14, "Checking Git executable")
            self.git = shutil.which("git")
            if not self.git:
                raise InstallerError("git_not_found", "Git is not installed. Install Git for Windows and retry.", {"stage": "checking_git"})
            self.run_command([self.git, "--version"], stage="checking_git", timeout=15)
            self.stage("checking_ffmpeg", 18, "Checking FFmpeg executable")
            self.ffmpeg = self.find_ffmpeg()
            self.run_command([self.ffmpeg, "-version"], stage="checking_ffmpeg", timeout=20)
            self.stage("checking_disk_space", 22, "Checking available disk space")
            free = shutil.disk_usage(str(self.root.parent if self.root.parent.exists() else Path.cwd())).free
            if free < 12 * 1024 * 1024 * 1024:
                raise InstallerError("insufficient_disk_space", "Insufficient disk space. At least 12 GB free is required for LivePortrait.", {"free_bytes": free})
            if os.name == "nt":
                os.system("git config --global core.longpaths true >NUL 2>NUL")
            self.stage("cloning_repository", 30, "Cloning or updating LivePortrait repository")
            if not (self.root / ".git").exists():
                self.root.parent.mkdir(parents=True, exist_ok=True)
                if self.root.exists() and any(self.root.iterdir()):
                    raise InstallerError("repository_path_not_empty", "Repository clone failed because the target folder already exists and is not a Git checkout.", {"repository_path": str(self.root)})
                self.run_command([self.git, "clone", "--depth", "1", LivePortraitProvider.repository_url, str(self.root)], stage="cloning_repository", timeout=1800)
            else:
                self.run_command([self.git, "pull", "--ff-only"], cwd=self.root, stage="cloning_repository", timeout=600)
            self.stage("creating_virtual_environment", 42, "Creating virtual environment")
            self.run_command([self.python, "-m", "venv", str(self.root / ".venv")], cwd=self.root, stage="creating_virtual_environment", timeout=600)
            self.stage("upgrading_pip", 50, "Upgrading pip, setuptools, and wheel")
            self.run_command([str(self.venv_python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], cwd=self.root, stage="upgrading_pip", timeout=900)
            self.stage("installing_torch", 58, "Installing supported PyTorch build")
            self.install_torch()
            self.stage("installing_dependencies", 68, "Installing LivePortrait dependencies")
            self.run_command([str(self.venv_python), "-m", "pip", "install", "-r", "requirements.txt"], cwd=self.root, stage="installing_dependencies", timeout=3600)
            self.stage("preparing_checkpoint_directories", 76, "Preparing checkpoint directories")
            LivePortraitProvider.checkpoint_root().mkdir(parents=True, exist_ok=True)
            self.stage("downloading_checkpoints", 82, "Downloading LivePortrait checkpoints from validated upstream sources")
            self.download_checkpoints()
            self.stage("verifying_checkpoints", 88, "Verifying checkpoint inventory")
            self.verify_checkpoints()
            self.stage("detecting_gpu", 92, "Verifying torch runtime and compute mode")
            self.verify_runtime()
            if self.compute_mode == "cpu":
                self.stage("validating_cpu_fallback", 95, "CPU fallback enabled. Generation will be slower than GPU generation.", compute_mode="cpu")
            self.stage("running_smoke_test", 98, "Running lightweight installer smoke test")
            self.smoke_test()
            diagnostics = LivePortraitProvider.diagnostics()
            diagnostics.update({"compute_mode": self.compute_mode, "gpu_name": self.gpu_name, "torch_version": self.torch_version, "ffmpeg": self.ffmpeg})
            self.diagnostics_file.write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
            self.stage("completed", 100, "LivePortrait installation completed and verified", completed_at=utc_now(), error=None, error_code=None, metadata=diagnostics)
        except InstallerError as exc:
            stage = "cancelled" if exc.error_code == "cancelled" else "failed"
            details = {"exception_type": type(exc).__name__, "error_code": exc.error_code, "user_message": exc.user_message, "technical": exc.technical, "timestamp": utc_now()}
            self.diagnostics_file.write_text(json.dumps(details, indent=2), encoding="utf-8")
            self.log(json.dumps(details, ensure_ascii=False))
            self.stage(stage, 100 if stage == "cancelled" else 0, exc.user_message, completed_at=utc_now(), error=exc.user_message, error_code=exc.error_code, full_user_safe_error=exc.user_message, metadata=details)
        except Exception as exc:
            details = {"exception_type": type(exc).__name__, "error_code": "unexpected_installer_error", "user_message": "LivePortrait installer failed unexpectedly.", "technical": {"traceback": traceback.format_exc()}, "timestamp": utc_now()}
            self.diagnostics_file.write_text(json.dumps(details, indent=2), encoding="utf-8")
            self.log(json.dumps(details, ensure_ascii=False))
            self.stage("failed", 0, details["user_message"], completed_at=utc_now(), error=details["user_message"], error_code="unexpected_installer_error", full_user_safe_error=details["user_message"], metadata=details)


def build_initial_install_payload(job_id: str, owner: str, retry_of: str | None = None) -> dict[str, Any]:
    now = utc_now()
    payload = {
        "id": job_id,
        "install_job_id": job_id,
        "owner_email": owner,
        "provider": "liveportrait",
        "status": "queued",
        "stage": "preflight",
        "progress": 0,
        "step": "Queued",
        "current_message": "Queued",
        "started_at": now,
        "updated_at": now,
        "completed_at": None,
        "error_code": None,
        "error": None,
        "full_user_safe_error": None,
        "recent_log_lines": [],
        "log": [],
        "metadata": {"repository_url": LivePortraitProvider.repository_url, "retry_of": retry_of, "platform": platform.platform()},
        "created_at": now,
    }
    job_dir(job_id)
    (job_dir(job_id) / "install.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload

