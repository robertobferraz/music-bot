from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

JobStatus = Literal["queued", "running", "completed", "cancelled", "failed"]


@dataclass(slots=True)
class PlaylistJob:
    job_id: str
    guild_id: int
    query: str
    requested_by: str
    created_at: float
    total: int = 0
    added: int = 0
    skipped: int = 0
    status: JobStatus = "queued"
    error: str = ""
    meta: dict[str, str] = field(default_factory=dict)


class PlaylistJobQueue:
    def __init__(self) -> None:
        self._jobs: dict[int, list[PlaylistJob]] = {}
        self._active_job_id: dict[int, str] = {}

    def create(self, guild_id: int, query: str, requested_by: str, *, total: int = 0) -> PlaylistJob:
        job = PlaylistJob(
            job_id=f"pl-{uuid.uuid4().hex[:10]}",
            guild_id=guild_id,
            query=query[:250],
            requested_by=requested_by[:80],
            created_at=time.time(),
            total=max(total, 0),
            status="queued",
        )
        self._jobs.setdefault(guild_id, []).append(job)
        return job

    def activate(self, guild_id: int, job_id: str) -> PlaylistJob | None:
        job = self.get(guild_id, job_id)
        if job is None:
            return None
        self._active_job_id[guild_id] = job_id
        job.status = "running"
        return job

    def get(self, guild_id: int, job_id: str) -> PlaylistJob | None:
        for job in self._jobs.get(guild_id, []):
            if job.job_id == job_id:
                return job
        return None

    def active(self, guild_id: int) -> PlaylistJob | None:
        active_id = self._active_job_id.get(guild_id)
        if not active_id:
            return None
        return self.get(guild_id, active_id)

    def update_progress(self, guild_id: int, job_id: str, *, added: int = 0, skipped: int = 0, total: int | None = None) -> None:
        job = self.get(guild_id, job_id)
        if job is None:
            return
        if total is not None:
            job.total = max(total, job.total)
        job.added += max(added, 0)
        job.skipped += max(skipped, 0)

    def finish(self, guild_id: int, job_id: str, status: JobStatus, *, error: str = "") -> None:
        job = self.get(guild_id, job_id)
        if job is None:
            return
        job.status = status
        job.error = error[:250]
        if self._active_job_id.get(guild_id) == job_id:
            self._active_job_id.pop(guild_id, None)

    def cancel(self, guild_id: int, job_id: str) -> bool:
        job = self.get(guild_id, job_id)
        if job is None:
            return False
        if job.status in {"completed", "cancelled", "failed"}:
            return False
        job.status = "cancelled"
        if self._active_job_id.get(guild_id) == job_id:
            self._active_job_id.pop(guild_id, None)
        return True

    def latest(self, guild_id: int) -> PlaylistJob | None:
        jobs = self._jobs.get(guild_id, [])
        return jobs[-1] if jobs else None

    def prune(self, guild_id: int, *, max_jobs: int = 20) -> None:
        jobs = self._jobs.get(guild_id, [])
        if len(jobs) <= max_jobs:
            return
        self._jobs[guild_id] = jobs[-max_jobs:]
