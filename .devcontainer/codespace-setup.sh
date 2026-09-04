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
