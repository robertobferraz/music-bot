from __future__ import annotations

from botmusica.music.services.playlist_jobs import PlaylistJobQueue


def test_playlist_jobs_create_progress_finish_cancel() -> None:
    q = PlaylistJobQueue()
    job = q.create(1, "query", "user", total=10)
    assert job.status == "queued"
    q.activate(1, job.job_id)
    q.update_progress(1, job.job_id, added=3, skipped=1)
    current = q.get(1, job.job_id)
    assert current is not None
    assert current.added == 3
    assert current.skipped == 1
    q.finish(1, job.job_id, "completed")
    assert q.get(1, job.job_id).status == "completed"  # type: ignore[union-attr]
    assert q.cancel(1, job.job_id) is False
