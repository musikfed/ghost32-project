#!/usr/bin/env bash
set -euo pipefail
P="${1:-}"; [[ -n "$P" ]] || { echo "Usage: $0 change.patch" >&2; exit 2; }
# EN: Validate patch context before changing files. / RU: Сначала проверяем контекст патча.
if command -v git >/dev/null 2>&1; then git apply --check "$P"; git apply "$P"; else patch -p1 --dry-run < "$P"; patch -p1 < "$P"; fi
echo "Patch applied: $P"
