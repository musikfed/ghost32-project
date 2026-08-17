from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .device_client import DeviceError, client
from .device_snapshot import collect_device_files
from .secret_scrubber import scrub_files

PublishValue = str | bytes

# EN: Keep the repository complete while excluding dependencies, VCS metadata, caches/local state and secrets.
# RU: Репозиторий полный, кроме зависимостей, метаданных VCS, кэшей/локального состояния и секретов.
BLOCKED_DIRS={".git",".venv","node_modules","__pycache__",".pytest_cache",".mypy_cache",".ruff_cache"}
BLOCKED_BASENAMES={".env",".env.local",".env.production","config.json","credentials.json","secrets.json",".studio-state.json"}
BLOCKED_SUFFIXES={".key",".pem",".p12",".pfx",".sqlite",".sqlite3",".db",".log",".pyc",".bak"}
TEXT_SUFFIXES={"",".py",".pyi",".js",".jsx",".ts",".tsx",".css",".html",".json",".md",".txt",".toml",".yaml",".yml",".ini",".cfg",".cmd",".bat",".ps1",".sh",".gitignore",".lock"}
MAX_LOCAL_FILE_BYTES=32*1024*1024
MAX_TOTAL_BYTES=50*1024*1024
MAX_LOCAL_FILES=1500

def _path_block_reason(relative: Path) -> str|None:
    parts=[p.lower() for p in relative.parts]
    if any(p in BLOCKED_DIRS for p in parts[:-1]): return "dependency/cache/VCS directory"
    base=relative.name.lower()
    if base in BLOCKED_BASENAMES or base.startswith(".env."): return "secret/config filename"
    if any(base.endswith(s) for s in BLOCKED_SUFFIXES): return "credential/local-state artifact"
    return None

def _read_publish_value(path: Path) -> PublishValue:
    suffix=path.suffix.lower()
    if suffix in TEXT_SUFFIXES or path.name in {".gitignore",".python-version","LICENSE"}:
        try: return path.read_text(encoding="utf-8")
        except UnicodeDecodeError: pass
    return path.read_bytes()

def collect_studio_source(root: Path):
    files:dict[str,PublishValue]={}; skipped=[]; total=0
    for current, dirnames, filenames in os.walk(root):
        current_path=Path(current)
        dirnames[:]=[n for n in sorted(dirnames) if n.lower() not in BLOCKED_DIRS]
        for filename in sorted(filenames):
            path=current_path/filename; rel=path.relative_to(root); reason=_path_block_reason(rel)
            if reason: skipped.append({"path":rel.as_posix(),"reason":reason}); continue
            if len(files)>=MAX_LOCAL_FILES: raise RuntimeError("Studio source exceeds file safety limit")
            size=path.stat().st_size
            if size>MAX_LOCAL_FILE_BYTES: skipped.append({"path":rel.as_posix(),"reason":f"too large ({size} bytes)"}); continue
            if total+size>MAX_TOTAL_BYTES: raise RuntimeError("Studio source exceeds 50 MB safety limit")
            files[rel.as_posix()]=_read_publish_value(path); total+=size
    return files, skipped

def _device_manifest()->dict[str,Any]:
    try: info=client.json("GET","/api/info")
    except DeviceError: info={}
    return {"generated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),"board":info.get("board"),"board_id":info.get("board_id"),"chip":info.get("chip"),"device_id":info.get("device_id"),"memory_profile":info.get("memory_profile",{})}

def collect_publish_bundle(root:Path,scope:str):
    scope=(scope or "device").lower()
    if scope not in {"device","full"}: raise ValueError("scope must be 'device' or 'full'")
    files={}; skipped=[]
    device_files,device_skipped=collect_device_files("/")
    if scope=="device": files.update(device_files)
    else:
        studio_files,studio_skipped=collect_studio_source(root); files.update(studio_files); skipped.extend(studio_skipped)
        for path,text in device_files.items():
            clean=path[len("device/"):] if path.startswith("device/") else path
            files[f"projects/connected-device/{clean}"]=text
    skipped.extend({"path":str(path),"reason":"device secret/binary policy"} for path in device_skipped)
    manifest={"generated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),"scope":scope,"device":_device_manifest(),"skipped":skipped,"security_note":"Secret Scrubber runs before cloud publication. Dependencies/VCS metadata, local databases/logs and credential files are excluded; built frontend and firmware binaries are included when present."}
    files["studio/publish-manifest.json"]=json.dumps(manifest,ensure_ascii=False,indent=2)+"\n"
    return files,manifest

def _payload_size(v:PublishValue)->int: return len(v.encode("utf-8")) if isinstance(v,str) else len(v)

def prepare_publish_bundle(root:Path,scope:str,dynamic_secrets:list[str]|tuple[str,...]=()):
    files,manifest=collect_publish_bundle(root,scope); cleaned,scrub_report=scrub_files(files,dynamic_secrets=dynamic_secrets)
    report={"scope":scope,"files":len(cleaned),"bytes":sum(_payload_size(v) for v in cleaned.values()),"skipped":manifest.get("skipped",[]),"skipped_count":len(manifest.get("skipped",[])),"scrubber":scrub_report,"includes":{"connected_device":True,"react_frontend":scope=="full","react_dist":scope=="full","python_host":scope=="full","micropython_runtime_source":scope=="full","board_profiles":scope=="full","firmware_binaries":scope=="full","windows_scripts":scope=="full","linux_scripts":scope=="full","docs_ru_en":scope=="full"}}
    return cleaned,report
