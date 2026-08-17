from __future__ import annotations

from typing import Any

from .device_client import DeviceError, client

# Never upload runtime credentials or transient files.
BLOCKED_BASENAMES = {
    "config.json",
    "secrets.json",
    ".env",
    "wifi.json",
    "credentials.json",
}
BLOCKED_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
MAX_FILE_BYTES = 128 * 1024
MAX_FILES = 200


def publishable_path(path: str) -> bool:
    clean = path.strip()
    if not clean.startswith("/"):
        clean = "/" + clean
    base = clean.rsplit("/", 1)[-1].lower()
    if base in BLOCKED_BASENAMES:
        return False
    if any(base.endswith(suffix) for suffix in BLOCKED_SUFFIXES):
        return False
    if "/.studio" in clean.lower() or base.startswith(".secret"):
        return False
    return True


def collect_device_files(path: str = "/") -> tuple[dict[str, str], list[str]]:
    files: dict[str, str] = {}
    skipped: list[str] = []

    def walk(folder: str) -> None:
        if len(files) >= MAX_FILES:
            raise DeviceError(f"Device snapshot exceeds {MAX_FILES} file safety limit")
        listing = client.json("GET", "/api/fs/list", params={"path": folder})
        for item in listing.get("items", []):
            child = str(item.get("path") or "")
            if not child:
                continue
            if item.get("directory"):
                if publishable_path(child):
                    walk(child)
                else:
                    skipped.append(child)
                continue
            if not publishable_path(child):
                skipped.append(child)
                continue
            size = int(item.get("size") or 0)
            if size > MAX_FILE_BYTES:
                skipped.append(f"{child} (too large)")
                continue
            response = client.request("GET", "/api/fs", params={"path": child})
            try:
                text = response.content.decode("utf-8")
            except UnicodeDecodeError:
                skipped.append(f"{child} (binary)")
                continue
            files[f"device{child}"] = text

    walk(path)
    return files, skipped
