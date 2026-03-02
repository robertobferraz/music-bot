from __future__ import annotations

import asyncio

from botmusica.music.circuit_breaker import CircuitBreaker
from botmusica.music.errors import ExtractionErrorCode, map_extraction_exception
from botmusica.music.player import GuildPlayer, Track
from botmusica.music.queue_service import QueueService


def _track(name: str) -> Track:
    return Track(
        source_query=f"ytsearch:{name}",
        title=name,
        webpage_url=f"https://example.com/{name}",
        requested_by="tester",
        duration_seconds=120,
    )


def test_queue_service_async_flow() -> None:
    async def _run() -> None:
        service = QueueService()
        player = GuildPlayer(guild_id=1)

        await service.enqueue(player, _track("a"))
        await service.enqueue_many(player, [_track("b"), _track("c")])
        assert [item.title for item in player.snapshot_queue()] == ["a", "b", "c"]

        removed = service.remove(player, 2)
        assert removed.title == "b"
        assert [item.title for item in player.snapshot_queue()] == ["a", "c"]

        await service.enqueue_many(player, [_track("d"), _track("e")])
        moved = service.move(player, 3, 1)
        assert moved.title == "d"
        assert [item.title for item in player.snapshot_queue()] == ["d", "a", "c", "e"]

        jumped = service.jump(player, 4)
        assert jumped.title == "e"
        assert [item.title for item in player.snapshot_queue()] == ["e", "d", "a", "c"]

        service.enqueue_front(player, _track("x"))
        assert [item.title for item in player.snapshot_queue()] == ["x", "e", "d", "a", "c"]

        shuffled_size = service.shuffle(player)
        assert shuffled_size == 5

        cleared = service.clear(player)
        assert len(cleared) == 5
        assert player.snapshot_queue() == []

    asyncio.run(_run())


def test_circuit_breaker_open_half_open_close() -> None:
    breaker = CircuitBreaker(failure_threshold=2, recovery_seconds=0.01, half_open_max_calls=1)
    assert breaker.allow_request() is True
    breaker.record_failure()
    assert breaker.state == "closed"
    breaker.record_failure()
    assert breaker.state == "open"
    assert breaker.allow_request() is False

    async def _wait() -> None:
        await asyncio.sleep(0.02)

    asyncio.run(_wait())
    assert breaker.allow_request() is True
    assert breaker.state == "half_open"
    breaker.record_success()
    assert breaker.state == "closed"


def test_error_mapping_codes() -> None:
    drm = map_extraction_exception(RuntimeError("known DRM protected content"))
    assert drm.code == ExtractionErrorCode.DRM_PROTECTED

    unavailable = map_extraction_exception(RuntimeError("video unavailable"))
    assert unavailable.code == ExtractionErrorCode.PRIVATE_OR_UNAVAILABLE

    forbidden = map_extraction_exception(RuntimeError("HTTP Error 403: Forbidden"))
    assert forbidden.code == ExtractionErrorCode.FORBIDDEN

    rate_limited = map_extraction_exception(RuntimeError("HTTP Error 429: Too Many Requests"))
    assert rate_limited.code == ExtractionErrorCode.RATE_LIMITED

    unknown = map_extraction_exception(RuntimeError("unexpected decoder error"))
    assert unknown.code == ExtractionErrorCode.UNKNOWN
