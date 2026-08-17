#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"; PY="$ROOT/.venv/bin/python"
# EN: Use the exact .venv interpreter; activation is not required.
# RU: Используем Python прямо из .venv; активация окружения не нужна.
[[ -x "$PY" ]] || "$ROOT/scripts/bootstrap.sh"
[[ -f "$ROOT/frontend/dist/index.html" ]] || (cd "$ROOT/frontend" && npm install --no-audit --no-fund && npm run build)
exec "$PY" -m host.app
