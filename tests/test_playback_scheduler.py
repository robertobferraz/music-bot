from __future__ import annotations

from botmusica.music.services.playback_scheduler import PlaybackScheduler, QueuePriority


def _track(name: str) -> object:
    class _T:
        def __init__(self) -> None:
            self.source_query = f"ytsearch:{name}"
            self.title = name
            self.webpage_url = f"https://example.com/{name}"
            self.requested_by = "tester"

    return _T()


def test_scheduler_high_priority_goes_front_without_background() -> None:
    scheduler = PlaybackScheduler()
    plan = scheduler.plan_playlist_enqueue(
        tracks=[_track("a"), _track("b")],
        to_front=True,
        priority=QueuePriority.HIGH,
        incremental_enabled=True,
        initial_enqueue=1,
    )
    assert plan.to_front is True
    assert plan.incremental is False
    assert len(plan.immediate) == 2
    assert plan.background == []


def test_scheduler_incremental_for_normal_large_batch() -> None:
    scheduler = PlaybackScheduler()
    plan = scheduler.plan_playlist_enqueue(
        tracks=[_track("a"), _track("b"), _track("c")],
        to_front=False,
        priority=QueuePriority.NORMAL,
        incremental_enabled=True,
        initial_enqueue=2,
    )
    assert plan.incremental is True
    assert [t.title for t in plan.immediate] == ["a", "b"]
    assert [t.title for t in plan.background] == ["c"]
