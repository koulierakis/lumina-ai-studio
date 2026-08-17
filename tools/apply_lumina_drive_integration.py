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
        "from ai_runtime.schemas import RuntimeJob, RuntimeJobStatus  # noqa: E402\nfrom lumina_drive import router as lumina_drive_router  # noqa: E402\n",
        "Drive import",
    )
    text = replace_once(
        text,
        "app.include_router(runtime_router)\n",
        "app.include_router(runtime_router)\napp.include_router(lumina_drive_router)\n",
        "Drive router include",
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
        "import DocumentStudio from './pages/DocumentStudio';\nimport LuminaDrive from './pages/LuminaDrive';\n",
        "Drive page import",
    )
    text = replace_once(
        text,
        '              <Route path="documents" element={<DocumentStudio />} />\n',
        '              <Route path="documents" element={<DocumentStudio />} />\n              <Route path="drive" element={<LuminaDrive />} />\n',
        "Drive route",
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
        "  Wand2,\n  Navigation,\n} from 'lucide-react';",
        "Navigation icon import",
    )
    anchor = "  {\n    id: 'gallery',\n"
    block = "  {\n    id: 'drive',\n    name: 'LUMINA Drive',\n    route: '/studio/drive',\n    icon: Navigation,\n    status: 'beta',\n    completion: 55,\n    visible: true,\n    navigationOrder: 9,\n  },\n  {\n    id: 'gallery',\n"
    text = replace_once(text, anchor, block, "Drive registry entry")
    if text != original:
        REGISTRY.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> None:
    server = patch_server()
    app = patch_app()
    registry = patch_registry()
    print("LUMINA DRIVE INTEGRATION APPLIED")
    print(f"backend/server.py: {'updated' if server else 'already installed'}")
    print(f"frontend/src/App.js: {'updated' if app else 'already installed'}")
    print(f"frontend/src/platform/moduleRegistry.js: {'updated' if registry else 'already installed'}")


if __name__ == "__main__":
    main()
