"""Existing repository inspection.

Given a Git URL or approved local path, snapshots the repo into the job
workspace, walks the file tree, detects the stack and returns a compact
summary usable by the patch planner.

Only reads the repo — does not modify it during inspection. Git clone runs
in a sandboxed environment so credentials from the host are not leaked.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional

from ..security import is_github_remote, sandbox_env
from .stacks import detect_stack
from .repo_intelligence import RepoContextMap, build_repo_map, format_repo_architecture_summary

MAX_FILE_BYTES = 40_000  # keep prompts sane
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".woff", ".woff2",
              ".ttf", ".eot", ".mp4", ".mov", ".webm", ".mp3", ".pdf", ".zip"}
SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__", "dist",
             "build", ".next", ".yarn", ".turbo"}


@dataclass
class InspectedRepo:
    root: Path
    stack_id: str
    file_tree: List[str] = field(default_factory=list)
    key_files: Dict[str, str] = field(default_factory=dict)  # path -> content snippet
    notes: List[str] = field(default_factory=list)
    repo_map: Optional[RepoContextMap] = None


async def clone_or_copy(source: str, dest: Path) -> Path:
    """If source starts with git:/https:/ssh: — git clone. Else — copytree."""
    dest.mkdir(parents=True, exist_ok=True)
    if source.startswith(("http://", "https://", "git@", "git://", "ssh://")):
        # git clone (shallow) into dest — sandboxed env so no host secrets leak
        env = sandbox_env({"GIT_TERMINAL_PROMPT": "0"})
        askpass = token_file = None
        token = (os.environ.get("GB_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
        if token and is_github_remote(source):
            nonce = uuid.uuid4().hex
            askpass = dest.parent / f".gb-askpass-{nonce}.sh"
            token_file = dest.parent / f".gb-token-{nonce}"
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
            # sandbox_env intentionally strips most host state. Preserve only the
            # non-secret pointer needed by our ephemeral askpass helper; the token
            # itself remains in the chmod-0600 temporary file and is deleted below.
            env["GIT_CONFIG_COUNT"] = "1"
            env["GIT_CONFIG_KEY_0"] = "credential.helper"
            env["GIT_CONFIG_VALUE_0"] = ""
        try:
            clone_args = ["git", "clone"]
            if os.environ.get("GB_GIT_SHALLOW", "").strip().lower() in {"1", "true", "yes"}:
                clone_args.extend(["--depth", "1"])
            clone_args.extend([source, str(dest)])
            proc = await asyncio.create_subprocess_exec(
                *clone_args,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await proc.communicate()
        finally:
            for secret_file in (askpass, token_file):
                if secret_file:
                    with contextlib.suppress(OSError):
                        secret_file.unlink()
        if proc.returncode != 0:
            output = stdout.decode("utf-8", errors="replace")
            if "Authentication failed" in output or "could not read Username" in output or "Repository not found" in output:
                raise RuntimeError("git clone failed: repository is private or credentials are unavailable")
            raise RuntimeError(f"git clone failed: {output}")
        # Keep .git locally so the Builder can create an isolated work branch
        # and commit its verified changes. Export already excludes .git.
        return dest
    # Local path
    src = Path(source).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"source path not found: {src}")
    if src.is_file():
        raise ValueError("existing-repo source must be a directory")
    # Copy contents, skipping heavy dirs
    for p in src.rglob("*"):
        rel = p.relative_to(src)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        target = dest / rel
        if p.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(Exception):
                shutil.copy2(p, target)
    return dest


def _read_snippet(path: Path) -> Optional[str]:
    if path.suffix.lower() in BINARY_EXT:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:1024]:
        return None
    text = data.decode("utf-8", errors="replace")
    if len(text) > MAX_FILE_BYTES:
        text = text[:MAX_FILE_BYTES] + "\n/* ...truncated... */\n"
    return text


async def inspect(project_root: Path, key_hints: Optional[List[str]] = None, on_file: Optional[Callable[[str], Awaitable[None]]] = None) -> InspectedRepo:
    """Walk project_root and pull out the most relevant files."""
    file_tree: List[str] = []
    key_files: Dict[str, str] = {}
    notes: List[str] = []

    default_hints = [
        "package.json", "vite.config.js", "vite.config.ts", "next.config.js",
        "requirements.txt", "pyproject.toml", "main.py", "server.py",
        "server.js", "index.js", "app.js", "index.html", "README.md",
        "tsconfig.json", "src/App.jsx", "src/App.tsx", "src/main.jsx",
    ]
    hints = set([*(key_hints or []), *default_hints])

    for p in sorted(project_root.rglob("*")):
        rel = p.relative_to(project_root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        rel_str = str(rel).replace("\\", "/")
        if p.is_file():
            file_tree.append(rel_str)
            if on_file:
                await on_file(rel_str)
            if rel_str in hints or rel.name in hints:
                snippet = _read_snippet(p)
                if snippet is not None:
                    key_files[rel_str] = snippet

    stack_id = detect_stack(project_root)
    repo_map = build_repo_map(project_root)
    if not file_tree:
        notes.append("repository is empty")
    return InspectedRepo(
        root=project_root,
        stack_id=stack_id,
        file_tree=file_tree[:500],  # cap
        key_files=key_files,
        notes=notes,
        repo_map=repo_map,
    )


def summarize_for_prompt(repo: InspectedRepo) -> str:
    lines: List[str] = [f"stack_detected: {repo.stack_id}", ""]
    if repo.repo_map:
        lines.append("=== REPO ARCHITECTURE MAP ===")
        lines.append(format_repo_architecture_summary(repo.repo_map))
        lines.append("=============================\n")
    lines.append("file_tree (first 200):")
    for f in repo.file_tree[:200]:
        lines.append(f"  {f}")
    if len(repo.file_tree) > 200:
        lines.append(f"  ... and {len(repo.file_tree) - 200} more")
    lines.append("")
    lines.append("key_files:")
    for path, content in list(repo.key_files.items())[:12]:
        lines.append(f"--- {path} ---")
        lines.append(content[:6000])
    return "\n".join(lines)
