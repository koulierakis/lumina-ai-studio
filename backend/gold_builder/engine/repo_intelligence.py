"""Repository Intelligence — contextual mapping and focused file selection.

Constructs a lightweight AST/regex-based context map of the repository:
- routes / endpoints
- components / interactive elements
- schemas / models
- services / utilities
- import dependencies
- configuration & tests

Used by planner, generator, repair, and continuation workflows to select
only relevant file context for LLMs instead of dumping the whole repo.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class RepoContextMap(BaseModel):
    routes: List[str] = Field(default_factory=list)
    components: List[str] = Field(default_factory=list)
    models_schemas: List[str] = Field(default_factory=list)
    services: List[str] = Field(default_factory=list)
    config_files: List[str] = Field(default_factory=list)
    test_files: List[str] = Field(default_factory=list)
    import_graph: Dict[str, List[str]] = Field(default_factory=dict)
    reverse_import_graph: Dict[str, List[str]] = Field(default_factory=dict)
    file_summaries: Dict[str, str] = Field(default_factory=dict)
    all_files: List[str] = Field(default_factory=list)


def build_repo_map(project_dir: Path) -> RepoContextMap:
    """Scan project files and build a structured context map."""
    repo_map = RepoContextMap()
    if not project_dir.is_dir():
        return repo_map

    skip_dirs = {
        ".git", "node_modules", "venv", ".venv", "__pycache__",
        ".pytest_cache", "dist", "build", ".next", ".cache", ".yarn", ".turbo"
    }

    route_pattern = re.compile(
        r"""(?:@(app|router)\.(get|post|put|delete|patch)\s*\(\s*['"]([^'"]+)['"]|"""
        r"""path\s*:\s*['"](/[^'"]*)['"]|"""
        r"""<Route\s+[^>]*path=['"]([^'"]+)['"])""",
        re.IGNORECASE
    )
    import_pattern = re.compile(
        r"""(?:from\s+([.\w]+)\s+import|import\s+([\w.]+)|import\s+.*?\s+from\s+['"]([^'"]+)['"])"""
    )
    component_pattern = re.compile(
        r"""(?:function\s+([A-Z]\w+)|class\s+([A-Z]\w+)|const\s+([A-Z]\w+)\s*=\s*(?:React\.)?(?:memo|forwardRef)?\s*\()"""
    )
    model_pattern = re.compile(
        r"""(?:class\s+([A-Z]\w+)\s*\([^)]*(?:BaseModel|Model|Schema)[^)]*\)|type\s+([A-Z]\w+)\s*=|interface\s+([A-Z]\w+))"""
    )

    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        for file in files:
            if file.startswith("."):
                continue
            full_path = Path(root) / file
            rel_path = full_path.relative_to(project_dir).as_posix()
            repo_map.all_files.append(rel_path)

            lower_name = file.lower()
            if "test" in lower_name or rel_path.startswith("tests/"):
                repo_map.test_files.append(rel_path)
            elif lower_name in ("package.json", "requirements.txt", "pyproject.toml", "tsconfig.json", "vite.config.js", "vite.config.ts", "tailwind.config.js"):
                repo_map.config_files.append(rel_path)

            ext = full_path.suffix.lower()
            if ext in (".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".json", ".md"):
                try:
                    text = full_path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                summary_parts = []

                # Find routes
                for m in route_pattern.finditer(text):
                    path_val = m.group(3) or m.group(4) or m.group(5)
                    if path_val:
                        entry = f"{rel_path}: {path_val}"
                        if entry not in repo_map.routes:
                            repo_map.routes.append(entry)
                        summary_parts.append(f"route:{path_val}")

                # Find components
                for m in component_pattern.finditer(text):
                    comp_name = m.group(1) or m.group(2) or m.group(3)
                    if comp_name and comp_name not in ("App", "Default"):
                        if comp_name not in repo_map.components:
                            repo_map.components.append(comp_name)
                        summary_parts.append(f"comp:{comp_name}")

                # Find models/schemas
                for m in model_pattern.finditer(text):
                    model_name = m.group(1) or m.group(2) or m.group(3)
                    if model_name:
                        if model_name not in repo_map.models_schemas:
                            repo_map.models_schemas.append(model_name)
                        summary_parts.append(f"model:{model_name}")

                # Imports
                imports = []
                for m in import_pattern.finditer(text):
                    imp = m.group(1) or m.group(2) or m.group(3)
                    if imp:
                        imports.append(imp)
                if imports:
                    repo_map.import_graph[rel_path] = imports[:15]
                    for imp in imports:
                        repo_map.reverse_import_graph.setdefault(imp, []).append(rel_path)

                if "service" in lower_name or "api" in lower_name or "client" in lower_name:
                    if rel_path not in repo_map.services:
                        repo_map.services.append(rel_path)

                if summary_parts:
                    repo_map.file_summaries[rel_path] = ", ".join(summary_parts[:6])
                else:
                    lines = text.splitlines()
                    preview = lines[0][:80] if lines else ""
                    repo_map.file_summaries[rel_path] = preview

    return repo_map


def format_repo_architecture_summary(repo_map: RepoContextMap) -> str:
    """Produce a concise architectural summary for planner, inspector, and diagnostic prompts."""
    parts = []
    if repo_map.routes:
        parts.append("Known Endpoints / Routes:")
        for r in repo_map.routes[:12]:
            parts.append(f"  - {r}")
    if repo_map.components:
        parts.append(f"Key UI Components: {', '.join(repo_map.components[:15])}")
    if repo_map.models_schemas:
        parts.append(f"Schemas & Models: {', '.join(repo_map.models_schemas[:15])}")
    if repo_map.services:
        parts.append(f"Services & Clients: {', '.join(repo_map.services[:8])}")
    if repo_map.config_files:
        parts.append(f"Configuration: {', '.join(repo_map.config_files[:6])}")
    if repo_map.test_files:
        parts.append(f"Test Suites: {', '.join(repo_map.test_files[:6])}")
    return "\n".join(parts)


def get_focused_cross_file_context(
    repo_map: RepoContextMap,
    project_dir: Path,
    target_file: str,
    query_or_reason: str = "",
    max_chars: int = 3500,
) -> str:
    """Extract relevant surrounding cross-file context for an LLM modifying target_file."""
    target_clean = target_file.replace("\\", "/")
    direct_imports = repo_map.import_graph.get(target_clean, [])

    # Files that import this target
    dependents = []
    stem = Path(target_clean).stem
    for imp_key, importing_files in repo_map.reverse_import_graph.items():
        if stem in imp_key or target_clean in imp_key:
            dependents.extend(importing_files)
    dependents = list(set(dependents))

    # Relevant schemas & models
    related_schemas = [s for s in repo_map.models_schemas if s.lower() in query_or_reason.lower() or s.lower() in target_clean.lower()]
    # Relevant routes
    related_routes = [r for r in repo_map.routes if target_clean in r or any(term in r.lower() for term in re.findall(r'\w+', query_or_reason.lower()) if len(term) > 3)]
    # Relevant services & utilities
    related_services = [s for s in repo_map.services if stem in s.lower() or any(term in s.lower() for term in re.findall(r'\w+', query_or_reason.lower()) if len(term) > 3)]
    # Relevant tests
    related_tests = [t for t in repo_map.test_files if stem in t.lower() or "test" in target_clean.lower()]

    parts = [
        f"Target File: {target_clean}",
    ]
    if direct_imports:
        parts.append(f"Declared Imports / Dependencies: {', '.join(direct_imports[:8])}")
    if dependents:
        parts.append(f"Files Depending on This: {', '.join(dependents[:6])}")
    if related_schemas:
        parts.append(f"Relevant Schemas / Models / Contracts: {', '.join(related_schemas[:8])}")
    if related_routes:
        parts.append(f"Related Routes / Endpoints: {', '.join(related_routes[:6])}")
    if related_services:
        parts.append(f"Related Services / Utilities: {', '.join(related_services[:4])}")
    if related_tests:
        parts.append(f"Related Test Files: {', '.join(related_tests[:4])}")

    # Pull in short focused snippets from directly imported or dependent files
    relevant_files_to_sample = []
    for f in repo_map.all_files:
        if f == target_clean:
            continue
        f_stem = Path(f).stem
        if any(f_stem == imp or imp.endswith(f_stem) for imp in direct_imports):
            relevant_files_to_sample.append(f)
        elif f in dependents:
            relevant_files_to_sample.append(f)

    sampled_snippets = []
    current_chars = sum(len(p) for p in parts)
    for f in relevant_files_to_sample[:3]:
        p = project_dir / f
        if p.is_file():
            try:
                snippet_text = p.read_text(encoding="utf-8", errors="ignore")
                lines = snippet_text.splitlines()[:40]
                snippet = "\n".join(lines)
                if len(snippet) > 800:
                    snippet = snippet[:800] + "\n... [truncated]"
                sampled_snippets.append(f"--- {f} (context) ---\n{snippet}")
                current_chars += len(snippet)
                if current_chars >= max_chars:
                    break
            except Exception:
                continue

    if sampled_snippets:
        parts.append("Focused Cross-File Snippets:\n" + "\n\n".join(sampled_snippets))

    final_context = "\n".join(parts)
    if len(final_context) > max_chars:
        final_context = final_context[:max_chars] + "\n... [truncated to context bound]"
    return final_context


def select_relevant_context(
    repo_map: RepoContextMap,
    project_dir: Path,
    query_or_error: str,
    max_files: int = 5,
    max_chars_per_file: int = 2500,
) -> Dict[str, str]:
    """Select the most relevant files for an LLM prompt without dumping the whole repo."""
    query_terms = set(re.findall(r"\w+", query_or_error.lower()))
    scores: Dict[str, float] = {}

    for file_path in repo_map.all_files:
        score = 0.0
        path_lower = file_path.lower()

        for term in query_terms:
            if len(term) < 3:
                continue
            if term in path_lower:
                score += 5.0
            summary = repo_map.file_summaries.get(file_path, "").lower()
            if term in summary:
                score += 3.0

        if path_lower.endswith((".py", ".jsx", ".tsx", ".js", ".html")):
            score += 1.0

        if file_path in repo_map.test_files and "test" not in query_terms:
            score -= 2.0
        if file_path in repo_map.config_files and not any(c in query_terms for c in ("config", "package", "requirement")):
            score -= 1.0

        scores[file_path] = score

    sorted_files = sorted(scores.keys(), key=lambda f: scores[f], reverse=True)
    selected = sorted_files[:max_files]

    context: Dict[str, str] = {}
    for f in selected:
        p = project_dir / f
        if p.is_file():
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                if len(content) > max_chars_per_file:
                    content = content[:max_chars_per_file] + "\n... [truncated]"
                context[f] = content
            except Exception:
                continue

    return context
