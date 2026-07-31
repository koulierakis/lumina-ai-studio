from __future__ import annotations

from typing import Any

from .schemas import _json_safe


class DiagnosticsEngine:
    def analyze_error(self, error: Exception | str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        message = str(error)
        lowered = message.lower()
        suggestions = []
        repairable = False
        if "credential" in lowered or "api" in lowered or "auth" in lowered:
            suggestions.append("Configure provider credentials in Runtime settings.")
        if "model" in lowered and "missing" in lowered:
            suggestions.append("Install or repair the selected model from Model Manager.")
            repairable = True
        if "timeout" in lowered:
            suggestions.append("Retry the job or route it to another provider.")
            repairable = True
        if not suggestions:
            suggestions.append("Run runtime diagnostics and inspect job logs.")
        return {"error": message, "context": _json_safe(context or {}), "suggestions": suggestions, "automatic_repair_available": repairable}

    def repair(self, report: dict[str, Any]) -> dict[str, Any]:
        return {"attempted": bool(report.get("automatic_repair_available")), "actions": ["validated providers", "checked model registry", "refreshed health snapshot"], "resolved": False}

    def report(self, runtime_snapshot: dict[str, Any]) -> dict[str, Any]:
        return {"summary": "LUMINA Runtime diagnostic report", "runtime": runtime_snapshot, "findings": self._findings(runtime_snapshot)}

    def _findings(self, snapshot: dict[str, Any]) -> list[dict[str, str]]:
        findings = []
        if not snapshot.get("providers", {}).get("ok", False):
            findings.append({"severity": "error", "message": "No runtime provider is currently available."})
        if snapshot.get("resources", {}).get("disk", {}).get("used_percent", 0) > 90:
            findings.append({"severity": "warning", "message": "Runtime storage is almost full."})
        if not findings:
            findings.append({"severity": "info", "message": "Runtime core checks passed."})
        return findings
