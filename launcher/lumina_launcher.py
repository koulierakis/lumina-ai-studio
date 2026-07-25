#!/usr/bin/env python3
"""LUMINA Runtime Manager CLI.

Usage:
  python lumina_launcher.py start|stop|restart|status|doctor
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running as `python lumina_launcher.py` from launcher/
_LAUNCHER_DIR = Path(__file__).resolve().parent
if str(_LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(_LAUNCHER_DIR))

from lumina.config import load_config  # noqa: E402
from lumina.doctor import run_doctor  # noqa: E402
from lumina.errors import AlreadyRunningError, LauncherError  # noqa: E402
from lumina.logging_util import setup_logging  # noqa: E402
from lumina.paths import find_repo_root  # noqa: E402
from lumina.services import start_all, status_report, stop_all  # noqa: E402


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, default=str))


def cmd_start(_: argparse.Namespace) -> int:
    root = find_repo_root()
    cfg = load_config(root)
    setup_logging(cfg["logging_level"], root)
    try:
        result = start_all(root)
    except AlreadyRunningError as exc:
        print(exc.message)
        return exc.code
    except LauncherError as exc:
        print(f"ERROR: {exc.message}")
        return exc.code
    print("LUMINA started successfully.")
    for warning in result.get("warnings") or []:
        print(f"WARNING: {warning}")
    print(f"Dashboard: http://{cfg['frontend_host']}:{cfg['frontend_port']}/")
    print(f"Backend:   http://{cfg['backend_host']}:{cfg['backend_port']}/api/health")
    return 0


def cmd_stop(_: argparse.Namespace) -> int:
    root = find_repo_root()
    cfg = load_config(root)
    setup_logging(cfg["logging_level"], root)
    try:
        result = stop_all(root)
    except LauncherError as exc:
        print(f"ERROR: {exc.message}")
        return exc.code
    print("LUMINA stop complete (only LUMINA-owned processes were targeted).")
    _print_json(result.get("results") or {})
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    stop_code = cmd_stop(args)
    # stop_code 0 is fine even if nothing was running
    if stop_code not in {0, 2}:
        return stop_code
    return cmd_start(args)


def cmd_status(_: argparse.Namespace) -> int:
    root = find_repo_root()
    cfg = load_config(root)
    setup_logging(cfg["logging_level"], root)
    report = status_report(root)
    _print_json(report)
    return 0 if report.get("backend", {}).get("ok") or not report.get("running") else 0


def cmd_doctor(_: argparse.Namespace) -> int:
    root = find_repo_root()
    cfg = load_config(root)
    setup_logging(cfg["logging_level"], root)
    report = run_doctor(root)
    _print_json(report)
    return 0 if report.get("ok") else 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lumina_launcher", description="LUMINA local runtime manager")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("start", help="Start backend, frontend, and Ollama if needed")
    sub.add_parser("stop", help="Stop only LUMINA-owned processes")
    sub.add_parser("restart", help="Safe stop then start")
    sub.add_parser("status", help="Show backend / frontend / Ollama state")
    sub.add_parser("doctor", help="Diagnose local dependencies and ports")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "start": cmd_start,
        "stop": cmd_stop,
        "restart": cmd_restart,
        "status": cmd_status,
        "doctor": cmd_doctor,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
