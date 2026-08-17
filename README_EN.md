# ESP32 MultiBoard Studio 2.5.0 — EN

A local React + FastAPI + MicroPython Studio for ESP32-C3/S3. Version 2.5.0 supports **Windows 11 and Linux**, preserves the proven 2.3.2 Wi‑Fi stack, and publishes the complete project to GitHub/GitLab behind Secret Scrubber.

## Windows setup
Requires Python 3.13, `uv`, Node.js/npm.
```powershell
.\SETUP.cmd
.\START_STUDIO.cmd
```

## Linux setup
Requires Python 3.13, `uv`, Node.js/npm. On Debian/Ubuntu, access to `/dev/ttyACM*`/`/dev/ttyUSB*` commonly requires membership in `dialout`.
```bash
chmod +x SETUP_LINUX.sh START_STUDIO_LINUX.sh REPAIR_ENV_LINUX.sh
./SETUP_LINUX.sh
./START_STUDIO_LINUX.sh
```
Diagnostics:
```bash
./scripts/diagnose.sh
```
Persistent GitHub/GitLab token storage on Linux uses `secret-tool` (usually package `libsecret-tools`). Without it, tokens remain session-only.

## Wi‑Fi baseline
`device/server.py` and `host/device_client.py` in 2.5.0 are kept **byte-for-byte identical to the working 2.3.2 files**. Git/Linux work is intentionally isolated from the proven network path.

## Full Git publication
**Full Studio Source** includes React/FastAPI/MicroPython source, board profiles, Windows/Linux scripts, documentation, `uv.lock`, `package-lock.json`, and — after local setup/build — `frontend/dist`. Firmware `.bin` files are allowed too.

Excluded: `.venv`, `node_modules`, `.git`, Python caches, local SQLite/log files, and credential files. Secret Scrubber also redacts token/password-like values from text payloads. The goal is “the whole reproducible project”, not dependencies, local noise, or secrets.

## Patching
Linux unified diff and PowerShell exact-block replacement are documented in [docs/PATCHING_EN.md](docs/PATCHING_EN.md). Helpers: `tools/apply-patch.sh` and `tools/Replace-Block.ps1`.

## Bilingual comments
New/substantially changed non-trivial code uses paired comments:
```python
# EN: Explain non-trivial behavior.
# RU: Объясняем нетривиальное поведение.
```
See [docs/CODE_STYLE_RU_EN.md](docs/CODE_STYLE_RU_EN.md).

## Port 8765 guard
2.5.0 checks the port before opening the browser. If an older Studio already owns it, the new process aborts with a clear message instead of silently opening the old backend. Override the port with `GHOST32_PORT`.
