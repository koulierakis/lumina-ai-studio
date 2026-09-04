#!/usr/bin/env bash
set -euo pipefail
ROOT="/workspaces/lumina-ai-studio"
STATE="$ROOT/.lumina-codespace"
mkdir -p "$STATE/logs"
export OWNER_EMAIL="owner@lumina.local"
export JWT_SECRET="${JWT_SECRET:-lumina-codespace-session-only-change-me}"
export LUMINA_LOCAL_PASSWORDLESS=1
export LUMINA_DATABASE_PROVIDER=sqlite
export CODE_MODEL=qwen2.5-coder:1.5b
export OLLAMA_URL=http://127.0.0.1:11434
export OLLAMA_HOST=http://127.0.0.1:11434
export BROWSER=none
export HOST=0.0.0.0
export WDS_SOCKET_PORT=0
pkill -f "uvicorn server:app" >/dev/null 2>&1 || true
pkill -f "craco start" >/dev/null 2>&1 || true
if ! pgrep -f "ollama serve" >/dev/null 2>&1; then
  nohup ollama serve >"$STATE/logs/ollama.log" 2>&1 &
fi
for _ in $(seq 1 60); do
  curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
  sleep 1
done
cd "$ROOT/backend"
nohup python -m uvicorn server:app --host 127.0.0.1 --port 8000 >"$STATE/logs/backend.log" 2>&1 &
for _ in $(seq 1 90); do
  curl -fsS http://127.0.0.1:8000/api/code-builder/health >/dev/null 2>&1 && break
  sleep 1
done
cd "$ROOT/frontend"
nohup npm start >"$STATE/logs/frontend.log" 2>&1 &
