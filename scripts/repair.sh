#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
# EN: Repair local dependencies only. / RU: Чиним только локальные зависимости.
command -v uv >/dev/null 2>&1 || { echo "ERROR: uv missing" >&2; exit 1; }
uv venv --python 3.13 .venv; uv sync
"$ROOT/.venv/bin/python" -c "import fastapi,httpx,serial,esptool,mpremote; print('Python tools: OK')"
(cd "$ROOT/frontend" && npm install --no-audit --no-fund && npm run build)
