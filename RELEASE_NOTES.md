# Release Notes — 2.5.0

## Cross-platform host
- Windows 11 remains supported with `SETUP.cmd` / `START_STUDIO.cmd`.
- Linux adds `SETUP_LINUX.sh`, `START_STUDIO_LINUX.sh`, `REPAIR_ENV_LINUX.sh`, `scripts/diagnose.sh`.
- Linux persistent cloud-token storage uses Secret Service via `secret-tool`; otherwise session-only mode is available.
- Local History/Logs use LocalAppData on Windows and XDG data directories on Linux.

## Wi‑Fi regression guard
The executable contents of `device/server.py` and `host/device_client.py` are unchanged from the user-proven 2.3.2 release. Their SHA256 values are intentionally kept as the network baseline.

## Git publication
Full source collection now allows built `frontend/dist` and firmware `.bin` artifacts when they exist. `.venv`, `node_modules`, `.git`, caches/local databases/logs and secrets stay excluded. Binary files are uploaded to GitHub/GitLab using base64/blob-aware API paths.

## Patching
Added reusable Linux unified-diff helper and PowerShell exact-block replacement helper with validation/backups.

## Startup safety
Studio checks port 8765 before opening the browser, preventing accidental use of an older backend that is still running.

## Code comments
New/substantially changed non-trivial comments follow paired `EN` / `RU` convention.
