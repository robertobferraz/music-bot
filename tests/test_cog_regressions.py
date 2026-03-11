from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

from botmusica.music.cog import MusicCog
from botmusica.music.player import GuildPlayer, Track, TrackBatch
from botmusica.music.resolver import MusicResolver
from botmusica.music.services.player_state import PlayerState


def _build_cog(loop: asyncio.AbstractEventLoop) -> MusicCog:
    bot = SimpleNamespace(loop=loop, user=None, guilds=[])
    return MusicCog(bot)


def test_send_followup_strips_delete_after() -> None:
    async def _run() -> None:
        cog = _build_cog(asyncio.get_running_loop())

        class FakeFollowup:
            async def send(self, *, wait: bool, **kwargs: object) -> None:
                assert wait is True
                assert "delete_after" not in kwargs

        interaction = SimpleNamespace(followup=FakeFollowup())
        await cog._send_followup(interaction, content="ok", delete_after=30)

    asyncio.run(_run())


def test_recover_playback_after_reconnect_requeues_current_track() -> None:
    async def _run() -> None:
        cog = _build_cog(asyncio.get_running_loop())

        player = GuildPlayer(guild_id=1)
        player.current = Track(
            source_query="ytsearch:track-a",
            title="track-a",
            webpage_url="https://example.com/a",
            requested_by="tester",
            duration_seconds=120,
        )

        voice_client = SimpleNamespace()
        guild = SimpleNamespace(id=1, voice_client=voice_client)

        called = {"started": False}

        async def _get_player(_guild_id: int) -> GuildPlayer:
            return player

        async def _persist(_guild_id: int, _player: GuildPlayer) -> None:
            return

        async def _start(_guild: object, _channel: object | None) -> None:
            called["started"] = True

        cog._get_player = _get_player  # type: ignore[method-assign]
        cog._persist_queue_state = _persist  # type: ignore[method-assign]
        cog._start_next_if_needed = _start  # type: ignore[method-assign]
        cog._is_voice_connected = lambda _vc: True  # type: ignore[method-assign]
        cog._is_voice_playing = lambda _vc: False  # type: ignore[method-assign]
        cog._is_voice_paused = lambda _vc: False  # type: ignore[method-assign]
        cog.feature_flags = replace(cog.feature_flags, reconnect_strategy_enabled=False)

        recovered = await cog._recover_playback_after_reconnect(guild, None)
        assert recovered is True
        assert player.current is None
        assert [item.title for item in player.snapshot_queue()] == ["track-a"]
        assert called["started"] is True

    asyncio.run(_run())


def test_is_voice_connected_lavalink_compatibility() -> None:
    loop = asyncio.new_event_loop()
    try:
        cog = _build_cog(loop)
        cog._is_lavalink_player = lambda _vc: True  # type: ignore[method-assign]

        with_connected = SimpleNamespace(connected=True)
        assert cog._is_voice_connected(with_connected) is True

        with_private_flag = SimpleNamespace(_connected=True)
        assert cog._is_voice_connected(with_private_flag) is True

        disconnected = SimpleNamespace(connected=False)
        assert cog._is_voice_connected(disconnected) is False
    finally:
        loop.close()


def test_resolver_spotify_fallback_prefers_best_candidate() -> None:
    class FakeMusic:
        async def extract_track(self, link: str, requester: str) -> Track:
            return Track(
                source_query=link,
                title=f"direct-{requester}",
                webpage_url=link,
                requested_by=requester,
            )

        async def extract_tracks(self, link: str, requester: str) -> object:
            raise NotImplementedError

        async def search_tracks(self, query: str, requester: str, *, limit: int = 5) -> list[Track]:
            assert requester == "tester"
            assert limit == 3
            return [
                Track(
                    source_query="ytsearch:wrong",
                    title="outra musica totalmente diferente",
                    webpage_url="https://example.com/wrong",
                    requested_by=requester,
                ),
                Track(
                    source_query="ytsearch:best",
                    title="artist x musica y oficial",
                    webpage_url="https://example.com/best",
                    requested_by=requester,
                ),
            ]

        async def extract_recommended_track(self, from_track: Track, requester: str) -> Track:
            return from_track

    async def _run() -> None:
        resolver = MusicResolver(
            FakeMusic(),
            spotify_strict_match=True,
            spotify_match_threshold=0.2,
            spotify_candidate_limit=3,
            spotify_meta_cache_ttl_seconds=60,
            spotify_meta_cache_max_entries=32,
        )
        resolver._spotify_oembed_meta = lambda _url: asyncio.sleep(0, result=("musica y", "artist x"))  # type: ignore[method-assign]

        track, used_spotify = await resolver.extract_track_with_spotify_fallback(
            link="https://open.spotify.com/track/abc",
            requester="tester",
        )
        assert used_spotify is True
        assert track.source_query == "ytsearch:best"
        await resolver.close()

    asyncio.run(_run())


def test_resolver_spotify_playlist_converts_all_items_to_search_queries() -> None:
    class FakeMusic:
        async def extract_track(self, link: str, requester: str) -> Track:
            return Track(
                source_query=link,
                title=f"direct-{requester}",
                webpage_url=link,
                requested_by=requester,
            )

        async def extract_tracks(
            self,
            link: str,
            requester: str,
            *,
            max_items: int | None = None,
        ) -> TrackBatch:
            assert "open.spotify.com/playlist/" in link
            assert requester == "tester"
            assert max_items == 10
            return TrackBatch(
                tracks=[
                    Track(
                        source_query="https://open.spotify.com/track/a",
                        title="Musica A",
                        webpage_url="https://open.spotify.com/track/a",
                        requested_by=requester,
                        artist="Artista A",
                        duration_seconds=210,
                    ),
                    Track(
                        source_query="https://open.spotify.com/track/b",
                        title="Musica B",
                        webpage_url="https://open.spotify.com/track/b",
                        requested_by=requester,
                        artist="Artista B",
                        duration_seconds=180,
                    ),
                ],
                total_items=2,
                invalid_items=0,
            )

        async def search_tracks(self, query: str, requester: str, *, limit: int = 5) -> list[Track]:
            return []

        async def extract_recommended_track(self, from_track: Track, requester: str) -> Track:
            return from_track

    async def _run() -> None:
        resolver = MusicResolver(
            FakeMusic(),
            spotify_strict_match=True,
            spotify_match_threshold=0.55,
            spotify_candidate_limit=3,
            spotify_meta_cache_ttl_seconds=60,
            spotify_meta_cache_max_entries=32,
        )
        batch, used_spotify = await resolver.extract_batch_with_spotify_fallback(
            link="https://open.spotify.com/playlist/abc123",
            requester="tester",
            max_items=10,
        )
        assert used_spotify is True
        assert batch.total_items == 2
        assert len(batch.tracks) == 2
        assert batch.tracks[0].source_query.startswith("ytsearch1:")
        assert batch.tracks[0].title == "Musica A"
        assert batch.tracks[1].source_query.startswith("ytsearch1:")
        assert batch.tracks[1].title == "Musica B"
        await resolver.close()

    asyncio.run(_run())


def test_provider_circuit_breaker_blocks_after_failures() -> None:
    async def _run() -> None:
        cog = _build_cog(asyncio.get_running_loop())
        cog.provider_failure_threshold = 1
        cog.provider_recovery_seconds = 999
        cog.provider_half_open_max_calls = 1
        cog._provider_breakers["search"].failure_threshold = 1
        cog._provider_breakers["search"].recovery_seconds = 999

        async def _boom(query: str, requester: str, *, limit: int) -> list[Track]:
            raise RuntimeError(f"boom:{query}:{requester}:{limit}")

        cog.resolver.search_tracks = _boom  # type: ignore[method-assign]
        try:
            await cog._search_tracks_guarded("abc", requester="tester", limit=2)
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected first guarded search to fail")

        try:
            await cog._search_tracks_guarded("abc", requester="tester", limit=2)
        except RuntimeError as exc:
            assert "temporariamente indisponivel" in str(exc).casefold()
        else:
            raise AssertionError("expected breaker to block second call")

    asyncio.run(_run())


def test_command_specific_rate_limits() -> None:
    loop = asyncio.new_event_loop()
    try:
        cog = _build_cog(loop)
        cog.search_user_window_seconds = 10.0
        cog.search_user_max_requests = 1
        cog.search_guild_window_seconds = 10.0
        cog.search_guild_max_requests = 10

        first = cog._check_play_rate_limits(guild_id=1, user_id=1, key="search")
        second = cog._check_play_rate_limits(guild_id=1, user_id=1, key="search")
        assert first == 0.0
        assert second > 0.0
    finally:
        loop.close()


def test_search_cache_returns_stale_when_allowed() -> None:
    loop = asyncio.new_event_loop()
    try:
        cog = _build_cog(loop)
        key = (1, 1, "abc", 3)
        track = Track(
            source_query="ytsearch:abc",
            title="abc",
            webpage_url="https://example.com/abc",
            requested_by="tester",
        )
        cog.search_cache_ttl_seconds = 0.001
        cog.search_cache_stale_ttl_seconds = 10.0
        cog._cache_put_search(key, [track])

        async def _wait() -> None:
            await asyncio.sleep(0.01)

        loop.run_until_complete(_wait())
        cached, stale = cog._cache_get_search(key, allow_stale=True)
        assert cached is not None
        assert stale is True
    finally:
        loop.close()


def test_autocomplete_prefers_ranked_queries() -> None:
    async def _run() -> None:
        cog = _build_cog(asyncio.get_running_loop())
        cog.search_autocomplete_limit = 5

        async def _popular(_guild_id: int, *, prefix: str, limit: int) -> list[str]:
            assert prefix == "so"
            assert limit == 5
            return ["Song Alpha", "Song Beta"]

        cog.store.list_popular_queries = _popular  # type: ignore[method-assign]
        interaction = SimpleNamespace(guild=SimpleNamespace(id=1))
        choices = await cog._play_autocomplete(interaction, "so")
        assert choices
        assert choices[0].value == "Song Alpha"
        assert choices[1].value == "Song Beta"

    asyncio.run(_run())


def test_lavalink_single_track_fallback_marker_consumes_once() -> None:
    loop = asyncio.new_event_loop()
    try:
        cog = _build_cog(loop)
        track = Track(
            source_query="ytsearch:abc",
            title="abc",
            webpage_url="https://example.com/abc",
            requested_by="tester",
        )
        cog._mark_track_ffmpeg_fallback(1, track)
        assert cog._consume_track_ffmpeg_fallback(1, track) is True
        assert cog._consume_track_ffmpeg_fallback(1, track) is False
    finally:
        loop.close()


def test_should_force_fresh_lavalink_session_uses_state_enum() -> None:
    loop = asyncio.new_event_loop()
    try:
        cog = _build_cog(loop)
        cog.player_state.transition(1, PlayerState.IDLE, reason="test")
        cog._is_lavalink_player = lambda _vc: True  # type: ignore[method-assign]
        cog._is_voice_playing = lambda _vc: False  # type: ignore[method-assign]
        cog._is_voice_paused = lambda _vc: False  # type: ignore[method-assign]
        guild = SimpleNamespace(id=1)
        assert cog._should_force_fresh_lavalink_session(guild, SimpleNamespace()) is True
    finally:
        loop.close()


def test_search_command_e2e_loading_then_edit() -> None:
    async def _run() -> None:
        cog = _build_cog(asyncio.get_running_loop())
        cog._record_query = lambda _guild_id, _query: None  # type: ignore[method-assign]
        cog.store.list_popular_queries = lambda *_args, **_kwargs: asyncio.sleep(0, result=[])  # type: ignore[method-assign]

        class FakeResponse:
            def __init__(self) -> None:
                self.done = False
                self.sent = 0

            def is_done(self) -> bool:
                return self.done

            async def send_message(self, **_kwargs: object) -> None:
                self.sent += 1
                self.done = True

        class FakeInteraction:
            def __init__(self) -> None:
                self.id = 123
                self.guild = SimpleNamespace(id=77)
                self.user = SimpleNamespace(id=9, display_name="tester")
                self.response = FakeResponse()
                self.edited = 0

            async def edit_original_response(self, **_kwargs: object) -> None:
                self.edited += 1

        interaction = FakeInteraction()
        cog._search_tracks_guarded = lambda _q, *, requester, limit: asyncio.sleep(  # type: ignore[method-assign]
            0,
            result=[
                Track(
                    source_query="ytsearch:song",
                    title=f"song-{requester}-{limit}",
                    webpage_url="https://example.com/song",
                    requested_by="tester",
                )
            ],
        )
        await cog.search(interaction, "song")
        assert interaction.response.sent == 1
        assert interaction.edited == 1

    asyncio.run(_run())


def test_playlist_pending_detects_partial_extraction_without_playlist_count() -> None:
    loop = asyncio.new_event_loop()
    try:
        cog = _build_cog(loop)
        batch = TrackBatch(
            tracks=[
                Track(
                    source_query=f"ytsearch:track-{index}",
                    title=f"track-{index}",
                    webpage_url=f"https://example.com/{index}",
                    requested_by="tester",
                )
                for index in range(10)
            ],
            total_items=10,
            invalid_items=0,
        )
        assert (
            cog._playlist_has_pending_items(
                query="https://www.youtube.com/playlist?list=PL123",
                batch=batch,
                extraction_limit=10,
            )
            is True
        )
    finally:
        loop.close()


def test_playlist_pending_ignores_non_playlist_queries() -> None:
    loop = asyncio.new_event_loop()
    try:
        cog = _build_cog(loop)
        batch = TrackBatch(
            tracks=[
                Track(
                    source_query="ytsearch:single",
                    title="single",
                    webpage_url="https://example.com/single",
                    requested_by="tester",
                )
            ],
            total_items=1,
            invalid_items=0,
        )
        assert (
            cog._playlist_has_pending_items(
                query="https://www.youtube.com/watch?v=abc",
                batch=batch,
                extraction_limit=10,
            )
            is False
        )
    finally:
        loop.close()


def test_play_command_e2e_enqueues_and_starts() -> None:
    async def _run() -> None:
        cog = _build_cog(asyncio.get_running_loop())
        cog._record_query = lambda _guild_id, _query: None  # type: ignore[method-assign]
        cog.store.record_query_usage = lambda *_args, **_kwargs: asyncio.sleep(0)  # type: ignore[method-assign]
        cog._safe_defer = lambda _i, **_k: asyncio.sleep(0, result=True)  # type: ignore[method-assign]
        cog._ensure_voice = lambda _i: asyncio.sleep(0, result=SimpleNamespace(channel=SimpleNamespace(name="vc")))  # type: ignore[method-assign]
        cog._persist_queue_state = lambda *_a, **_k: asyncio.sleep(0)  # type: ignore[method-assign]
        cog._record_queue_event = lambda *_a, **_k: asyncio.sleep(0)  # type: ignore[method-assign]
        started = {"ok": 0}
        cog._start_next_if_needed = lambda *_a, **_k: asyncio.sleep(0, result=started.__setitem__("ok", 1))  # type: ignore[method-assign]
        cog._send_followup = lambda *_a, **_k: asyncio.sleep(0, result=True)  # type: ignore[method-assign]

        class FakeResponse:
            def is_done(self) -> bool:
                return False

        interaction = SimpleNamespace(
            id=124,
            guild=SimpleNamespace(id=88),
            user=SimpleNamespace(id=10, display_name="tester"),
            response=FakeResponse(),
            channel=SimpleNamespace(id=55),
        )
        track = Track(
            source_query="ytsearch:one",
            title="one",
            webpage_url="https://example.com/one",
            requested_by="tester",
        )
        cog._extract_batch_with_spotify_fallback = lambda **_kwargs: asyncio.sleep(  # type: ignore[method-assign]
            0,
            result=(SimpleNamespace(tracks=[track], total_items=1, invalid_items=0), False),
        )

        await cog.play(interaction, "one song")
        player = await cog._get_player(88)
        assert len(player.snapshot_queue()) == 1
        assert started["ok"] == 1

    asyncio.run(_run())


def test_queue_command_e2e_sends_embed() -> None:
    async def _run() -> None:
        cog = _build_cog(asyncio.get_running_loop())
        sent = {"count": 0}

        async def _send(_interaction: object, **kwargs: object) -> None:
            if "embed" in kwargs:
                sent["count"] += 1

        cog._send_response = _send  # type: ignore[method-assign]
        interaction = SimpleNamespace(guild=SimpleNamespace(id=99), user=SimpleNamespace(id=10))
        await cog.queue(interaction)
        assert sent["count"] == 1

    asyncio.run(_run())


def test_channel_specific_rate_limit() -> None:
    loop = asyncio.new_event_loop()
    try:
        cog = _build_cog(loop)
        cog.rate_limit_channel_window_seconds = 10.0
        cog.rate_limit_channel_max_requests = 1
        first = cog._check_play_rate_limits(guild_id=1, user_id=1, key="play", channel_id=55)
        second = cog._check_play_rate_limits(guild_id=1, user_id=2, key="play", channel_id=55)
        assert first == 0.0
        assert second > 0.0
    finally:
        loop.close()


def test_nowplaying_button_cooldown() -> None:
    loop = asyncio.new_event_loop()
    try:
        cog = _build_cog(loop)
        cog.nowplaying_button_cooldown_seconds = 5.0
        first = cog._check_button_cooldown(guild_id=1, user_id=10, action="np_skip")
        second = cog._check_button_cooldown(guild_id=1, user_id=10, action="np_skip")
        assert first == 0.0
        assert second > 0.0
    finally:
        loop.close()
