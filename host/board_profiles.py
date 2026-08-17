from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "boards" / "profiles"
FIRMWARE_CATALOG_PATH = ROOT / "firmware" / "firmware_catalog.json"


class BoardProfileError(RuntimeError):
    pass


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise BoardProfileError(f"Cannot read {path.name}: {exc}") from exc


def _validate_profile(profile: dict[str, Any], source: Path) -> dict[str, Any]:
    required = ("id", "name", "chip", "firmware_id", "pins")
    missing = [key for key in required if key not in profile]
    if missing:
        raise BoardProfileError(f"{source.name}: missing keys: {', '.join(missing)}")
    if not isinstance(profile["pins"], list):
        raise BoardProfileError(f"{source.name}: pins must be a list")
    profile = dict(profile)
    profile["source_file"] = source.name
    return profile


def profiles() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(PROFILE_DIR.glob("*.json")):
        profile = _validate_profile(_load_json(path), path)
        profile_id = str(profile["id"])
        if profile_id in seen:
            raise BoardProfileError(f"Duplicate profile id: {profile_id}")
        seen.add(profile_id)
        result.append(profile)
    return result


def get_profile(profile_id: str) -> dict[str, Any]:
    for profile in profiles():
        if profile["id"] == profile_id:
            return profile
    raise BoardProfileError(f"Unknown board profile: {profile_id}")


def firmware_catalog() -> dict[str, dict[str, Any]]:
    catalog = _load_json(FIRMWARE_CATALOG_PATH)
    if not isinstance(catalog, dict):
        raise BoardProfileError("firmware_catalog.json must contain an object")
    return catalog


def get_firmware(firmware_id: str) -> dict[str, Any]:
    catalog = firmware_catalog()
    try:
        return dict(catalog[firmware_id])
    except KeyError as exc:
        raise BoardProfileError(f"Unknown firmware id: {firmware_id}") from exc


def compatible_profiles(chip: str, flash_mb: int | None = None) -> list[dict[str, Any]]:
    chip = (chip or "").lower()
    matches = []
    for profile in profiles():
        if str(profile.get("chip", "")).lower() != chip:
            continue
        score = 0
        expected = int((profile.get("memory") or {}).get("flash_mb") or 0)
        if flash_mb and expected:
            if flash_mb == expected:
                score += 20
            elif flash_mb >= expected:
                score += 5
            else:
                score -= 20
        if profile.get("verified"):
            score += 2
        item = dict(profile)
        item["match_score"] = score
        matches.append(item)
    matches.sort(key=lambda p: (-int(p.get("match_score", 0)), str(p.get("name", ""))))
    return matches
