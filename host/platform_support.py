from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

APP_DIR_NAME = "ESP32MultiBoardStudio"

def data_dir() -> Path:
    """EN: Per-user state path. RU: Каталог состояния текущего пользователя."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        target = base / APP_DIR_NAME
    else:
        xdg = os.environ.get("XDG_DATA_HOME", "").strip()
        base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
        target = base / "esp32-multiboard-studio"
    target.mkdir(parents=True, exist_ok=True)
    return target

def credential_backend_name() -> str:
    # EN: Linux token persistence uses Secret Service when secret-tool exists.
    # RU: В Linux токены сохраняются через Secret Service, если есть secret-tool.
    if os.name == "nt":
        return "Windows Credential Manager"
    if shutil.which("secret-tool"):
        return "Secret Service (secret-tool)"
    return "Session only (install libsecret-tools for persistence)"

def platform_label() -> str:
    return f"{platform.system()} {platform.release()}".strip()
