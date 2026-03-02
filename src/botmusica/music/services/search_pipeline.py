from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from botmusica.music.player import Track
else:
    Track = Any


@dataclass(slots=True)
class SearchPipelineRequest:
    query: str
    requester: str
    limit: int
    guild_id: int = 0
    user_id: int = 0


@dataclass(slots=True)
class SearchPipelineResult:
    tracks: list[Track]
    source: str
    stale: bool = False
    stage_latency_ms: dict[str, float] = field(default_factory=dict)


CacheLookup = Callable[[SearchPipelineRequest], Awaitable[tuple[list[Track] | None, bool]]]
SearchLookup = Callable[[SearchPipelineRequest], Awaitable[list[Track]]]
CacheStore = Callable[[SearchPipelineRequest, list[Track]], Awaitable[None]]


class SearchPipeline:
    def __init__(
        self,
        *,
        cache_timeout_seconds: float = 0.12,
        lavalink_timeout_seconds: float = 1.6,
        resolver_timeout_seconds: float = 4.0,
    ) -> None:
        self.cache_timeout_seconds = max(cache_timeout_seconds, 0.01)
        self.lavalink_timeout_seconds = max(lavalink_timeout_seconds, 0.01)
        self.resolver_timeout_seconds = max(resolver_timeout_seconds, 0.01)

    async def run(
        self,
        request: SearchPipelineRequest,
        *,
        cache_lookup: CacheLookup | None = None,
        lavalink_lookup: SearchLookup | None = None,
        resolver_lookup: SearchLookup,
        cache_store: CacheStore | None = None,
    ) -> SearchPipelineResult:
        stage_latency_ms: dict[str, float] = {}

        if cache_lookup is not None:
            started = time.perf_counter()
            try:
                cached, stale = await asyncio.wait_for(
                    cache_lookup(request),
                    timeout=self.cache_timeout_seconds,
                )
            except asyncio.TimeoutError:
                cached, stale = None, False
            stage_latency_ms["cache"] = (time.perf_counter() - started) * 1000.0
            if cached:
                return SearchPipelineResult(
                    tracks=cached,
                    source="cache",
                    stale=bool(stale),
                    stage_latency_ms=stage_latency_ms,
                )

        if lavalink_lookup is not None:
            started = time.perf_counter()
            try:
                lavalink_tracks = await asyncio.wait_for(
                    lavalink_lookup(request),
                    timeout=self.lavalink_timeout_seconds,
                )
            except asyncio.TimeoutError:
                lavalink_tracks = []
            stage_latency_ms["lavalink"] = (time.perf_counter() - started) * 1000.0
            if lavalink_tracks:
                if cache_store is not None:
                    await cache_store(request, lavalink_tracks)
                return SearchPipelineResult(
                    tracks=lavalink_tracks,
                    source="lavalink",
                    stale=False,
                    stage_latency_ms=stage_latency_ms,
                )

        started = time.perf_counter()
        resolver_tracks = await asyncio.wait_for(
            resolver_lookup(request),
            timeout=self.resolver_timeout_seconds,
        )
        stage_latency_ms["resolver"] = (time.perf_counter() - started) * 1000.0
        if resolver_tracks and cache_store is not None:
            await cache_store(request, resolver_tracks)
        return SearchPipelineResult(
            tracks=resolver_tracks,
            source="resolver",
            stale=False,
            stage_latency_ms=stage_latency_ms,
        )
