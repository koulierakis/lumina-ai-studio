"""Filesystem snapshots + rollback.

Before a repair attempt we tar the whole project into
`artifacts/checkpoints/N.tar.gz`. If the repair worsens things we can
restore an earlier checkpoint. History is recorded on the Job.

Snapshots are content-tarballs, not database state — the Job document
already provides Mongo-level checkpointing.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tarfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from ..models import Snapshot
from .. import workspace
from ..security import sandbox_env


def _checkpoint_dir(job_id: str) -> Path:
    d = workspace.artifacts_dir(job_id) / "checkpoints"
    d.mkdir(parents=True, exist_ok=True)
    return d


def snapshot(job_id: str, label: str = "") -> Snapshot:
    """Create a tar.gz snapshot of the project dir."""
    project = workspace.project_dir(job_id)
    ck_dir = _checkpoint_dir(job_id)
    idx = len(list(ck_dir.glob("*.tar.gz")))
    fname = f"{idx:03d}-{_slug(label) or 'checkpoint'}.tar.gz"
    out = ck_dir / fname

    with tarfile.open(out, "w:gz") as tf:
        tf.add(project, arcname=".", recursive=True,
               filter=_skip_transient)
    return Snapshot(
        id=str(idx),
        label=label or f"checkpoint-{idx}",
        path=str(out),
        created_at=datetime.now(timezone.utc).isoformat(),
        size_bytes=out.stat().st_size,
    )


def _skip_transient(info: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
    skip = ("__pycache__", "node_modules", ".venv", "venv", ".pytest_cache")
    parts = info.name.split("/")
    if any(part in skip for part in parts):
        return None
    return info


def list_snapshots(job_id: str) -> List[Snapshot]:
    ck_dir = _checkpoint_dir(job_id)
    out: List[Snapshot] = []
    for p in sorted(ck_dir.glob("*.tar.gz")):
        idx_padded, _, label = p.stem.partition("-")
        idx = str(int(idx_padded)) if idx_padded.isdigit() else idx_padded
        out.append(Snapshot(
            id=idx,
            label=label or p.stem,
            path=str(p),
            created_at=datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
            size_bytes=p.stat().st_size,
        ))
    return out


def restore(job_id: str, snapshot_id: str) -> Snapshot:
    """Overwrite the project directory with the contents of a snapshot."""
    ck_dir = _checkpoint_dir(job_id)
    candidates = list(ck_dir.glob(f"{int(snapshot_id):03d}-*.tar.gz"))
    if not candidates:
        raise FileNotFoundError(f"snapshot {snapshot_id} not found")
    tar_path = candidates[0]

    project = workspace.project_dir(job_id)
    # Nuke and re-extract. Keep the project dir itself.
    for child in project.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except OSError:
                pass
    with tarfile.open(tar_path, "r:gz") as tf:
        tf.extractall(project, filter="data")  # noqa: S202 (safe: our tarballs)
    return Snapshot(
        id=snapshot_id,
        label=tar_path.stem,
        path=str(tar_path),
        created_at=datetime.fromtimestamp(tar_path.stat().st_mtime, tz=timezone.utc).isoformat(),
        size_bytes=tar_path.stat().st_size,
    )


def _slug(s: str) -> str:
    import re
    return re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-")[:32]


def prepare_work_branch(project_dir: Path, job_id: str) -> Optional[str]:
    """Create/checkout an isolated local branch for Builder changes."""
    try:
        git_bin = shutil.which("git")
        dot_git = project_dir / ".git"
        if not git_bin or not dot_git.is_dir():
            return None
        branch = "gold-builder/" + "".join(ch for ch in job_id[:12] if ch.isalnum() or ch in {"-", "_"})
        subprocess.run([git_bin, "config", "user.name", "Gold Builder"], cwd=project_dir, check=True, capture_output=True)
        subprocess.run([git_bin, "config", "user.email", "gold-builder@local.dev"], cwd=project_dir, check=True, capture_output=True)
        exists = subprocess.run([git_bin, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=project_dir).returncode == 0
        cmd = [git_bin, "checkout", branch] if exists else [git_bin, "checkout", "-b", branch]
        subprocess.run(cmd, cwd=project_dir, check=True, capture_output=True)
        return branch
    except Exception:
        return None


def commit_if_git(project_dir: Path, message: str) -> Optional[str]:
    """Create a local commit for verified changes without pushing remotely."""
    try:
        git_bin = shutil.which("git")
        if not git_bin:
            return None
        dot_git = project_dir / ".git"
        if not dot_git.is_dir():
            subprocess.run([git_bin, "init"], cwd=project_dir, check=True, capture_output=True)
        subprocess.run([git_bin, "config", "user.name", "Gold Builder"], cwd=project_dir, check=True, capture_output=True)
        subprocess.run([git_bin, "config", "user.email", "gold-builder@local.dev"], cwd=project_dir, check=True, capture_output=True)
        # Job attachments under inputs/ are reference material, never repository output.
        # Exclude them at staging time too: .git/info/exclude alone cannot protect a
        # path that was already tracked by the source repository.
        exclude = dot_git / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        current = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if "/inputs/" not in {line.strip() for line in current.splitlines()}:
            separator = "" if not current or current.endswith("\n") else "\n"
            exclude.write_text(current + separator + "/inputs/\n", encoding="utf-8")
        subprocess.run(
            [git_bin, "add", "-A"],
            cwd=project_dir, check=True, capture_output=True,
        )
        has_head = subprocess.run(
            [git_bin, "rev-parse", "--verify", "HEAD"],
            cwd=project_dir, capture_output=True,
        ).returncode == 0
        if has_head:
            subprocess.run(
                [git_bin, "reset", "-q", "HEAD", "--", "inputs"],
                cwd=project_dir, check=True, capture_output=True,
            )
        else:
            subprocess.run(
                [git_bin, "rm", "--cached", "-r", "--ignore-unmatch", "-q", "inputs"],
                cwd=project_dir, check=True, capture_output=True,
            )
        res = subprocess.run([git_bin, "commit", "-m", message], cwd=project_dir, capture_output=True, text=True)
        if res.returncode != 0 and "nothing to commit" not in (res.stdout + res.stderr).lower():
            return None
        sha_res = subprocess.run([git_bin, "rev-parse", "HEAD"], cwd=project_dir, capture_output=True, text=True)
        return sha_res.stdout.strip() if sha_res.returncode == 0 else None
    except Exception:
        return None


def push_current_branch(project_dir: Path) -> Optional[str]:
    """Push the current verified branch to origin without embedding credentials in URLs."""
    git_bin = shutil.which("git")
    if not git_bin or not (project_dir / ".git").is_dir():
        return None
    branch_res = subprocess.run(
        [git_bin, "branch", "--show-current"], cwd=project_dir,
        capture_output=True, text=True,
    )
    branch = branch_res.stdout.strip()
    if branch_res.returncode != 0 or not branch:
        return None

    env = sandbox_env({"GIT_TERMINAL_PROMPT": "0"})
    askpass = token_file = None
    token = (os.environ.get("GB_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    remote = subprocess.run(
        [git_bin, "remote", "get-url", "origin"], cwd=project_dir,
        capture_output=True, text=True,
    )
    remote_url = remote.stdout.strip() if remote.returncode == 0 else ""
    if "github.com" in remote_url.lower():
        if not token:
            return None
        nonce = uuid.uuid4().hex
        askpass = project_dir.parent / f".gb-push-askpass-{nonce}.sh"
        token_file = project_dir.parent / f".gb-push-token-{nonce}"
        token_file.write_text(token, encoding="utf-8")
        token_file.chmod(0o600)
        askpass.write_text(
            "#!/bin/sh\ncase \"$1\" in\n  *Username*) echo x-access-token ;;\n  *) cat \"$GB_GIT_TOKEN_FILE\" ;;\nesac\n",
            encoding="utf-8",
        )
        askpass.chmod(0o700)
        env["GIT_ASKPASS"] = str(askpass)
        env["GIT_ASKPASS_REQUIRE"] = "force"
        env["GB_GIT_TOKEN_FILE"] = str(token_file)
    try:
        pushed = subprocess.run(
            [git_bin, "push", "--set-upstream", "origin", branch],
            cwd=project_dir, env=env, capture_output=True, text=True,
        )
        return branch if pushed.returncode == 0 else None
    finally:
        for secret_file in (askpass, token_file):
            if secret_file:
                with contextlib.suppress(OSError):
                    secret_file.unlink()
