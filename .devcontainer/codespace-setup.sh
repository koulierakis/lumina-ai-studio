#!/usr/bin/env bash
set -euo pipefail
ROOT="/workspaces/lumina-ai-studio"
STATE="$ROOT/.lumina-codespace"
mkdir -p "$STATE/logs"
python -m pip install --disable-pip-version-check -r "$ROOT/backend/requirements.txt"
cd "$ROOT/frontend"
npm ci --no-audit --no-fund
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
if ! pgrep -f "ollama serve" >/dev/null 2>&1; then
  nohup ollama serve >"$STATE/logs/ollama.log" 2>&1 &
fi
for _ in $(seq 1 60); do
  curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
  sleep 1
done
ollama pull qwen2.5-coder:1.5b
ollama pull qwen2.5-coder:7b
