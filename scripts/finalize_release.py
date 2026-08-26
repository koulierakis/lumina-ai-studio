from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Expected release patch anchor not found in {path}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_server() -> None:
    path = ROOT / "backend" / "server.py"
    replace_once(
        path,
        "from ai_runtime.schemas import RuntimeJob, RuntimeJobStatus  # noqa: E402\n",
        "from ai_runtime.schemas import RuntimeJob, RuntimeJobStatus  # noqa: E402\n"
        "from productivity_router import (  # noqa: E402\n"
        "    configure_productivity_router,\n"
        "    router as productivity_router,\n"
        "    start_productivity_scheduler,\n"
        "    stop_productivity_scheduler,\n"
        ")\n",
    )
    replace_once(
        path,
        "configure_document_studio_router(persistence_provider, media_coll, notifications_coll)\n",
        "configure_document_studio_router(persistence_provider, media_coll, notifications_coll)\n"
        "configure_productivity_router(persistence_provider)\n",
    )
    replace_once(
        path,
        "app.include_router(runtime_router)\n",
        "app.include_router(runtime_router)\napp.include_router(productivity_router)\n",
    )
    replace_once(
        path,
        "    _configure_local_first_collections()\n    logger.info(\"Persistence ready: %s\", persistence_provider.diagnostics())\n",
        "    _configure_local_first_collections()\n"
        "    configure_productivity_router(persistence_provider)\n"
        "    start_productivity_scheduler()\n"
        "    logger.info(\"Persistence ready: %s\", persistence_provider.diagnostics())\n",
    )
    replace_once(
        path,
        "@app.on_event(\"shutdown\")\nasync def _shutdown() -> None:\n    return None\n",
        "@app.on_event(\"shutdown\")\nasync def _shutdown() -> None:\n    await stop_productivity_scheduler()\n",
    )


def patch_app() -> None:
    path = ROOT / "frontend" / "src" / "App.js"
    replace_once(
        path,
        "import ComingSoon from './pages/ComingSoon';\n",
        "import ProductivityCenter from './pages/ProductivityCenter';\n",
    )
    replace_once(
        path,
        "              <Route path=\"finance\" element={<Navigate to=\"/studio/advisor\" replace />} />\n"
        "              <Route path=\"research\" element={<ComingSoon title=\"Internet Research\" />} />\n"
        "              <Route path=\"automations\" element={<ComingSoon title=\"Automations\" />} />\n",
        "              <Route path=\"finance\" element={<ProductivityCenter mode=\"finance\" />} />\n"
        "              <Route path=\"research\" element={<ProductivityCenter mode=\"research\" />} />\n"
        "              <Route path=\"automations\" element={<ProductivityCenter mode=\"automations\" />} />\n",
    )


def patch_module_registry() -> None:
    path = ROOT / "frontend" / "src" / "platform" / "moduleRegistry.js"
    text = path.read_text(encoding="utf-8")
    if "id: 'finance'" not in text:
        text = text.replace(
            "  LayoutDashboard,\n",
            "  LayoutDashboard,\n  Landmark,\n  Search,\n  Clock3,\n",
            1,
        )
        anchor = "  {\n    id: 'settings',\n"
        insertion = (
            "  {\n    id: 'finance',\n    name: 'JSA Finance',\n    route: '/studio/finance',\n    icon: Landmark,\n    status: 'ready',\n    completion: 100,\n    visible: true,\n    navigationOrder: 13,\n  },\n"
            "  {\n    id: 'research',\n    name: 'Internet Research',\n    route: '/studio/research',\n    icon: Search,\n    status: 'ready',\n    completion: 100,\n    visible: true,\n    navigationOrder: 14,\n  },\n"
            "  {\n    id: 'automations',\n    name: 'Automations',\n    route: '/studio/automations',\n    icon: Clock3,\n    status: 'ready',\n    completion: 100,\n    visible: true,\n    navigationOrder: 15,\n  },\n"
        )
        if anchor not in text:
            raise RuntimeError("Module registry settings anchor not found")
        text = text.replace(anchor, insertion + anchor, 1)
        text = text.replace("navigationOrder: 13,\n  },\n];", "navigationOrder: 16,\n  },\n];", 1)
        path.write_text(text, encoding="utf-8")


def patch_productivity_styles() -> None:
    path = ROOT / "frontend" / "src" / "pages" / "ProductivityCenter.jsx"
    text = path.read_text(encoding="utf-8")
    text = text.replace("lumina-input", "field")
    path.write_text(text, encoding="utf-8")


def append_status() -> None:
    path = ROOT / "IMPLEMENTATION_STATUS.md"
    text = path.read_text(encoding="utf-8")
    marker = "## Release completion pass (2026-08-12)"
    if marker in text:
        return
    text += (
        "\n\n## Release completion pass (2026-08-12)\n"
        "- Replaced the remaining active-route placeholders with owner-private local modules: JSA Finance, Internet Research and Automations.\n"
        "- Finance provides a persisted multi-currency income/expense ledger with month/year summaries.\n"
        "- Research provides persisted research records plus guarded public HTTP/HTTPS source import with SSRF/local-network blocking and bounded text extraction.\n"
        "- Automations provides persisted once/hourly/daily/weekly notification tasks and a backend scheduler lifecycle tied to Lumina startup/shutdown.\n"
        "- These modules require no paid provider credentials for their core local operation.\n"
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_server()
    patch_app()
    patch_module_registry()
    patch_productivity_styles()
    append_status()
    print("Lumina release patches applied successfully.")


if __name__ == "__main__":
    main()
