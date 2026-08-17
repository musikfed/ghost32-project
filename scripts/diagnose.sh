#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
echo "== ESP32 MultiBoard Studio 2.5.0 Linux diagnostics =="; uname -a; id
printf "uv: "; uv --version 2>/dev/null || echo missing
printf "node: "; node --version 2>/dev/null || echo missing
printf "npm: "; npm --version 2>/dev/null || echo missing
printf "python: "; [[ -x .venv/bin/python ]] && .venv/bin/python --version || echo '.venv missing'
echo "Serial:"; ls -l /dev/ttyACM* /dev/ttyUSB* 2>/dev/null || echo 'none detected'
echo "Groups: $(id -nG)"
