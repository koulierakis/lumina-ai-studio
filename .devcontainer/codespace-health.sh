#!/usr/bin/env bash
set -euo pipefail
ROOT="/workspaces/lumina-ai-studio"
STATE="$ROOT/.lumina-codespace"
mkdir -p "$STATE/logs"
rm -f "$STATE/READY" "$STATE/FAILED"
backend_ok=0
for _ in $(seq 1 120); do
  if curl -fsS http://127.0.0.1:8000/api/code-builder/health >/dev/null 2>&1; then backend_ok=1; break; fi
  sleep 1
done
if [ "$backend_ok" -ne 1 ]; then
  echo "backend failed" >"$STATE/FAILED"
  tail -n 200 "$STATE/logs/backend.log" || true
  exit 1
fi
frontend_ok=0
for _ in $(seq 1 180); do
  if curl -fsS http://127.0.0.1:3000/ >/dev/null 2>&1; then frontend_ok=1; break; fi
  sleep 1
done
if [ "$frontend_ok" -ne 1 ]; then
  echo "frontend failed" >"$STATE/FAILED"
  tail -n 200 "$STATE/logs/frontend.log" || true
  exit 1
fi
echo "ready" >"$STATE/READY"
echo "LUMINA runtime ready: http://localhost:3000"
