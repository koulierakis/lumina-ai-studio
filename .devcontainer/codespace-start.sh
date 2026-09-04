#!/usr/bin/env bash
set -u
ROOT="/workspaces/lumina-ai-studio"
STATE="$ROOT/.lumina-codespace"
mkdir -p "$STATE/logs"
export OWNER_EMAIL="owner@lumina.local"
export JWT_SECRET="lumina-codespace-local-session"
export LUMINA_LOCAL_PASSWORDLESS=1
export LUMINA_TAILSCALE_PASSWORDLESS=0
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
cd "$ROOT/backend"
nohup python -m uvicorn server:app --host 127.0.0.1 --port 8000 >"$STATE/logs/backend.log" 2>&1 &
cd "$ROOT/frontend"
nohup npm start >"$STATE/logs/frontend.log" 2>&1 &
(
  for _ in $(seq 1 90); do
    curl -fsS http://127.0.0.1:3000 >/dev/null 2>&1 && break
    sleep 1
  done
  if command -v gh >/dev/null 2>&1 && [ -n "${CODESPACE_NAME:-}" ]; then
    gh codespace ports visibility 3000:public -c "$CODESPACE_NAME" >>"$STATE/logs/ports.log" 2>&1 || true
  fi
) >/dev/null 2>&1 &
(
  for _ in $(seq 1 90); do
    curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
    sleep 1
  done
  ollama pull qwen2.5-coder:1.5b >>"$STATE/logs/models.log" 2>&1 || true
  ollama pull qwen2.5-coder:7b >>"$STATE/logs/models.log" 2>&1 || true
) >/dev/null 2>&1 &
