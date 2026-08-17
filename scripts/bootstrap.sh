#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
# EN: Check prerequisites; do not modify the OS automatically.
# RU: Проверяем зависимости, но автоматически ОС не изменяем.
for cmd in uv node npm; do command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: $cmd is required" >&2; exit 1; }; done
echo "[1/4] Python 3.13 .venv"; uv venv --python 3.13 .venv
echo "[2/4] Python dependencies"; uv sync
echo "[3/4] React dependencies"; cd "$ROOT/frontend"; if [[ -f package-lock.json ]]; then npm ci --no-audit --no-fund; else npm install --no-audit --no-fund; fi
echo "[4/4] React build"; npm run build
echo "Setup complete. Run ./START_STUDIO_LINUX.sh"
