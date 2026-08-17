from __future__ import annotations

import hashlib
import importlib.metadata as importlib_metadata
import json
import os
import platform
import socket
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .audit_store import clear_events, list_events, record_event
from .board_profiles import BoardProfileError, firmware_catalog, get_profile, profiles
from .cloud_sync import (
    CloudSyncError,
    account_info,
    forget_token,
    load_token,
    publish_snapshot,
    remember_token,
)
from .device_client import DeviceError, client
from .device_snapshot import collect_device_files, publishable_path
from .project_snapshot import prepare_publish_bundle
from .history_store import (
    diff_text,
    get_revision,
    list_revisions,
    record_revision,
    record_snapshot,
    workspace_key,
)
from .jobs import jobs
from .platform_support import credential_backend_name
from .serial_tools import (
    SerialToolError,
    flash_micropython,
    flash_micropython_job,
    install_runtime,
    install_runtime_job,
    ports,
    probe_device,
    probe_device_job,
    read_device_files,
    read_device_files_job,
)

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIST = ROOT / "frontend" / "dist"
FIRMWARE_DIR = ROOT / "firmware"
STUDIO_VERSION = "2.5.0"
STUDIO_HOST = os.environ.get("GHOST32_HOST", "127.0.0.1")
STUDIO_PORT = int(os.environ.get("GHOST32_PORT", "8765"))

app = FastAPI(title="ESP32 MultiBoard Studio", version=STUDIO_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConnectionIn(BaseModel):
    base_url: str = Field(default="http://192.168.4.1", min_length=1, max_length=255)
    token: str = Field(default="", max_length=256)


class PinModeIn(BaseModel):
    mode: str
    force: bool = False


class DigitalWriteIn(BaseModel):
    value: int = Field(ge=0, le=1)


class PwmIn(BaseModel):
    duty_u16: int = Field(ge=0, le=65535)
    frequency: int = Field(default=1000, ge=1, le=1_000_000)


class FileWriteIn(BaseModel):
    path: str = Field(min_length=1, max_length=180)
    content: str = Field(default="", max_length=65536)
    message: str = Field(default="Save from Wi-Fi editor", max_length=200)


class PathIn(BaseModel):
    path: str = Field(min_length=1, max_length=180)


class WifiIn(BaseModel):
    ssid: str = Field(default="", max_length=64)
    password: str = Field(default="", max_length=128)


class SnapshotIn(BaseModel):
    message: str = Field(default="Manual project snapshot", max_length=200)


class SerialProvisionIn(BaseModel):
    port: str = Field(min_length=1, max_length=64)
    profile_id: str = Field(min_length=1, max_length=120)
    ssid: str = Field(default="", max_length=64)
    password: str = Field(default="", max_length=128)
    token: str = Field(min_length=8, max_length=256)


class FlashIn(BaseModel):
    port: str = Field(min_length=1, max_length=64)
    profile_id: str = Field(min_length=1, max_length=120)
    erase: bool = True
    baud: int = Field(default=460800, ge=115200, le=921600)


class PortIn(BaseModel):
    port: str = Field(min_length=1, max_length=64)


class CloudAuthIn(BaseModel):
    provider: str = Field(pattern="^(github|gitlab)$")
    token: str = Field(default="", max_length=1024)
    remember: bool = False


class CloudPublishIn(BaseModel):
    provider: str = Field(pattern="^(github|gitlab)$")
    token: str = Field(default="", max_length=1024)
    remember: bool = False
    repo_name: str = Field(min_length=1, max_length=100)
    private: bool = True
    message: str = Field(default="Update ESP32 snapshot", max_length=240)
    scope: str = Field(default="full", pattern="^(device|full)$")


class CloudScanIn(BaseModel):
    scope: str = Field(default="full", pattern="^(device|full)$")


def device_call(fn: Callable[[], Any]):
    try:
        return fn()
    except DeviceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def serial_call(fn: Callable[[], Any]):
    try:
        return fn()
    except (SerialToolError, BoardProfileError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def current_project() -> dict[str, Any]:
    """Stable project relation for history/logs. Device unique_id wins over DHCP/IP."""
    try:
        info = client.json("GET", "/api/info")
        identity = str(info.get("device_id") or "").strip()
        board = str(info.get("board") or info.get("board_id") or info.get("family") or "ESP32")
        if identity:
            project_id = workspace_key("device:" + identity)
            return {
                "id": project_id,
                "name": board,
                "device_id": identity,
                "board": board,
                "board_id": info.get("board_id", ""),
                "chip": info.get("chip", ""),
                "base_url": client.connection.base_url,
            }
    except DeviceError:
        pass
    base_url = client.connection.base_url or "offline"
    return {
        "id": workspace_key("url:" + base_url),
        "name": base_url,
        "device_id": "",
        "board": "",
        "board_id": "",
        "chip": "",
        "base_url": base_url,
    }


def current_workspace() -> str:
    return str(current_project()["id"])


def _read_device_bytes(path: str) -> bytes | None:
    try:
        return client.request("GET", "/api/fs", params={"path": path}).content
    except DeviceError:
        return None


def _cloud_token(provider: str, supplied: str) -> str:
    token = supplied.strip() or load_token(provider)
    if not token:
        raise CloudSyncError(f"{provider.title()} token is required")
    return token


def _audit(
    source: str,
    action: str,
    message: str,
    *,
    status: str = "ok",
    kind: str = "action",
    severity: str = "info",
    target: str = "",
    detail: str = "",
    context: dict[str, Any] | None = None,
    project: dict[str, Any] | None = None,
    job_id: str = "",
) -> None:
    project = project or current_project()
    record_event(
        kind=kind,
        severity=severity,
        status=status,
        source=source,
        action=action,
        message=message,
        project_id=str(project.get("id") or ""),
        project_name=str(project.get("name") or ""),
        job_id=job_id,
        target=target,
        detail=detail,
        context={**{k: v for k, v in project.items() if k not in {"id", "name"}}, **(context or {})},
    )


def _mutating_device_action(source: str, action: str, target: str, fn: Callable[[], Any], context: dict[str, Any] | None = None):
    project = current_project()
    try:
        result = fn()
        _audit(source, action, f"{action} completed", target=target, context=context, project=project)
        return result
    except DeviceError as exc:
        _audit(source, action, str(exc), status="error", kind="error", severity="error", target=target, context=context, project=project)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _usb_project(port: str, profile_id: str = "") -> tuple[str, str, dict[str, Any]]:
    name = f"USB {port}"
    context: dict[str, Any] = {"port": port}
    if profile_id:
        try:
            profile = get_profile(profile_id)
            name = f"{profile['name']} · {port}"
            context.update({"profile_id": profile_id, "profile_name": profile.get("name", ""), "chip": profile.get("chip", "")})
        except BoardProfileError:
            context["profile_id"] = profile_id
    return workspace_key(f"usb:{port}:{profile_id}"), name, context


@app.get("/api/host/info")
def host_info():
    firmware = []
    for item in firmware_catalog().values():
        path = FIRMWARE_DIR / str(item["filename"])
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""
        firmware.append({**item, "present": path.exists(), "size": path.stat().st_size if path.exists() else 0, "sha256": digest})

    def pkg_version(name: str) -> str:
        try:
            return importlib_metadata.version(name)
        except importlib_metadata.PackageNotFoundError:
            return "missing"

    return {
        "studio_version": STUDIO_VERSION,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "frontend_built": FRONTEND_DIST.exists(),
        "profile_count": len(profiles()),
        "tools": {"esptool": pkg_version("esptool"), "mpremote": pkg_version("mpremote"), "credential_vault": credential_backend_name()},
        "features": {
            "job_progress": True,
            "local_history": True,
            "project_snapshot": True,
            "github": True,
            "gitlab": True,
            "full_source_publish": True,
            "secret_scrubber": True,
            "docs_ru_en": True,
            "linux_host": True,
            "binary_git_publish": True,
            "action_log": True,
            "error_log": True,
        },
        "firmware": firmware,
    }


@app.get("/api/boards")
def board_profiles():
    return {"profiles": profiles()}


@app.post("/api/connection")
def set_connection(payload: ConnectionIn):
    try:
        connection = client.configure(payload.base_url, payload.token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"base_url": connection.base_url, "token_set": bool(connection.token), "workspace": current_workspace(), "project": current_project()}


@app.get("/api/device/status")
def device_status():
    return device_call(lambda: client.json("GET", "/api/status"))


@app.get("/api/device/info")
def device_info():
    return device_call(lambda: client.json("GET", "/api/info"))


@app.get("/api/device/auth")
def device_auth():
    return device_call(lambda: client.json("GET", "/api/auth/check"))


@app.post("/api/device/pins/{gpio}/mode")
def pin_mode(gpio: int, payload: PinModeIn):
    return _mutating_device_action(
        "GPIO", "pin-mode", f"GPIO{gpio}",
        lambda: client.json("POST", f"/api/pins/{gpio}/mode", json=payload.model_dump()),
        {"gpio": gpio, "mode": payload.mode, "force": payload.force},
    )


@app.post("/api/device/pins/{gpio}/write")
def pin_write(gpio: int, payload: DigitalWriteIn):
    return _mutating_device_action(
        "GPIO", "digital-write", f"GPIO{gpio}",
        lambda: client.json("POST", f"/api/pins/{gpio}/write", json=payload.model_dump()),
        {"gpio": gpio, "value": payload.value},
    )


@app.post("/api/device/pins/{gpio}/pwm")
def pin_pwm(gpio: int, payload: PwmIn):
    return _mutating_device_action(
        "GPIO", "pwm-write", f"GPIO{gpio}",
        lambda: client.json("POST", f"/api/pins/{gpio}/pwm", json=payload.model_dump()),
        {"gpio": gpio, "duty_u16": payload.duty_u16, "frequency": payload.frequency},
    )


@app.get("/api/device/fs")
def fs_read(path: str = Query(..., min_length=1, max_length=180)):
    response = device_call(lambda: client.request("GET", "/api/fs", params={"path": path}))
    return Response(response.content, media_type=response.headers.get("content-type", "text/plain"))


@app.get("/api/device/fs/list")
def fs_list(path: str = Query(default="/", max_length=180)):
    return device_call(lambda: client.json("GET", "/api/fs/list", params={"path": path}))


# Synchronous compatibility endpoints; React 2.3 uses job variants below.
@app.put("/api/device/fs")
def fs_write(payload: FileWriteIn):
    workspace = current_workspace()
    project = current_project()
    history_enabled = publishable_path(payload.path)
    try:
        if history_enabled:
            previous = _read_device_bytes(payload.path)
            if previous is not None:
                record_revision(workspace, payload.path, previous, action="baseline", message="Before editor save")
        result = client.json(
            "PUT", "/api/fs", params={"path": payload.path}, content=payload.content.encode("utf-8"),
            headers={"Content-Type": "application/octet-stream"}, timeout=15.0,
        )
        if history_enabled:
            result["revision_id"] = record_revision(workspace, payload.path, payload.content, action="save", message=payload.message)
        else:
            result["history_skipped"] = "Sensitive/config path is excluded from Local History"
        _audit("FILES", "save-file", f"Saved {payload.path}", target=payload.path, project=project)
        return result
    except DeviceError as exc:
        _audit("FILES", "save-file", str(exc), kind="error", severity="error", status="error", target=payload.path, project=project)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.delete("/api/device/fs")
def fs_delete(path: str = Query(..., min_length=1, max_length=180)):
    workspace = current_workspace()
    project = current_project()
    history_enabled = publishable_path(path)
    try:
        if history_enabled:
            previous = _read_device_bytes(path)
            if previous is not None:
                record_revision(workspace, path, previous, action="baseline", message="Before delete")
        result = client.json("DELETE", "/api/fs", params={"path": path})
        if history_enabled:
            result["revision_id"] = record_revision(workspace, path, None, action="delete", message="Deleted from Wi-Fi editor", deleted=True)
        _audit("FILES", "delete-file", f"Deleted {path}", target=path, project=project)
        return result
    except DeviceError as exc:
        _audit("FILES", "delete-file", str(exc), kind="error", severity="error", status="error", target=path, project=project)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/device/wifi")
def wifi_config(payload: WifiIn):
    return _mutating_device_action(
        "WIFI", "wifi-config", payload.ssid or "Wi-Fi",
        lambda: client.json("POST", "/api/wifi", json=payload.model_dump()),
        {"ssid": payload.ssid, "password_present": bool(payload.password)},
    )


@app.post("/api/device/reboot")
def reboot():
    return _mutating_device_action("DEVICE", "reboot", "ESP32", lambda: client.json("POST", "/api/reboot"))


# --------------------------- Local History ---------------------------------

@app.get("/api/history")
def history_list(path: str | None = Query(default=None, max_length=180), limit: int = Query(default=100, ge=1, le=500)):
    project = current_project()
    return {"workspace": project["id"], "project": project, "revisions": list_revisions(project["id"], path, limit)}


@app.get("/api/history/{revision_id}")
def history_get(revision_id: int):
    revision = get_revision(current_workspace(), revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail="Revision not found")
    return revision


@app.get("/api/history/{revision_id}/diff")
def history_diff(revision_id: int):
    revision = get_revision(current_workspace(), revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail="Revision not found")
    if revision.get("binary"):
        raise HTTPException(status_code=400, detail="Binary revision cannot be diffed")
    current = _read_device_bytes(revision["path"])
    try:
        current_text = (current or b"").decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Current file is binary") from exc
    return {"revision": revision, "diff": diff_text(revision.get("content", ""), current_text, revision["path"])}


@app.post("/api/history/{revision_id}/restore")
def history_restore(revision_id: int):
    workspace = current_workspace()
    project = current_project()
    revision = get_revision(workspace, revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail="Revision not found")
    if revision.get("binary"):
        raise HTTPException(status_code=400, detail="Binary revision cannot be restored by Wi-Fi editor")
    path = revision["path"]
    try:
        if revision.get("deleted"):
            result = client.json("DELETE", "/api/fs", params={"path": path})
            record_revision(workspace, path, None, action="restore-delete", message=f"Restore revision #{revision_id}", deleted=True)
            message = f"Restored deleted state for {path}"
        else:
            content = revision.get("content", "")
            result = client.json(
                "PUT", "/api/fs", params={"path": path}, content=content.encode("utf-8"),
                headers={"Content-Type": "application/octet-stream"}, timeout=15.0,
            )
            record_revision(workspace, path, content, action="restore", message=f"Restore revision #{revision_id}")
            message = f"Restored {path} from revision #{revision_id}"
        _audit("HISTORY", "restore", message, target=path, context={"revision_id": revision_id}, project=project)
        return {**result, "message": message}
    except DeviceError as exc:
        _audit("HISTORY", "restore", str(exc), kind="error", severity="error", status="error", target=path, context={"revision_id": revision_id}, project=project)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# --------------------------- Activity / Error log --------------------------

@app.get("/api/activity")
def activity_list(
    scope: str = Query(default="all", pattern="^(all|current)$"),
    kind: str = Query(default="all", pattern="^(all|action|error)$"),
    source: str = Query(default="all", max_length=40),
    limit: int = Query(default=250, ge=1, le=1000),
):
    project = current_project()
    project_id = project["id"] if scope == "current" else None
    return {"current_project": project, "events": list_events(project_id=project_id, kind=kind, source=source, limit=limit)}


@app.delete("/api/activity")
def activity_clear(
    scope: str = Query(default="all", pattern="^(all|current)$"),
    kind: str = Query(default="all", pattern="^(all|action|error)$"),
):
    project = current_project()
    project_id = project["id"] if scope == "current" else None
    deleted = clear_events(project_id=project_id, kind=kind)
    return {"deleted": deleted}


# --------------------------- Cloud Sync ------------------------------------

@app.get("/api/cloud/token-status")
def cloud_token_status(provider: str = Query(pattern="^(github|gitlab)$")):
    return {"provider": provider, "stored": bool(load_token(provider)), "vault": credential_backend_name()}


@app.post("/api/cloud/auth")
def cloud_auth(payload: CloudAuthIn):
    project = current_project()
    try:
        token = _cloud_token(payload.provider, payload.token)
        info = account_info(payload.provider, token)
        if payload.remember and payload.token.strip():
            remember_token(payload.provider, token)
        _audit(payload.provider.upper(), "cloud-auth", f"Authenticated as {info.get('username', '')}", project=project)
        return {**info, "stored": bool(load_token(payload.provider))}
    except CloudSyncError as exc:
        _audit(payload.provider.upper(), "cloud-auth", str(exc), kind="error", severity="error", status="error", project=project)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/cloud/forget")
def cloud_forget(payload: CloudAuthIn):
    forget_token(payload.provider)
    _audit(payload.provider.upper(), "forget-token", f"Credential removed from {credential_backend_name()}")
    return {"provider": payload.provider, "stored": False}


@app.post("/api/cloud/scan")
def cloud_scan(payload: CloudScanIn):
    project = current_project()
    try:
        _files, report = prepare_publish_bundle(ROOT, payload.scope, dynamic_secrets=[client.connection.token])
        _audit("SECURITY", "secret-scan", f"Scanned {report['files']} files; redactions {report['scrubber']['redactions']}", project=project, target=payload.scope)
        return report
    except (DeviceError, RuntimeError, ValueError) as exc:
        _audit("SECURITY", "secret-scan", str(exc), kind="error", severity="error", status="error", project=project, target=payload.scope)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/cloud/publish")
def cloud_publish(payload: CloudPublishIn):
    project = current_project()

    def worker(handle):
        try:
            handle.set_project(project["id"], project["name"], provider=payload.provider, repository=payload.repo_name, scope=payload.scope)
            token = _cloud_token(payload.provider, payload.token)
            if payload.remember and payload.token.strip():
                remember_token(payload.provider, token)

            handle.stage("collect", progress=10, detail="Collecting safe project files")
            files, report = prepare_publish_bundle(
                ROOT, payload.scope, dynamic_secrets=[client.connection.token, payload.token, token]
            )
            handle.stage_done("collect", f"{report['files']} files · {report['skipped_count']} excluded")

            handle.stage("scrub", progress=100, detail=f"{report['scrubber']['redactions']} redaction(s); {report['scrubber']['files_redacted']} file(s) changed")
            handle.stage_done("scrub", "Secret Scrubber passed")

            # Device-only revisions stay useful for rollback; Full Studio source is not written into device history.
            if payload.scope == "device":
                record_snapshot(project["id"], {k: v for k, v in files.items() if k.startswith("device/")}, message=f"Before {payload.provider} publish")

            def progress(stage: str, pct: int, detail: str) -> None:
                if stage == "snapshot":
                    handle.stage_progress("upload", pct, detail)
                else:
                    handle.stage_progress(stage, pct, detail)

            result = publish_snapshot(payload.provider, token, payload.repo_name, payload.private, files, payload.message, progress)
            handle.stage_done("upload", f"{len(files)} scrubbed files")
            result["scope"] = payload.scope
            result["security"] = report
            return result
        except (CloudSyncError, DeviceError, RuntimeError, ValueError) as exc:
            raise RuntimeError(str(exc)) from exc

    return jobs.create(
        "cloud-publish",
        f"Publish to {payload.provider.title()}",
        [("collect", "Collect"), ("scrub", "Secrets"), ("auth", "Token"), ("repo", "Repository"), ("upload", "Upload"), ("commit", "Commit")],
        worker,
        project_id=project["id"],
        project_name=project["name"],
        source=payload.provider.upper(),
        target=payload.repo_name,
        context={"provider": payload.provider, "repository": payload.repo_name, "private": payload.private, "scope": payload.scope, "secret_scrubber": True},
    )


# --------------------------- Serial / compatibility ------------------------

@app.get("/api/serial/ports")
def serial_ports():
    return {"ports": ports()}


@app.get("/api/serial/probe")
def serial_probe(port: str = Query(..., min_length=1, max_length=64)):
    return serial_call(lambda: probe_device(port))


@app.get("/api/serial/files")
def serial_files(port: str):
    return serial_call(lambda: read_device_files(port))


@app.post("/api/serial/install")
def serial_install(payload: SerialProvisionIn):
    return serial_call(lambda: install_runtime(payload.port, payload.profile_id, payload.ssid, payload.password, payload.token))


@app.post("/api/serial/flash")
def serial_flash(payload: FlashIn):
    return serial_call(lambda: flash_micropython(payload.port, payload.profile_id, payload.erase, payload.baud))


# --------------------------- Job endpoints ---------------------------------

@app.post("/api/jobs/connect")
def start_connect(payload: ConnectionIn):
    fallback_project = {"id": workspace_key("url:" + payload.base_url), "name": payload.base_url}

    def worker(handle):
        handle.stage("configure", progress=30, detail=payload.base_url)
        try:
            connection = client.configure(payload.base_url, payload.token)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        handle.stage_done("configure", "Connection configured")

        try:
            handle.stage("auth", progress=None, detail="Checking API token")
            auth = client.json("GET", "/api/auth/check")
            handle.stage_done("auth", "Token accepted")

            handle.stage("info", progress=None, detail="Reading board identity")
            info = client.json("GET", "/api/info")
            project = current_project()
            handle.set_project(project["id"], project["name"], device_id=project.get("device_id", ""), base_url=connection.base_url)
            handle.stage_done("info", str(info.get("board") or info.get("chip") or "ESP32"))

            handle.stage("status", progress=None, detail="Reading runtime status")
            status = client.json("GET", "/api/status")
            handle.stage_done("status", str((status.get("wifi") or {}).get("ip") or "online"))
            return {"message": f"Connected: {info.get('board') or info.get('chip') or 'ESP32'}", "auth": auth, "info": info, "status": status, "project": project}
        except DeviceError as exc:
            raise RuntimeError(str(exc)) from exc

    return jobs.create(
        "connect", "Connect over Wi-Fi",
        [("configure", "URL"), ("auth", "Auth"), ("info", "Board"), ("status", "Status")],
        worker,
        project_id=fallback_project["id"], project_name=fallback_project["name"], source="WIFI", target=payload.base_url,
        context={"base_url": payload.base_url, "token_present": bool(payload.token)},
    )


@app.post("/api/jobs/fs-save")
def start_fs_save(payload: FileWriteIn):
    project = current_project()

    def worker(handle):
        workspace = project["id"]
        history_enabled = publishable_path(payload.path)
        handle.stage("baseline", progress=None, detail="Reading current file")
        previous = _read_device_bytes(payload.path) if history_enabled else None
        if previous is not None:
            record_revision(workspace, payload.path, previous, action="baseline", message="Before editor save")
        handle.stage_done("baseline", "Baseline stored" if previous is not None else "No baseline / excluded")

        handle.stage("write", progress=10, detail=f"Writing {len(payload.content.encode('utf-8'))} bytes")
        try:
            result = client.json(
                "PUT", "/api/fs", params={"path": payload.path}, content=payload.content.encode("utf-8"),
                headers={"Content-Type": "application/octet-stream"}, timeout=15.0,
            )
        except DeviceError as exc:
            raise RuntimeError(str(exc)) from exc
        handle.stage_done("write", "File written")

        handle.stage("verify", progress=None, detail="Reading file back")
        verify = _read_device_bytes(payload.path)
        if verify is None or verify != payload.content.encode("utf-8"):
            raise RuntimeError("Save verify failed: device content differs from editor")
        handle.stage_done("verify", "Content verified")

        handle.stage("version", progress=50, detail="Creating Local History revision")
        if history_enabled:
            result["revision_id"] = record_revision(workspace, payload.path, payload.content, action="save", message=payload.message)
            handle.stage_done("version", f"Revision #{result['revision_id']}" if result.get("revision_id") else "No changes")
        else:
            result["history_skipped"] = "Sensitive/config path is excluded from Local History"
            handle.stage_done("version", "Excluded by security policy")
        result["message"] = f"Saved {payload.path}"
        return result

    return jobs.create(
        "save-file", f"Save {payload.path}",
        [("baseline", "Baseline"), ("write", "Write"), ("verify", "Verify"), ("version", "Version")],
        worker,
        project_id=project["id"], project_name=project["name"], source="FILES", target=payload.path,
        context={"path": payload.path, "bytes": len(payload.content.encode("utf-8"))},
    )


@app.post("/api/jobs/fs-delete")
def start_fs_delete(payload: PathIn):
    project = current_project()

    def worker(handle):
        history_enabled = publishable_path(payload.path)
        handle.stage("baseline", progress=None, detail="Saving current content")
        previous = _read_device_bytes(payload.path) if history_enabled else None
        if previous is not None:
            record_revision(project["id"], payload.path, previous, action="baseline", message="Before delete")
        handle.stage_done("baseline", "Baseline stored" if previous is not None else "No baseline / excluded")
        handle.stage("delete", progress=None, detail=payload.path)
        try:
            result = client.json("DELETE", "/api/fs", params={"path": payload.path})
        except DeviceError as exc:
            raise RuntimeError(str(exc)) from exc
        handle.stage_done("delete", "Deleted")
        handle.stage("version", progress=50, detail="Recording deleted state")
        if history_enabled:
            result["revision_id"] = record_revision(project["id"], payload.path, None, action="delete", message="Deleted from Wi-Fi editor", deleted=True)
        handle.stage_done("version", "Delete version stored" if history_enabled else "Excluded by policy")
        result["message"] = f"Deleted {payload.path}"
        return result

    return jobs.create(
        "delete-file", f"Delete {payload.path}",
        [("baseline", "Baseline"), ("delete", "Delete"), ("version", "Version")], worker,
        project_id=project["id"], project_name=project["name"], source="FILES", target=payload.path,
    )


@app.post("/api/jobs/wifi")
def start_wifi(payload: WifiIn):
    project = current_project()

    def worker(handle):
        handle.stage("send", progress=None, detail=f"SSID: {payload.ssid}")
        try:
            result = client.json("POST", "/api/wifi", json=payload.model_dump())
        except DeviceError as exc:
            raise RuntimeError(str(exc)) from exc
        handle.stage_done("send", "Configuration accepted")
        handle.stage("persist", progress=50, detail="Runtime saved configuration")
        handle.stage_done("persist", "Saved; reboot may be required")
        result["message"] = "Wi-Fi configuration saved"
        return result

    return jobs.create(
        "wifi-config", "Save Wi-Fi configuration", [("send", "Send"), ("persist", "Persist")], worker,
        project_id=project["id"], project_name=project["name"], source="WIFI", target=payload.ssid,
        context={"ssid": payload.ssid, "password_present": bool(payload.password)},
    )


@app.post("/api/jobs/reboot")
def start_reboot():
    project = current_project()

    def worker(handle):
        handle.stage("send", progress=None, detail="Sending reset command")
        try:
            result = client.json("POST", "/api/reboot")
        except DeviceError as exc:
            raise RuntimeError(str(exc)) from exc
        handle.stage_done("send", "Reset command sent")
        return {**result, "message": "ESP32 reboot command sent"}

    return jobs.create(
        "reboot", "Reboot ESP32", [("send", "Reset")], worker,
        project_id=project["id"], project_name=project["name"], source="DEVICE", target=project["name"],
    )


@app.post("/api/jobs/history-snapshot")
def start_history_snapshot(payload: SnapshotIn):
    project = current_project()

    def worker(handle):
        handle.stage("collect", progress=5, detail="Scanning safe files")
        try:
            files, skipped = collect_device_files("/")
        except DeviceError as exc:
            raise RuntimeError(str(exc)) from exc
        handle.stage_done("collect", f"{len(files)} files; {len(skipped)} excluded")
        handle.stage("version", progress=10, detail="Comparing with Local History")
        result = record_snapshot(project["id"], files, message=payload.message)
        handle.stage_done("version", f"{result['created']} new revisions · {result['unchanged']} unchanged")
        return {**result, "skipped": skipped, "message": f"Snapshot saved: {result['created']} new revisions"}

    return jobs.create(
        "history-snapshot", "Create Local History snapshot", [("collect", "Collect"), ("version", "Version")], worker,
        project_id=project["id"], project_name=project["name"], source="HISTORY", target=project["name"],
    )


@app.post("/api/jobs/history-restore/{revision_id}")
def start_history_restore(revision_id: int):
    project = current_project()

    def worker(handle):
        handle.stage("load", progress=50, detail=f"Revision #{revision_id}")
        revision = get_revision(project["id"], revision_id)
        if not revision:
            raise RuntimeError("Revision not found")
        if revision.get("binary"):
            raise RuntimeError("Binary revision cannot be restored by Wi-Fi editor")
        handle.stage_done("load", revision["path"])
        path = revision["path"]
        handle.stage("write", progress=None, detail=path)
        try:
            if revision.get("deleted"):
                result = client.json("DELETE", "/api/fs", params={"path": path})
            else:
                content = revision.get("content", "")
                result = client.json(
                    "PUT", "/api/fs", params={"path": path}, content=content.encode("utf-8"),
                    headers={"Content-Type": "application/octet-stream"}, timeout=15.0,
                )
        except DeviceError as exc:
            raise RuntimeError(str(exc)) from exc
        handle.stage_done("write", "Device updated")
        handle.stage("verify", progress=None, detail="Checking restored state")
        if revision.get("deleted"):
            verify = _read_device_bytes(path)
            if verify is not None:
                raise RuntimeError("Restore verify failed: deleted file is still readable")
            record_revision(project["id"], path, None, action="restore-delete", message=f"Restore revision #{revision_id}", deleted=True)
        else:
            expected = revision.get("content", "").encode("utf-8")
            verify = _read_device_bytes(path)
            if verify != expected:
                raise RuntimeError("Restore verify failed: device content differs")
            record_revision(project["id"], path, revision.get("content", ""), action="restore", message=f"Restore revision #{revision_id}")
        handle.stage_done("verify", "Restored state verified")
        return {**result, "message": f"Restored {path} from revision #{revision_id}"}

    return jobs.create(
        "history-restore", f"Restore revision #{revision_id}", [("load", "Revision"), ("write", "Restore"), ("verify", "Verify")], worker,
        project_id=project["id"], project_name=project["name"], source="HISTORY", target=f"revision:{revision_id}",
        context={"revision_id": revision_id},
    )


@app.post("/api/jobs/cloud-scan")
def start_cloud_scan(payload: CloudScanIn):
    project = current_project()

    def worker(handle):
        handle.stage("collect", progress=None, detail="Collecting publish scope")
        try:
            _files, report = prepare_publish_bundle(ROOT, payload.scope, dynamic_secrets=[client.connection.token])
        except (DeviceError, RuntimeError, ValueError) as exc:
            raise RuntimeError(str(exc)) from exc
        handle.stage_done("collect", f"{report['files']} files · {report['skipped_count']} excluded")
        handle.stage("scrub", progress=100, detail=f"{report['scrubber']['redactions']} redaction(s)")
        handle.stage_done("scrub", f"{report['scrubber']['files_redacted']} file(s) changed")
        return {**report, "message": f"Secret Scrubber checked {report['files']} files"}

    return jobs.create(
        "cloud-scan", "Secret Scrubber scan", [("collect", "Collect"), ("scrub", "Secrets")], worker,
        project_id=project["id"], project_name=project["name"], source="SECURITY", target=payload.scope,
        context={"scope": payload.scope, "secret_scrubber": True},
    )


@app.post("/api/jobs/cloud-auth")
def start_cloud_auth(payload: CloudAuthIn):
    project = current_project()

    def worker(handle):
        handle.stage("token", progress=50, detail="Loading token")
        token = _cloud_token(payload.provider, payload.token)
        handle.stage_done("token", "Token loaded")
        handle.stage("auth", progress=None, detail=f"Contacting {payload.provider.title()}")
        try:
            info = account_info(payload.provider, token)
        except CloudSyncError as exc:
            raise RuntimeError(str(exc)) from exc
        handle.stage_done("auth", f"@{info.get('username', '')}")
        handle.stage("vault", progress=50, detail="Credential storage")
        if payload.remember and payload.token.strip():
            remember_token(payload.provider, token)
            handle.stage_done("vault", f"Stored in {credential_backend_name()}")
        else:
            handle.stage_done("vault", "Session only")
        return {**info, "stored": bool(load_token(payload.provider)), "message": f"Authenticated: @{info.get('username', '')}"}

    return jobs.create(
        "cloud-auth", f"Check {payload.provider.title()} token", [("token", "Token"), ("auth", "Auth"), ("vault", "Vault")], worker,
        project_id=project["id"], project_name=project["name"], source=payload.provider.upper(), target="account",
    )


@app.post("/api/jobs/probe")
def start_probe(payload: PortIn):
    project_id, project_name, context = _usb_project(payload.port)
    return jobs.create(
        "probe", "Detect ESP32", [("probe", "Probe")], lambda handle: probe_device_job(payload.port, handle),
        project_id=project_id, project_name=project_name, source="USB", target=payload.port, context=context,
    )


@app.post("/api/jobs/flash")
def start_flash(payload: FlashIn):
    project_id, project_name, context = _usb_project(payload.port, payload.profile_id)
    return jobs.create(
        "flash", "Erase + Flash MicroPython",
        [("probe", "Probe"), ("firmware", "Firmware"), ("erase", "Erase"), ("flash", "Flash"), ("verify", "Verify")],
        lambda handle: flash_micropython_job(payload.port, payload.profile_id, payload.erase, payload.baud, handle),
        project_id=project_id, project_name=project_name, source="FLASH", target=payload.port,
        context={**context, "baud": payload.baud, "erase": payload.erase},
    )


@app.post("/api/jobs/install")
def start_install(payload: SerialProvisionIn):
    project_id, project_name, context = _usb_project(payload.port, payload.profile_id)
    return jobs.create(
        "runtime", "Install runtime",
        [("probe", "Probe"), ("prepare", "Config"), ("upload", "Files"), ("verify", "Verify"), ("reset", "Start")],
        lambda handle: install_runtime_job(payload.port, payload.profile_id, payload.ssid, payload.password, payload.token, handle),
        project_id=project_id, project_name=project_name, source="RUNTIME", target=payload.port,
        context={**context, "ssid": payload.ssid, "password_present": bool(payload.password), "api_token_present": bool(payload.token)},
    )


@app.post("/api/jobs/serial-files")
def start_serial_files(payload: PortIn):
    project_id, project_name, context = _usb_project(payload.port)
    return jobs.create(
        "serial-files", "Read files via mpremote", [("connect", "Connect"), ("files", "Read files"), ("reset", "Restart")],
        lambda handle: read_device_files_job(payload.port, handle),
        project_id=project_id, project_name=project_name, source="USB", target=payload.port, context=context,
    )


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
else:
    @app.get("/", response_class=HTMLResponse)
    def frontend_missing():
        return """
        <!doctype html><meta charset='utf-8'><title>ESP32 MultiBoard Studio</title>
        <style>body{font-family:system-ui;background:#07101f;color:#e5e7eb;padding:40px;max-width:800px;margin:auto}code{background:#162238;padding:3px 6px;border-radius:6px}</style>
        <h1>ESP32 MultiBoard Studio backend is running</h1>
        <p>React build is missing. Run <code>npm install</code> and <code>npm run build</code> in <code>frontend</code>, or rerun <code>scripts\\bootstrap.ps1</code>.</p>
        """


def _studio_url() -> str:
    return f"http://{STUDIO_HOST}:{STUDIO_PORT}"

def _port_preflight() -> None:
    # EN: Do not open a browser against an older Studio already owning the port.
    # RU: Не открываем браузер на старой Studio, которая уже заняла порт.
    probe=socket.socket(socket.AF_INET,socket.SOCK_STREAM); probe.settimeout(0.4)
    try: busy=probe.connect_ex((STUDIO_HOST,STUDIO_PORT))==0
    finally: probe.close()
    if not busy: return
    existing="unknown service"
    try:
        with httpx.Client(timeout=1.0,trust_env=False) as http:
            r=http.get(_studio_url()+"/api/host/info")
            if r.status_code==200: existing=f"ESP32 MultiBoard Studio {r.json().get('studio_version','?')}"
    except Exception: pass
    raise RuntimeError(f"Port {STUDIO_PORT} is already in use by {existing}. Close the previous Studio process or set GHOST32_PORT to another free port.")

def _open_browser() -> None:
    if os.environ.get("ESP32_STUDIO_NO_BROWSER") == "1": return
    threading.Timer(0.8,lambda:webbrowser.open(_studio_url())).start()

def main() -> None:
    import uvicorn
    try: _port_preflight()
    except RuntimeError as exc:
        print(f"ERROR: {exc}",file=sys.stderr); raise SystemExit(2) from exc
    print(f"Opening ESP32 MultiBoard Studio {STUDIO_VERSION} at {_studio_url()}")
    _open_browser(); uvicorn.run("host.app:app",host=STUDIO_HOST,port=STUDIO_PORT,reload=False,log_level="info")


if __name__ == "__main__":
    main()
