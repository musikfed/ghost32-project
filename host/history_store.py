from __future__ import annotations

import difflib
import hashlib
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any



from .platform_support import data_dir


DB_PATH = data_dir() / "history.sqlite3"
_lock = threading.RLock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace TEXT NOT NULL,
            path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            action TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            sha256 TEXT NOT NULL,
            content BLOB,
            deleted INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_revision_lookup ON revisions(workspace, path, id DESC)")
    conn.commit()
    return conn


def workspace_key(base_url: str) -> str:
    value = (base_url or "offline").strip().lower()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def _digest(content: bytes | None, deleted: bool) -> str:
    marker = b"\x01deleted" if deleted else b"\x00content"
    return hashlib.sha256(marker + (content or b"")).hexdigest()


def record_revision(workspace: str, path: str, content: bytes | str | None, *, action: str = "save", message: str = "", deleted: bool = False) -> int | None:
    if isinstance(content, str):
        content = content.encode("utf-8")
    digest = _digest(content, deleted)
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _lock, _connect() as conn:
        previous = conn.execute(
            "SELECT id, sha256 FROM revisions WHERE workspace=? AND path=? ORDER BY id DESC LIMIT 1",
            (workspace, path),
        ).fetchone()
        if previous and previous["sha256"] == digest:
            return None
        cur = conn.execute(
            "INSERT INTO revisions(workspace,path,created_at,action,message,sha256,content,deleted) VALUES(?,?,?,?,?,?,?,?)",
            (workspace, path, created_at, action, message, digest, content, 1 if deleted else 0),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_revisions(workspace: str, path: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    with _lock, _connect() as conn:
        if path:
            rows = conn.execute(
                "SELECT id,path,created_at,action,message,sha256,deleted,length(content) AS bytes FROM revisions WHERE workspace=? AND path=? ORDER BY id DESC LIMIT ?",
                (workspace, path, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id,path,created_at,action,message,sha256,deleted,length(content) AS bytes FROM revisions WHERE workspace=? ORDER BY id DESC LIMIT ?",
                (workspace, limit),
            ).fetchall()
    return [dict(row) for row in rows]


def get_revision(workspace: str, revision_id: int) -> dict[str, Any] | None:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT id,path,created_at,action,message,sha256,content,deleted FROM revisions WHERE workspace=? AND id=?",
            (workspace, int(revision_id)),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    raw = item.pop("content")
    try:
        item["content"] = (raw or b"").decode("utf-8")
        item["binary"] = False
    except UnicodeDecodeError:
        item["content"] = ""
        item["binary"] = True
    return item


def diff_text(old_text: str, new_text: str, path: str) -> str:
    return "".join(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"revision:{path}",
            tofile=f"device:{path}",
            n=3,
        )
    ) or "Нет отличий."


def latest_states(workspace: str) -> dict[str, dict[str, Any]]:
    """Return the newest revision metadata for every path in a workspace."""
    with _lock, _connect() as conn:
        rows = conn.execute(
            """
            SELECT r.id,r.path,r.created_at,r.action,r.message,r.sha256,r.deleted,length(r.content) AS bytes
            FROM revisions r
            JOIN (
                SELECT path, MAX(id) AS max_id
                FROM revisions
                WHERE workspace=?
                GROUP BY path
            ) latest ON latest.max_id=r.id
            WHERE r.workspace=?
            """,
            (workspace, workspace),
        ).fetchall()
    return {str(row["path"]): dict(row) for row in rows}


def record_snapshot(workspace: str, files: dict[str, str | bytes], *, message: str = "Project snapshot") -> dict[str, Any]:
    """Version all changed safe files and mark previously tracked missing files as deleted."""
    existing = latest_states(workspace)
    current_paths = set(files)
    created: list[int] = []
    unchanged = 0
    deleted = 0

    for path, content in sorted(files.items()):
        revision_id = record_revision(workspace, path, content, action="snapshot", message=message)
        if revision_id is None:
            unchanged += 1
        else:
            created.append(revision_id)

    for path, state in existing.items():
        if path in current_paths or bool(state.get("deleted")):
            continue
        revision_id = record_revision(
            workspace,
            path,
            None,
            action="snapshot-delete",
            message=f"{message} · file missing from device",
            deleted=True,
        )
        if revision_id is not None:
            created.append(revision_id)
            deleted += 1

    return {
        "created": len(created),
        "revision_ids": created,
        "unchanged": unchanged,
        "deleted": deleted,
        "files": len(files),
    }
