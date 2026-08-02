from __future__ import annotations

import ast
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "docs" / "generated"
SKIP = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "backups",
    "runtime",
    "__pycache__",
}
CODE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx"}


def eligible(path: Path) -> bool:
    return (
        path.is_file()
        and path.suffix.lower() in CODE_EXTENSIONS
        and not any(part in SKIP for part in path.parts)
    )


def python_imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError):
        return set()
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    return imports


def javascript_imports(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set()
    matches = re.findall(r"(?:from\s+|require\()['\"]([^'\"]+)", text)
    return {
        item.split("/")[0] if not item.startswith("@") else "/".join(item.split("/")[:2])
        for item in matches
    }


def main() -> None:
    files = sorted(path for path in ROOT.rglob("*") if eligible(path))
    by_extension = Counter(path.suffix.lower() for path in files)
    by_area = Counter(path.relative_to(ROOT).parts[0] for path in files)
    dependencies = Counter()
    largest = sorted(files, key=lambda p: p.stat().st_size, reverse=True)[:25]

    for path in files:
        imports = python_imports(path) if path.suffix == ".py" else javascript_imports(path)
        dependencies.update(imports)

    generated = datetime.now(UTC).isoformat()
    payload = {
        "generated_at": generated,
        "total_code_files": len(files),
        "files_by_extension": dict(by_extension),
        "files_by_area": dict(by_area),
        "top_dependencies": dependencies.most_common(50),
        "largest_files": [
            {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size}
            for path in largest
        ],
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "architecture-inventory.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )

    lines = [
        "# LUMINA Architecture Inventory",
        "",
        f"Generated: `{generated}`",
        "",
        f"Total code files: **{len(files)}**",
        "",
        "## Code areas",
        "",
        "| Area | Files |",
        "|---|---:|",
    ]
    lines.extend(f"| `{area}` | {count} |" for area, count in by_area.most_common())
    lines += ["", "## Languages", "", "| Extension | Files |", "|---|---:|"]
    lines.extend(f"| `{extension}` | {count} |" for extension, count in by_extension.most_common())
    lines += [
        "",
        "## Most referenced dependencies",
        "",
        "| Dependency | References |",
        "|---|---:|",
    ]
    lines.extend(f"| `{name}` | {count} |" for name, count in dependencies.most_common(30))
    lines += ["", "## Largest code files", "", "| File | Size (KB) |", "|---|---:|"]
    lines.extend(
        f"| `{path.relative_to(ROOT).as_posix()}` | {path.stat().st_size / 1024:.1f} |"
        for path in largest
    )
    lines += [
        "",
        "## High-level system map",
        "",
        "```mermaid",
        "flowchart LR",
        "  UI[React Frontend] --> API[FastAPI Backend]",
        "  API --> STORAGE[Persistence / Storage]",
        "  API --> AI[AI Providers and Pipelines]",
        "  DEV[Developer Tooling] --> API",
        "  DEV --> UI",
        "  MEMORY[Qdrant Repository Memory] --> DEV",
        "  OLLAMA[Ollama Local Models] --> MEMORY",
        "  REDIS[Redis] --> API",
        "  POSTGRES[PostgreSQL] --> STORAGE",
        "  MINIO[MinIO] --> STORAGE",
        "```",
        "",
    ]
    (OUTPUT_DIR / "architecture-inventory.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Generated {OUTPUT_DIR / 'architecture-inventory.md'}")
    print(f"Generated {OUTPUT_DIR / 'architecture-inventory.json'}")


if __name__ == "__main__":
    main()
