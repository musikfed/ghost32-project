from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any



from .platform_support import data_dir


DB_PATH = data_dir() / "activity.sqlite3"
_lock = threading.RLock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            kind TEXT NOT NULL,
            severity TEXT NOT NULL,
            status TEXT NOT NULL,
            source TEXT NOT NULL,
            action TEXT NOT NULL,
            message TEXT NOT NULL,
            project_id TEXT NOT NULL DEFAULT '',
            project_name TEXT NOT NULL DEFAULT '',
            job_id TEXT NOT NULL DEFAULT '',
            target TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT '',
            context_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_created ON events(id DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_project ON events(project_id, id DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind, id DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_source ON events(source, id DESC)")
    conn.commit()
    return conn


def record_event(
    *,
    kind: str = "action",
    severity: str = "info",
    status: str = "ok",
    source: str,
    action: str,
    message: str,
    project_id: str = "",
    project_name: str = "",
    job_id: str = "",
    target: str = "",
    detail: str = "",
    context: dict[str, Any] | None = None,
) -> int:
    created_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    payload = json.dumps(context or {}, ensure_ascii=False, separators=(",", ":"), default=str)
    with _lock, _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO events(
                created_at,kind,severity,status,source,action,message,
                project_id,project_name,job_id,target,detail,context_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                created_at,
                kind,
                severity,
                status,
                source,
                action,
                message,
                project_id,
                project_name,
                job_id,
                target,
                detail,
                payload,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_events(
    *,
    project_id: str | None = None,
    kind: str | None = None,
    source: str | None = None,
    limit: int = 250,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if project_id:
        clauses.append("project_id=?")
        params.append(project_id)
    if kind and kind != "all":
        clauses.append("kind=?")
        params.append(kind)
    if source and source != "all":
        clauses.append("source=?")
        params.append(source)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    limit = max(1, min(1000, int(limit)))
    query = (
        "SELECT id,created_at,kind,severity,status,source,action,message,project_id,"
        "project_name,job_id,target,detail,context_json FROM events"
        + where
        + " ORDER BY id DESC LIMIT ?"
    )
    params.append(limit)
    with _lock, _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["context"] = json.loads(item.pop("context_json") or "{}")
        except json.JSONDecodeError:
            item["context"] = {}
            item.pop("context_json", None)
        result.append(item)
    return result


def clear_events(*, project_id: str | None = None, kind: str | None = None) -> int:
    clauses: list[str] = []
    params: list[Any] = []
    if project_id:
        clauses.append("project_id=?")
        params.append(project_id)
    if kind and kind != "all":
        clauses.append("kind=?")
        params.append(kind)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM events" + where, params)
        conn.commit()
        return int(cur.rowcount or 0)
