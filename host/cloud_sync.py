from __future__ import annotations

import base64
import ctypes
import os
import shutil
import subprocess
import urllib.parse
from ctypes import wintypes
from typing import Any, Callable

import httpx

SERVICE_NAME = "ESP32 MultiBoard Studio"
GITHUB_API = "https://api.github.com"
GITLAB_API = "https://gitlab.com/api/v4"


class CloudSyncError(RuntimeError):
    pass


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2026-03-10",
        "User-Agent": "ESP32-MultiBoard-Studio/2.5.0",
    }


def _gitlab_headers(token: str) -> dict[str, str]:
    return {
        "PRIVATE-TOKEN": token,
        "User-Agent": "ESP32-MultiBoard-Studio/2.5.0",
    }


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        data = {}
    if response.is_error:
        detail = data.get("message") if isinstance(data, dict) else None
        if isinstance(detail, dict):
            detail = "; ".join(f"{k}: {v}" for k, v in detail.items())
        if isinstance(detail, list):
            detail = "; ".join(str(v) for v in detail)
        raise CloudSyncError(str(detail or response.text or f"HTTP {response.status_code}"))
    return data if isinstance(data, dict) else {"data": data}


def _credential_target(provider: str) -> str:
    return f"{SERVICE_NAME}:{provider.lower()}"


def _wincred_api():
    if os.name != "nt":
        return None

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    advapi = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    cred_write = advapi.CredWriteW
    cred_write.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
    cred_write.restype = wintypes.BOOL
    cred_read = advapi.CredReadW
    cred_read.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
    cred_read.restype = wintypes.BOOL
    cred_delete = advapi.CredDeleteW
    cred_delete.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    cred_delete.restype = wintypes.BOOL
    cred_free = advapi.CredFree
    cred_free.argtypes = [ctypes.c_void_p]
    cred_free.restype = None
    return CREDENTIALW, cred_write, cred_read, cred_delete, cred_free


def _linux_secret_tool() -> str | None:
    # EN: Linux uses Secret Service via secret-tool when available.
    # RU: Linux использует Secret Service через secret-tool, если он доступен.
    return shutil.which("secret-tool") if os.name != "nt" else None

def remember_token(provider: str, token: str) -> None:
    api=_wincred_api()
    if api is not None:
        CREDENTIALW,cred_write,_r,_d,_f=api; blob=token.encode("utf-16-le"); buffer=(ctypes.c_ubyte*len(blob)).from_buffer_copy(blob); credential=CREDENTIALW()
        credential.Flags=0; credential.Type=1; credential.TargetName=_credential_target(provider); credential.Comment="ESP32 MultiBoard Studio cloud token"; credential.CredentialBlobSize=len(blob); credential.CredentialBlob=ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)); credential.Persist=2; credential.AttributeCount=0; credential.Attributes=None; credential.TargetAlias=None; credential.UserName=provider.lower()
        if not cred_write(ctypes.byref(credential),0): raise CloudSyncError(f"Windows Credential Manager error: {ctypes.get_last_error()}")
        return
    tool=_linux_secret_tool()
    if not tool: raise CloudSyncError("Linux persistent token storage requires secret-tool (package libsecret-tools). Install it or disable Remember token.")
    try: subprocess.run([tool,"store","--label=ESP32 MultiBoard Studio cloud token","service",SERVICE_NAME,"provider",provider.lower()],input=token,text=True,check=True,capture_output=True,timeout=15)
    except Exception as exc: raise CloudSyncError(f"Secret Service error: {exc}") from exc

def load_token(provider: str) -> str:
    api=_wincred_api()
    if api is not None:
        CREDENTIALW,_w,cred_read,_d,cred_free=api; pointer=ctypes.POINTER(CREDENTIALW)()
        if not cred_read(_credential_target(provider),1,0,ctypes.byref(pointer)): return ""
        try:
            cred=pointer.contents; return ctypes.string_at(cred.CredentialBlob,cred.CredentialBlobSize).decode("utf-16-le")
        except Exception: return ""
        finally: cred_free(pointer)
    tool=_linux_secret_tool()
    if not tool: return ""
    try:
        proc=subprocess.run([tool,"lookup","service",SERVICE_NAME,"provider",provider.lower()],text=True,check=False,capture_output=True,timeout=10); return proc.stdout.strip() if proc.returncode==0 else ""
    except Exception: return ""

def forget_token(provider: str) -> None:
    api=_wincred_api()
    if api is not None:
        _C,_w,_r,cred_delete,_f=api
        if not cred_delete(_credential_target(provider),1,0) and ctypes.get_last_error() not in (0,1168): raise CloudSyncError(f"Windows Credential Manager error: {ctypes.get_last_error()}")
        return
    tool=_linux_secret_tool()
    if tool:
        try: subprocess.run([tool,"clear","service",SERVICE_NAME,"provider",provider.lower()],text=True,check=False,capture_output=True,timeout=10)
        except Exception: pass

def account_info(provider: str, token: str) -> dict[str, Any]:
    provider = provider.lower()
    if not token.strip():
        raise CloudSyncError("Token is required")
    with httpx.Client(timeout=25.0, follow_redirects=True) as client:
        if provider == "github":
            data = _json(client.get(f"{GITHUB_API}/user", headers=_github_headers(token)))
            return {"provider": provider, "username": data.get("login", ""), "name": data.get("name") or data.get("login", ""), "avatar_url": data.get("avatar_url", "")}
        if provider == "gitlab":
            data = _json(client.get(f"{GITLAB_API}/user", headers=_gitlab_headers(token)))
            return {"provider": provider, "username": data.get("username", ""), "name": data.get("name") or data.get("username", ""), "avatar_url": data.get("avatar_url", "")}
    raise CloudSyncError("Unsupported provider")


def create_or_get_repository(provider: str, token: str, repo_name: str, private: bool) -> dict[str, Any]:
    repo_name = _validate_repo_name(repo_name)
    account = account_info(provider, token)
    provider = provider.lower()
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        if provider == "github":
            headers = _github_headers(token)
            owner = account["username"]
            existing = client.get(f"{GITHUB_API}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo_name)}", headers=headers)
            if existing.status_code == 200:
                repo = _json(existing)
                if bool(repo.get("private")) != bool(private):
                    repo = _json(client.patch(
                        f"{GITHUB_API}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo_name)}",
                        headers=headers, json={"private": bool(private)}
                    ))
                return _repo_result(provider, repo, created=False)
            if existing.status_code not in {404}:
                _json(existing)
            repo = _json(client.post(f"{GITHUB_API}/user/repos", headers=headers, json={
                "name": repo_name,
                "description": "ESP32 project published by MultiBoard Studio",
                "private": bool(private),
                "auto_init": True,
            }))
            return _repo_result(provider, repo, created=True)

        if provider == "gitlab":
            headers = _gitlab_headers(token)
            owner = account["username"]
            encoded = urllib.parse.quote(f"{owner}/{repo_name}", safe="")
            existing = client.get(f"{GITLAB_API}/projects/{encoded}", headers=headers)
            if existing.status_code == 200:
                repo = _json(existing)
                wanted_visibility = "private" if private else "public"
                if repo.get("visibility") != wanted_visibility:
                    repo = _json(client.put(
                        f"{GITLAB_API}/projects/{repo['id']}", headers=headers,
                        json={"visibility": wanted_visibility}
                    ))
                return _repo_result(provider, repo, created=False)
            if existing.status_code not in {404}:
                _json(existing)
            repo = _json(client.post(f"{GITLAB_API}/projects", headers=headers, json={
                "name": repo_name,
                "visibility": "private" if private else "public",
                "initialize_with_readme": True,
                "description": "ESP32 project published by MultiBoard Studio",
            }))
            return _repo_result(provider, repo, created=True)
    raise CloudSyncError("Unsupported provider")


def publish_snapshot(
    provider: str,
    token: str,
    repo_name: str,
    private: bool,
    files: dict[str, str | bytes],
    message: str,
    progress: Callable[[str, int, str], None] | None = None,
) -> dict[str, Any]:
    if not files:
        raise CloudSyncError("No publishable files found on the device")
    if sum(len(v.encode("utf-8")) if isinstance(v, str) else len(v) for v in files.values()) > 50_000_000:
        raise CloudSyncError("Snapshot is larger than the Studio cloud-sync safety limit (50 MB)")

    def step(stage: str, pct: int, detail: str) -> None:
        if progress:
            progress(stage, pct, detail)

    step("auth", 20, "Checking token")
    account = account_info(provider, token)
    step("auth", 100, f"Signed in as {account['username']}")

    step("repo", 20, "Opening repository")
    repo = create_or_get_repository(provider, token, repo_name, private)
    step("repo", 100, "Repository ready")

    provider = provider.lower()
    if provider == "github":
        return _publish_github(token, repo, files, message, step)
    if provider == "gitlab":
        return _publish_gitlab(token, repo, files, message, step)
    raise CloudSyncError("Unsupported provider")


def _publish_github(token: str, repo: dict[str, Any], files: dict[str, str | bytes], message: str, step) -> dict[str, Any]:
    owner = repo["owner"]
    name = repo["name"]
    branch = repo.get("default_branch") or "main"
    headers = _github_headers(token)
    base = f"{GITHUB_API}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}"
    with httpx.Client(timeout=45.0, follow_redirects=True) as client:
        step("snapshot", 10, f"Reading {branch}")
        ref = _json(client.get(f"{base}/git/ref/heads/{urllib.parse.quote(branch, safe='')}", headers=headers))
        parent_sha = ref["object"]["sha"]
        commit = _json(client.get(f"{base}/git/commits/{parent_sha}", headers=headers))
        base_tree = commit["tree"]["sha"]

        entries = []
        ordered = sorted(files.items())
        for index, (path, content) in enumerate(ordered, start=1):
            clean=path.lstrip("/")
            if isinstance(content, bytes):
                # EN: Binary GitHub files are uploaded as base64 blobs.
                # RU: Бинарные файлы GitHub загружаются как base64 blobs.
                blob=_json(client.post(f"{base}/git/blobs",headers=headers,json={"content":base64.b64encode(content).decode("ascii"),"encoding":"base64"}))
                entries.append({"path":clean,"mode":"100644","type":"blob","sha":blob["sha"]})
            else:
                entries.append({"path":clean,"mode":"100644","type":"blob","content":content})
            step("snapshot", min(80, int(index / len(ordered) * 80)), f"Preparing {path}")

        tree = _json(client.post(f"{base}/git/trees", headers=headers, json={"base_tree": base_tree, "tree": entries}))
        step("snapshot", 100, f"Prepared {len(entries)} files")

        step("commit", 35, "Creating commit")
        new_commit = _json(client.post(f"{base}/git/commits", headers=headers, json={
            "message": message or "Update ESP32 snapshot",
            "tree": tree["sha"],
            "parents": [parent_sha],
        }))
        step("commit", 70, "Updating branch")
        _json(client.patch(f"{base}/git/refs/heads/{urllib.parse.quote(branch, safe='')}", headers=headers, json={"sha": new_commit["sha"], "force": False}))
        step("commit", 100, new_commit["sha"][:12])

    return {
        "message": f"Published {len(files)} files to GitHub",
        "provider": "github",
        "repository": f"{owner}/{name}",
        "url": repo["web_url"],
        "branch": branch,
        "commit": new_commit["sha"],
        "files": len(files),
    }


def _publish_gitlab(token: str, repo: dict[str, Any], files: dict[str, str | bytes], message: str, step) -> dict[str, Any]:
    project_id = repo["id"]
    branch = repo.get("default_branch") or "main"
    headers = _gitlab_headers(token)
    base = f"{GITLAB_API}/projects/{project_id}"
    with httpx.Client(timeout=45.0, follow_redirects=True) as client:
        step("snapshot", 20, f"Reading {branch}")
        tree_response = client.get(f"{base}/repository/tree", headers=headers, params={"ref": branch, "recursive": "true", "per_page": 100})
        existing_data = tree_response.json() if tree_response.status_code == 200 else []
        if tree_response.status_code >= 400:
            _json(tree_response)
        existing = {item.get("path") for item in existing_data if isinstance(item, dict) and item.get("type") == "blob"}

        actions = []
        ordered = sorted(files.items())
        for index, (path, content) in enumerate(ordered, start=1):
            clean=path.lstrip("/"); action={"action":"update" if clean in existing else "create","file_path":clean}
            if isinstance(content, bytes): action.update({"content":base64.b64encode(content).decode("ascii"),"encoding":"base64"})
            else: action["content"]=content
            actions.append(action)
            step("snapshot", min(100, int(index / len(ordered) * 100)), f"Preparing {path}")

        step("commit", 40, f"Committing {len(actions)} files")
        commit = _json(client.post(f"{base}/repository/commits", headers=headers, json={
            "branch": branch,
            "commit_message": message or "Update ESP32 snapshot",
            "actions": actions,
        }))
        step("commit", 100, str(commit.get("short_id") or commit.get("id", ""))[:12])

    return {
        "message": f"Published {len(files)} files to GitLab",
        "provider": "gitlab",
        "repository": repo["path_with_namespace"],
        "url": repo["web_url"],
        "branch": branch,
        "commit": commit.get("id", ""),
        "files": len(files),
    }


def _repo_result(provider: str, data: dict[str, Any], created: bool) -> dict[str, Any]:
    if provider == "github":
        return {
            "provider": provider,
            "id": data.get("id"),
            "name": data.get("name", ""),
            "owner": (data.get("owner") or {}).get("login", ""),
            "default_branch": data.get("default_branch") or "main",
            "web_url": data.get("html_url", ""),
            "path_with_namespace": data.get("full_name", ""),
            "private": bool(data.get("private")),
            "created": created,
        }
    return {
        "provider": provider,
        "id": data.get("id"),
        "name": data.get("path") or data.get("name", ""),
        "owner": ((data.get("namespace") or {}).get("full_path") or ""),
        "default_branch": data.get("default_branch") or "main",
        "web_url": data.get("web_url", ""),
        "path_with_namespace": data.get("path_with_namespace", ""),
        "private": data.get("visibility") == "private",
        "created": created,
    }


def _validate_repo_name(value: str) -> str:
    value = (value or "").strip()
    if not value or len(value) > 100:
        raise CloudSyncError("Repository name must be 1..100 characters")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    if any(ch not in allowed for ch in value):
        raise CloudSyncError("Repository name may contain letters, digits, dash, underscore and dot")
    return value
