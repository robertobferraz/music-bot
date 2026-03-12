from __future__ import annotations

import asyncio
from types import SimpleNamespace

from botmusica.music.services.search_pipeline import SearchPipeline, SearchPipelineRequest


def _track(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        source_query=f"ytsearch:{name}",
        title=name,
        webpage_url=f"https://example.com/{name}",
        requested_by="tester",
        duration_seconds=100,
    )


def test_search_pipeline_prefers_cache_then_stops() -> None:
    async def _run() -> None:
        pipeline = SearchPipeline(cache_timeout_seconds=0.2, resolver_timeout_seconds=0.2)
        request = SearchPipelineRequest(query="abc", requester="tester", limit=3, guild_id=1, user_id=2)

        async def cache_lookup(_req: SearchPipelineRequest) -> tuple[list[SimpleNamespace] | None, bool]:
            return [_track("cached")], False

        async def resolver_lookup(_req: SearchPipelineRequest) -> list[SimpleNamespace]:
            raise AssertionError("resolver should not be called when cache hits")

        result = await pipeline.run(
            request,
            cache_lookup=cache_lookup,
            resolver_lookup=resolver_lookup,
        )
        assert result.source == "cache"
        assert result.tracks[0].title == "cached"

    asyncio.run(_run())


def test_search_pipeline_falls_back_to_resolver() -> None:
    async def _run() -> None:
        pipeline = SearchPipeline(cache_timeout_seconds=0.2, resolver_timeout_seconds=0.2)
        request = SearchPipelineRequest(query="abc", requester="tester", limit=3)

        async def cache_lookup(_req: SearchPipelineRequest) -> tuple[list[SimpleNamespace] | None, bool]:
            return None, False

        async def resolver_lookup(_req: SearchPipelineRequest) -> list[SimpleNamespace]:
            return [_track("resolver")]

        result = await pipeline.run(
            request,
            cache_lookup=cache_lookup,
            resolver_lookup=resolver_lookup,
        )
        assert result.source == "resolver"
        assert result.tracks[0].title == "resolver"

    asyncio.run(_run())
