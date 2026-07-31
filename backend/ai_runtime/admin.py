from __future__ import annotations

import json
import sys

from .manager import runtime_manager


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "runtime_report"
    health = runtime_manager.health()
    if action == "runtime_scan":
        payload = {"runtime": health, "scan": "completed"}
    elif action == "runtime_validate_providers":
        payload = runtime_manager.providers.validate()
    elif action == "runtime_repair":
        payload = runtime_manager.diagnostics.repair(runtime_manager.diagnostic_report())
    elif action == "runtime_missing_models":
        models = runtime_manager.models.list()["available_models"]
        payload = {"missing_models": [m for m in models if not m["installed"] and m["provider"] != "cloud"]}
    elif action == "runtime_dependencies":
        payload = {"dependencies": health["services"], "ok": True}
    elif action == "runtime_diagnostics":
        payload = runtime_manager.diagnostic_report()
    else:
        payload = {"report": runtime_manager.diagnostic_report(), "models": runtime_manager.models.export_installed()}
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
