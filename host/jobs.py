from __future__ import annotations

import copy
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .audit_store import record_event


@dataclass
class JobStage:
    id: str
    label: str
    status: str = "pending"  # pending | active | done | error
    progress: int | None = 0
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "progress": self.progress,
            "detail": self.detail,
        }


@dataclass
class Job:
    id: str
    kind: str
    title: str
    stages: list[JobStage]
    status: str = "queued"  # queued | running | done | error
    progress: int = 0
    active_stage: str = ""
    message: str = ""
    log: str = ""
    error: str = ""
    result: dict[str, Any] | None = None
    project_id: str = ""
    project_name: str = ""
    source: str = "JOB"
    target: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    started_event_id: int | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "progress": self.progress,
            "active_stage": self.active_stage,
            "message": self.message,
            "log": self.log,
            "error": self.error,
            "result": copy.deepcopy(self.result),
            "project": {"id": self.project_id, "name": self.project_name},
            "source": self.source,
            "target": self.target,
            "context": copy.deepcopy(self.context),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "stages": [stage.as_dict() for stage in self.stages],
        }


class JobHandle:
    def __init__(self, manager: "JobManager", job_id: str):
        self.manager = manager
        self.job_id = job_id

    def _mutate(self, fn: Callable[[Job], None]) -> None:
        self.manager._mutate(self.job_id, fn)

    def start(self, message: str = "") -> None:
        def apply(job: Job) -> None:
            job.status = "running"
            job.message = message
        self._mutate(apply)

    def set_project(self, project_id: str, project_name: str, **context: Any) -> None:
        def apply(job: Job) -> None:
            job.project_id = str(project_id or job.project_id)
            job.project_name = str(project_name or job.project_name)
            if context:
                job.context.update(context)
        self._mutate(apply)

    def stage(self, stage_id: str, *, progress: int | None = None, detail: str | None = None, status: str = "active") -> None:
        def apply(job: Job) -> None:
            found = False
            for stage in job.stages:
                if stage.id == stage_id:
                    found = True
                    stage.status = status
                    if progress is not None:
                        stage.progress = max(0, min(100, int(progress)))
                    elif status == "active" and stage.progress == 0:
                        stage.progress = None
                    if detail is not None:
                        stage.detail = detail
                elif status == "active" and stage.status == "active":
                    stage.status = "done"
                    stage.progress = 100
            if not found:
                raise KeyError(stage_id)
            job.active_stage = stage_id if status == "active" else job.active_stage
            job.progress = _overall_progress(job.stages)
        self._mutate(apply)

    def stage_progress(self, stage_id: str, progress: int, detail: str | None = None) -> None:
        self.stage(stage_id, progress=progress, detail=detail, status="active")

    def stage_done(self, stage_id: str, detail: str | None = None) -> None:
        self.stage(stage_id, progress=100, detail=detail, status="done")

    def append_log(self, text: str) -> None:
        text = str(text)
        if not text:
            return
        def apply(job: Job) -> None:
            job.log += text
            if not text.endswith("\n"):
                job.log += "\n"
            if len(job.log) > 180_000:
                job.log = "… log truncated …\n" + job.log[-160_000:]
        self._mutate(apply)

    def message(self, text: str) -> None:
        self._mutate(lambda job: setattr(job, "message", str(text)))

    def finish(self, result: dict[str, Any] | None = None, message: str = "Готово") -> None:
        def apply(job: Job) -> None:
            for stage in job.stages:
                if stage.status in {"pending", "active"}:
                    stage.status = "done"
                    stage.progress = 100
            job.status = "done"
            job.progress = 100
            job.message = message
            job.result = copy.deepcopy(result or {})
            job.active_stage = ""
        self._mutate(apply)

    def fail(self, error: str) -> None:
        def apply(job: Job) -> None:
            for stage in job.stages:
                if stage.status == "active":
                    stage.status = "error"
            job.status = "error"
            job.error = str(error)
            job.message = "Ошибка"
            job.active_stage = ""
            job.progress = _overall_progress(job.stages)
        self._mutate(apply)


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}

    def create(
        self,
        kind: str,
        title: str,
        stages: list[tuple[str, str]],
        worker: Callable[[JobHandle], dict[str, Any] | None],
        *,
        project_id: str = "",
        project_name: str = "",
        source: str = "JOB",
        target: str = "",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        job = Job(
            job_id,
            kind,
            title,
            [JobStage(stage_id, label) for stage_id, label in stages],
            project_id=project_id,
            project_name=project_name,
            source=source,
            target=target,
            context=copy.deepcopy(context or {}),
        )
        with self._lock:
            self._jobs[job_id] = job
            self._prune_locked()
        handle = JobHandle(self, job_id)

        def run() -> None:
            handle.start()
            snapshot = self.get(job_id) or {}
            started_event = record_event(
                kind="action",
                severity="info",
                status="running",
                source=snapshot.get("source") or source,
                action=kind,
                message=f"Started: {title}",
                project_id=(snapshot.get("project") or {}).get("id", ""),
                project_name=(snapshot.get("project") or {}).get("name", ""),
                job_id=job_id,
                target=snapshot.get("target") or target,
                context=snapshot.get("context") or context or {},
            )
            self._mutate(job_id, lambda item: setattr(item, "started_event_id", started_event))
            try:
                result = worker(handle) or {}
                current = self.get(job_id)
                if current and current["status"] not in {"done", "error"}:
                    handle.finish(result, result.get("message", "Готово") if isinstance(result, dict) else "Готово")
                current = self.get(job_id) or {}
                record_event(
                    kind="action",
                    severity="info",
                    status="ok",
                    source=current.get("source") or source,
                    action=kind,
                    message=current.get("message") or f"Completed: {title}",
                    project_id=(current.get("project") or {}).get("id", ""),
                    project_name=(current.get("project") or {}).get("name", ""),
                    job_id=job_id,
                    target=current.get("target") or target,
                    detail=(current.get("log") or "")[-4000:],
                    context={**(current.get("context") or {}), "result": current.get("result") or {}},
                )
            except Exception as exc:
                handle.append_log(f"ERROR: {exc}")
                handle.fail(str(exc))
                current = self.get(job_id) or {}
                record_event(
                    kind="error",
                    severity="error",
                    status="error",
                    source=current.get("source") or source,
                    action=kind,
                    message=str(exc),
                    project_id=(current.get("project") or {}).get("id", ""),
                    project_name=(current.get("project") or {}).get("name", ""),
                    job_id=job_id,
                    target=current.get("target") or target,
                    detail=(current.get("log") or "")[-8000:],
                    context=current.get("context") or {},
                )

        thread = threading.Thread(target=run, name=f"studio-job-{kind}-{job_id[:8]}", daemon=True)
        thread.start()
        return {"job_id": job_id}

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.as_dict() if job else None

    def _mutate(self, job_id: str, fn: Callable[[Job], None]) -> None:
        with self._lock:
            job = self._jobs[job_id]
            fn(job)
            job.updated_at = time.time()

    def _prune_locked(self) -> None:
        if len(self._jobs) <= 50:
            return
        removable = sorted(
            (job for job in self._jobs.values() if job.status in {"done", "error"}),
            key=lambda item: item.updated_at,
        )
        while len(self._jobs) > 40 and removable:
            old = removable.pop(0)
            self._jobs.pop(old.id, None)


def _overall_progress(stages: list[JobStage]) -> int:
    if not stages:
        return 0
    total = 0.0
    for stage in stages:
        if stage.status == "done":
            total += 100
        elif stage.status == "error":
            total += float(stage.progress or 0)
        elif stage.status == "active":
            total += float(stage.progress or 0)
    return int(round(total / len(stages)))


jobs = JobManager()
