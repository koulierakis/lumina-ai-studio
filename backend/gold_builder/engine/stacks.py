"""Stack configuration registry.

Each StackConfig describes how to build, run and verify a specific technology
stack. Adding a new stack = adding one entry here — the orchestrator does not
need to know about individual stacks.

A stack config is intentionally small: commands, ports, seed file
suggestions, and a system prompt fragment the planner appends when this stack
is selected.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional



@dataclass
class ServiceDefinition:
    name: str
    start_command: List[str]
    start_cwd: str = "."
    port_env: str = "PORT"
    default_port: int = 8000
    ready_path: str = "/"
    ready_timeout: float = 30.0
    extra_env: Dict[str, str] = field(default_factory=dict)
    services: List[ServiceDefinition] = field(default_factory=list)
    verify_service: Optional[str] = None

@dataclass
class StackConfig:
    id: str
    label: str
    # planner
    planner_hint: str
    seed_files: List[str] = field(default_factory=list)  # files planner MUST include
    # runtime
    install_pipeline: List[List[str]] = field(default_factory=list)
    build_pipeline: List[List[str]] = field(default_factory=list)
    typecheck_pipeline: List[List[str]] = field(default_factory=list)
    lint_pipeline: List[List[str]] = field(default_factory=list)
    test_pipeline: List[List[str]] = field(default_factory=list)
    start_command: Optional[List[str]] = None  # None => use built-in static server
    start_cwd: str = "."  # relative to project root
    port_env: str = "PORT"
    default_port: int = 5173
    ready_path: str = "/"
    detect: Dict[str, List[str]] = field(default_factory=dict)  # heuristics
    # allow env override e.g. VITE dev server needs host binding
    extra_env: Dict[str, str] = field(default_factory=dict)
    services: List[ServiceDefinition] = field(default_factory=list)
    verify_service: Optional[str] = None


# --- registry ---
STACKS: Dict[str, StackConfig] = {}


def register(cfg: StackConfig) -> None:
    STACKS[cfg.id] = cfg


register(StackConfig(
    id="html-static",
    label="Plain HTML/CSS/JS (static)",
    planner_hint=(
        "Use plain HTML, CSS and JavaScript with NO build step. "
        "The frontend must be servable directly by `python -m http.server`."
    ),
    seed_files=["index.html", "styles.css", "app.js", "README.md"],
    default_port=5173,
    ready_path="/",
    detect={"files": ["index.html"], "not_files": ["package.json", "vite.config.js", "requirements.txt"]},
))


register(StackConfig(
    id="react-vite",
    label="React + Vite (SPA)",
    planner_hint=(
        "Use React 18 with Vite 5 and JavaScript (not TypeScript). "
        "Produce: package.json, vite.config.js, index.html at project root, "
        "src/main.jsx, src/App.jsx, src/styles.css, README.md. "
        "Use ONLY these dependencies: react@^18, react-dom@^18, and devDependencies vite@^5 and @vitejs/plugin-react@^4. "
        "Do NOT introduce TypeScript, Tailwind, routers or other libraries."
    ),
    seed_files=[
        "package.json", "vite.config.js", "index.html",
        "src/main.jsx", "src/App.jsx", "src/styles.css", "README.md",
    ],
    install_pipeline=[["npm", "install", "--no-audit", "--no-fund", "--silent"]],
    build_pipeline=[["npx", "vite", "build"]],
    lint_pipeline=[],
    test_pipeline=[],
    start_command=["npx", "vite", "--host", "127.0.0.1", "--port", "{port}"],
    default_port=5175,
    ready_path="/",
    detect={"files": ["package.json", "vite.config.js"]},
    extra_env={"BROWSER": "none"},
))



register(StackConfig(
    id="expo-web-static",
    label="Expo / React Native with standalone web frontend",
    planner_hint=(
        "This is an existing Expo/React Native repository with a standalone web/ "
        "frontend. Preserve the native app and edit only the requested files. "
        "The web frontend is served directly from web/ for browser verification."
    ),
    seed_files=[],
    install_pipeline=[["npm", "install", "--no-audit", "--no-fund", "--silent"]],
    typecheck_pipeline=[["npm", "run", "typecheck", "--if-present"]],
    build_pipeline=[],
    lint_pipeline=[],
    test_pipeline=[],
    start_command=None,
    start_cwd="web",
    default_port=5177,
    ready_path="/",
    detect={"files": ["package.json", "web/index.html"], "package_deps": ["expo"]},
))


register(StackConfig(
    id="node-express",
    label="Node.js (Express)",
    planner_hint=(
        "Use Node.js with Express. Produce package.json, server.js, README.md. "
        "Server must listen on process.env.PORT and serve at least GET / with a small HTML page. "
        "Dependencies: express@^4."
    ),
    seed_files=["package.json", "server.js", "README.md"],
    install_pipeline=[["npm", "install", "--no-audit", "--no-fund", "--silent"]],
    build_pipeline=[],
    lint_pipeline=[],
    test_pipeline=[],
    start_command=["node", "server.js"],
    default_port=3001,
    ready_path="/",
    detect={"files": ["package.json"], "package_deps": ["express"]},
))


register(StackConfig(
    id="fastapi",
    label="Python + FastAPI",
    planner_hint=(
        "Use Python 3.11 with FastAPI and uvicorn. Produce main.py, requirements.txt, "
        "README.md, and a static/index.html served from main.py's StaticFiles mount. "
        "The app must respond 200 on GET / with the static/index.html page. "
        "Dependencies (requirements.txt): fastapi>=0.110, uvicorn>=0.25."
    ),
    seed_files=["main.py", "requirements.txt", "static/index.html", "README.md"],
    install_pipeline=[["pip", "install", "--quiet", "-r", "requirements.txt"]],
    build_pipeline=[],
    typecheck_pipeline=[],
    lint_pipeline=[],
    test_pipeline=[],
    start_command=["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "{port}"],
    default_port=8010,
    ready_path="/",
    detect={"files": ["requirements.txt", "main.py"], "requirements_deps": ["fastapi"]},
))


register(StackConfig(
    id="react-vite-fastapi",
    label="React + Vite frontend + FastAPI backend",
    planner_hint=(
        "Full stack. Frontend: React+Vite in frontend/ (as in the react-vite stack). "
        "Backend: FastAPI in backend/ (main.py, requirements.txt). "
        "Frontend calls backend at /api/* — Vite dev proxy proxies /api to the backend port. "
        "Verify URL is the frontend URL; the backend must be running before verification."
    ),
    seed_files=[
        "backend/main.py", "backend/requirements.txt",
        "frontend/package.json", "frontend/vite.config.js", "frontend/index.html",
        "frontend/src/main.jsx", "frontend/src/App.jsx", "frontend/src/styles.css",
        "README.md",
    ],
    install_pipeline=[
        ["pip", "install", "--quiet", "-r", "backend/requirements.txt"],
        ["npm", "install", "--no-audit", "--no-fund", "--silent", "--prefix", "frontend"],
    ],
    build_pipeline=[["npx", "--prefix", "frontend", "vite", "build"]],
    start_command=["npx", "vite", "--host", "127.0.0.1", "--port", "{port}"],
    start_cwd="frontend",
    default_port=5176,
    ready_path="/",
    detect={
        "files": ["frontend/package.json", "backend/main.py"],
    },
    services=[
        ServiceDefinition(
            name="backend",
            start_command=["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "{port}"],
            start_cwd="backend",
            port_env="PORT",
            default_port=8000,
            ready_path="/",
            ready_timeout=35.0,
        ),
        ServiceDefinition(
            name="frontend",
            start_command=["npx", "vite", "--host", "127.0.0.1", "--port", "{port}"],
            start_cwd="frontend",
            port_env="PORT",
            default_port=5176,
            ready_path="/",
            ready_timeout=35.0,
            extra_env={"BROWSER": "none", "VITE_API_URL": "http://127.0.0.1:{backend_port}", "BACKEND_PORT": "{backend_port}"},
        ),
    ],
    verify_service="frontend",
))


register(StackConfig(
    id="nextjs",
    label="Next.js (App Router)",
    planner_hint=(
        "Use Next.js 14 with the App Router and JavaScript (no TypeScript). "
        "Produce: package.json, next.config.mjs, app/layout.jsx, app/page.jsx, "
        "app/globals.css, README.md. Do NOT introduce Tailwind, TypeScript, or "
        "extra libraries. Dependencies: next@^14, react@^18, react-dom@^18."
    ),
    seed_files=[
        "package.json", "next.config.mjs",
        "app/layout.jsx", "app/page.jsx", "app/globals.css", "README.md",
    ],
    install_pipeline=[["npm", "install", "--no-audit", "--no-fund", "--silent"]],
    build_pipeline=[["npx", "next", "build"]],
    start_command=["npx", "next", "dev", "--hostname", "127.0.0.1", "--port", "{port}"],
    default_port=3010,
    ready_path="/",
    detect={"files": ["next.config.mjs", "next.config.js"], "package_deps": ["next"]},
    extra_env={"BROWSER": "none", "NEXT_TELEMETRY_DISABLED": "1"},
))


register(StackConfig(
    id="flask",
    label="Python + Flask",
    planner_hint=(
        "Use Python 3.11 with Flask. Produce app.py, requirements.txt, "
        "templates/index.html, README.md. App must respond 200 on GET / with "
        "the templates/index.html page. Dependencies (requirements.txt): flask>=3.0."
    ),
    seed_files=["app.py", "requirements.txt", "templates/index.html", "README.md"],
    install_pipeline=[["pip", "install", "--quiet", "-r", "requirements.txt"]],
    build_pipeline=[],
    start_command=["python", "-m", "flask", "--app", "app", "run",
                   "--host", "127.0.0.1", "--port", "{port}"],
    default_port=5010,
    ready_path="/",
    detect={"files": ["app.py", "requirements.txt"], "requirements_deps": ["flask"]},
    extra_env={"FLASK_DEBUG": "0"},
))


register(StackConfig(
    id="django",
    label="Python + Django (single-app project)",
    planner_hint=(
        "Use Django 5 with a single project named `site_app` and a single app "
        "named `main`. Produce: manage.py, site_app/settings.py (DEBUG=True, "
        "ALLOWED_HOSTS=['*'], SECRET_KEY='dev'), site_app/urls.py, "
        "site_app/asgi.py or wsgi.py, main/apps.py, main/urls.py, main/views.py, "
        "main/templates/main/index.html, requirements.txt, README.md. "
        "Do NOT depend on a database beyond SQLite. Dependencies: django>=5.0."
    ),
    seed_files=[
        "manage.py", "requirements.txt",
        "site_app/__init__.py", "site_app/settings.py", "site_app/urls.py",
        "site_app/wsgi.py",
        "main/__init__.py", "main/apps.py", "main/urls.py", "main/views.py",
        "main/templates/main/index.html",
        "README.md",
    ],
    install_pipeline=[["pip", "install", "--quiet", "-r", "requirements.txt"]],
    build_pipeline=[],
    start_command=["python", "manage.py", "runserver", "127.0.0.1:{port}",
                   "--noreload"],
    default_port=8020,
    ready_path="/",
    detect={"files": ["manage.py"], "requirements_deps": ["django"]},
))


def get_stack(stack_id: str) -> StackConfig:
    if stack_id not in STACKS:
        return STACKS["html-static"]
    return STACKS[stack_id]


def list_stacks() -> List[StackConfig]:
    return list(STACKS.values())


def detect_stack(project_root) -> str:
    """Best-effort stack detection given a project directory."""
    from pathlib import Path
    root = Path(project_root)
    if not root.exists():
        return "html-static"

    def has(p: str) -> bool:
        return (root / p).exists()

    if has("next.config.mjs") or has("next.config.js"):
        return "nextjs"
    if has("manage.py"):
        return "django"
    # Full-stack combo before generic frontend checks. Gold Builder and other
    # FastAPI repos commonly use backend/server.py rather than backend/main.py.
    # Missing that shape misclassifies the repository as a frontend-only stack,
    # so installs/builds run from the wrong directory.
    if has("frontend/package.json") and (
        has("backend/main.py")
        or has("backend/server.py")
        or has("backend/requirements.txt")
    ):
        return "react-vite-fastapi"
    # Existing React frontends may be Create React App/CRACO rather than Vite.
    # Keep them out of the root-level generic Node fallback.
    if has("frontend/package.json"):
        return "react-vite"
    if has("vite.config.js") or has("vite.config.ts"):
        return "react-vite"
    if has("package.json"):
        try:
            import json
            pkg = json.loads((root / "package.json").read_text())
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "next" in deps:
                return "nextjs"
            if "vite" in deps:
                return "react-vite"
            if "expo" in deps and has("web/index.html"):
                return "expo-web-static"
            if "express" in deps:
                return "node-express"
        except Exception:  # noqa: BLE001
            pass
        return "node-express"
    if has("requirements.txt"):
        try:
            reqs = (root / "requirements.txt").read_text().lower()
            if "fastapi" in reqs:
                return "fastapi"
            if "django" in reqs:
                return "django"
            if "flask" in reqs:
                return "flask"
        except Exception:  # noqa: BLE001
            pass
    if has("app.py"):
        # heuristic — treat as flask
        return "flask"
    if has("index.html"):
        return "html-static"
    return "html-static"
