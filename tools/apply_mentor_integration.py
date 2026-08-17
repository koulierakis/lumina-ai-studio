from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "backend" / "server.py"
APP = ROOT / "frontend" / "src" / "App.js"
REGISTRY = ROOT / "frontend" / "src" / "platform" / "moduleRegistry.js"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"Could not find {label} anchor")
    return text.replace(old, new, 1)


def patch_server() -> bool:
    text = SERVER.read_text(encoding="utf-8")
    original = text
    text = replace_once(
        text,
        "from ai_runtime.schemas import RuntimeJob, RuntimeJobStatus  # noqa: E402\n",
        "from ai_runtime.schemas import RuntimeJob, RuntimeJobStatus  # noqa: E402\nfrom mentor import configure_mentor, router as mentor_router  # noqa: E402\n",
        "Mentor import",
    )
    text = replace_once(
        text,
        'notifications_coll = LocalPersistenceCollection(persistence_provider, "notifications")\n',
        'notifications_coll = LocalPersistenceCollection(persistence_provider, "notifications")\nmentor_sessions_coll = LocalPersistenceCollection(persistence_provider, "mentor_sessions")\n',
        "Mentor collection",
    )
    text = replace_once(
        text,
        "configure_document_studio_router(persistence_provider, media_coll, notifications_coll)\n",
        "configure_document_studio_router(persistence_provider, media_coll, notifications_coll)\nconfigure_mentor(sessions_collection=mentor_sessions_coll, model=str(runtime_config[\"preferred_ollama_model\"]))\n",
        "Mentor configuration",
    )
    text = replace_once(
        text,
        "app.include_router(runtime_router)\n",
        "app.include_router(runtime_router)\napp.include_router(mentor_router)\n",
        "Mentor router include",
    )
    if text != original:
        SERVER.write_text(text, encoding="utf-8")
        return True
    return False


def patch_app() -> bool:
    text = APP.read_text(encoding="utf-8")
    original = text
    text = replace_once(
        text,
        "import DocumentStudio from './pages/DocumentStudio';\n",
        "import DocumentStudio from './pages/DocumentStudio';\nimport Mentor from './pages/Mentor';\n",
        "Mentor page import",
    )
    text = replace_once(
        text,
        '              <Route path="documents" element={<DocumentStudio />} />\n',
        '              <Route path="documents" element={<DocumentStudio />} />\n              <Route path="mentor" element={<Mentor />} />\n',
        "Mentor route",
    )
    if text != original:
        APP.write_text(text, encoding="utf-8")
        return True
    return False


def patch_registry() -> bool:
    text = REGISTRY.read_text(encoding="utf-8")
    original = text
    text = replace_once(
        text,
        "  Wand2,\n} from 'lucide-react';",
        "  Wand2,\n  Brain,\n} from 'lucide-react';",
        "Brain icon import",
    )
    anchor = "  {\n    id: 'gallery',\n"
    block = "  {\n    id: 'mentor',\n    name: 'Mentor',\n    route: '/studio/mentor',\n    icon: Brain,\n    status: 'ready',\n    completion: 90,\n    visible: true,\n    navigationOrder: 9,\n  },\n  {\n    id: 'gallery',\n"
    text = replace_once(text, anchor, block, "Mentor registry entry")
    text = text.replace("navigationOrder: 9,\n  },\n  {\n    id: 'jobs'", "navigationOrder: 10,\n  },\n  {\n    id: 'jobs'", 1)
    text = text.replace("navigationOrder: 10,\n  },\n  {\n    id: 'notifications'", "navigationOrder: 11,\n  },\n  {\n    id: 'notifications'", 1)
    text = text.replace("navigationOrder: 11,\n  },\n  {\n    id: 'projects'", "navigationOrder: 12,\n  },\n  {\n    id: 'projects'", 1)
    text = text.replace("navigationOrder: 12,\n  },\n  {\n    id: 'settings'", "navigationOrder: 13,\n  },\n  {\n    id: 'settings'", 1)
    text = text.replace("navigationOrder: 13,\n  },\n];", "navigationOrder: 14,\n  },\n];", 1)
    if text != original:
        REGISTRY.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> None:
    server = patch_server()
    app = patch_app()
    registry = patch_registry()
    print("MENTOR INTEGRATION APPLIED")
    print(f"backend/server.py: {'updated' if server else 'already installed'}")
    print(f"frontend/src/App.js: {'updated' if app else 'already installed'}")
    print(f"frontend/src/platform/moduleRegistry.js: {'updated' if registry else 'already installed'}")


if __name__ == "__main__":
    main()
