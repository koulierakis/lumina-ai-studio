#!/usr/bin/env bash
set -euo pipefail
ROOT="/workspaces/lumina-ai-studio"
STATE="$ROOT/.lumina-codespace"
mkdir -p "$STATE/logs"

: "${LUMINA_MOBILE_OWNER_EMAIL:?Missing Codespaces secret LUMINA_MOBILE_OWNER_EMAIL}"
: "${LUMINA_MOBILE_OWNER_PASSWORD:?Missing Codespaces secret LUMINA_MOBILE_OWNER_PASSWORD}"
: "${LUMINA_MOBILE_JWT_SECRET:?Missing Codespaces secret LUMINA_MOBILE_JWT_SECRET}"

export OWNER_EMAIL="$LUMINA_MOBILE_OWNER_EMAIL"
export OWNER_PASSWORD="$LUMINA_MOBILE_OWNER_PASSWORD"
export JWT_SECRET="$LUMINA_MOBILE_JWT_SECRET"
export LUMINA_LOCAL_PASSWORDLESS=0
export LUMINA_TAILSCALE_PASSWORDLESS=0
export LUMINA_DATABASE_PROVIDER=sqlite
export CODE_MODEL=qwen2.5-coder:1.5b
export OLLAMA_URL=http://127.0.0.1:11434
export OLLAMA_HOST=http://127.0.0.1:11434
export CORS_ORIGIN_REGEX='^https://[a-zA-Z0-9-]+-3000\.app\.github\.dev$'
export BROWSER=none
export HOST=0.0.0.0
export PORT=3000
export WDS_SOCKET_PORT=0

if ! pgrep -f "ollama serve" >/dev/null 2>&1; then
  nohup ollama serve >"$STATE/logs/ollama.log" 2>&1 &
fi
for _ in $(seq 1 90); do
  curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS http://127.0.0.1:11434/api/tags >/dev/null

cd "$ROOT/backend"
nohup python -m uvicorn server:app --host 127.0.0.1 --port 8000 >"$STATE/logs/backend.log" 2>&1 &
for _ in $(seq 1 120); do
  curl -fsS http://127.0.0.1:8000/api/code-builder/health >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS http://127.0.0.1:8000/api/code-builder/health >"$STATE/backend-health.json"

cd "$ROOT/frontend"
nohup npm start >"$STATE/logs/frontend.log" 2>&1 &
for _ in $(seq 1 180); do
  curl -fsS http://127.0.0.1:3000/ >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS http://127.0.0.1:3000/ >/dev/null

gh codespace ports visibility 3000:public -c "$CODESPACE_NAME"
gh codespace ports --json sourcePort,browseUrl,visibility -c "$CODESPACE_NAME" >"$STATE/ports.json"
printf 'READY\n' >"$STATE/READY"
