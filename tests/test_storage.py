from __future__ import annotations

import asyncio
from pathlib import Path

from botmusica.music.storage import (
    FavoriteTrack,
    GuildSettings,
    NowPlayingStateRecord,
    PlaylistTrack,
    QueueTrack,
    SettingsStore,
    VoteStateRecord,
)


def test_sqlite_persistence(tmp_path: Path) -> None:
    db_path = tmp_path / "botmusica_test.db"
    store = SettingsStore(str(db_path))
    asyncio.run(store.initialize())

    settings = GuildSettings(
        volume=0.75,
        loop_mode="queue",
        autoplay=True,
        stay_connected=True,
        audio_filter="bassboost",
        max_track_duration_seconds=600,
        domain_whitelist="youtube.com,youtu.be",
        domain_blacklist="example.com",
    )
    asyncio.run(store.upsert(123, settings))
    restored = asyncio.run(store.get(123))

    assert restored is not None
    assert restored.volume == 0.75
    assert restored.loop_mode == "queue"
    assert restored.autoplay is True
    assert restored.stay_connected is True
    assert restored.audio_filter == "bassboost"
    assert restored.max_track_duration_seconds == 600
    assert restored.domain_whitelist == "youtube.com,youtu.be"
    assert restored.domain_blacklist == "example.com"


def test_favorites_and_playlists(tmp_path: Path) -> None:
    db_path = tmp_path / "botmusica_test.db"
    store = SettingsStore(str(db_path))
    asyncio.run(store.initialize())

    fav = FavoriteTrack(
        title="Song A",
        source_query="https://example.com/a",
        webpage_url="https://example.com/a",
        duration_seconds=123,
    )
    asyncio.run(store.add_favorite(1, 10, fav))
    favorites = asyncio.run(store.list_favorites(1, 10))
    assert len(favorites) == 1
    assert favorites[0].title == "Song A"

    removed = asyncio.run(store.remove_favorite(1, 10, "https://example.com/a"))
    assert removed == 1
    assert asyncio.run(store.list_favorites(1, 10)) == []

    playlist_tracks = [
        PlaylistTrack(
            title="Track 1",
            source_query="https://example.com/1",
            webpage_url="https://example.com/1",
            duration_seconds=100,
        ),
        PlaylistTrack(
            title="Track 2",
            source_query="https://example.com/2",
            webpage_url="https://example.com/2",
            duration_seconds=200,
        ),
    ]
    asyncio.run(store.save_playlist(1, 10, "mix", playlist_tracks))
    names = asyncio.run(store.list_playlists(1, 10))
    assert names == ["mix"]

    loaded = asyncio.run(store.load_playlist(1, 10, "mix"))
    assert [item.title for item in loaded] == ["Track 1", "Track 2"]

    deleted = asyncio.run(store.delete_playlist(1, 10, "mix"))
    assert deleted == 1


def test_queue_state_persistence(tmp_path: Path) -> None:
    db_path = tmp_path / "botmusica_test.db"
    store = SettingsStore(str(db_path))
    asyncio.run(store.initialize())

    queue_state = [
        QueueTrack(
            title="Now",
            source_query="https://example.com/now",
            webpage_url="https://example.com/now",
            duration_seconds=111,
            requested_by="alice",
        ),
        QueueTrack(
            title="Next",
            source_query="https://example.com/next",
            webpage_url="https://example.com/next",
            duration_seconds=222,
            requested_by="bob",
        ),
    ]
    asyncio.run(store.save_queue_state(99, queue_state))

    loaded = asyncio.run(store.load_queue_state(99))
    assert [item.title for item in loaded] == ["Now", "Next"]
    assert [item.requested_by for item in loaded] == ["alice", "bob"]

    asyncio.run(store.save_queue_state(99, []))
    assert asyncio.run(store.load_queue_state(99)) == []


def test_vote_state_persistence_and_cleanup(tmp_path: Path) -> None:
    db_path = tmp_path / "botmusica_test.db"
    store = SettingsStore(str(db_path))
    asyncio.run(store.initialize())

    record = VoteStateRecord(
        guild_id=55,
        action="skip",
        channel_id=777,
        required_votes=3,
        voters_csv="1,2",
        created_at_unix=1_700_000_000,
    )
    asyncio.run(store.upsert_vote_state(record))

    loaded = asyncio.run(store.get_vote_state(55, "skip"))
    assert loaded is not None
    assert loaded.required_votes == 3
    assert loaded.voters_csv == "1,2"
    assert SettingsStore.voters_from_csv(loaded.voters_csv) == {1, 2}

    removed = asyncio.run(store.cleanup_expired_votes(max_age_seconds=10, now_unix=1_700_000_100))
    assert removed == 1
    assert asyncio.run(store.get_vote_state(55, "skip")) is None


def test_nowplaying_state_persistence(tmp_path: Path) -> None:
    db_path = tmp_path / "botmusica_test.db"
    store = SettingsStore(str(db_path))
    asyncio.run(store.initialize())

    record = NowPlayingStateRecord(guild_id=77, channel_id=888, message_id=999)
    asyncio.run(store.upsert_nowplaying_state(record))

    loaded = asyncio.run(store.get_nowplaying_state(77))
    assert loaded is not None
    assert loaded.channel_id == 888
    assert loaded.message_id == 999

    asyncio.run(store.delete_nowplaying_state(77))
    assert asyncio.run(store.get_nowplaying_state(77)) is None


def test_player_runtime_state_persistence(tmp_path: Path) -> None:
    db_path = tmp_path / "botmusica_test.db"
    store = SettingsStore(str(db_path))
    asyncio.run(store.initialize())

    asyncio.run(store.upsert_player_runtime_state(77, "playing", 1_700_000_000))
    loaded = asyncio.run(store.get_player_runtime_state(77))
    assert loaded is not None
    assert loaded.state == "playing"
    assert loaded.updated_at_unix == 1_700_000_000

    asyncio.run(store.delete_player_runtime_state(77))
    assert asyncio.run(store.get_player_runtime_state(77)) is None


def test_queue_events_persistence_and_prune(tmp_path: Path) -> None:
    db_path = tmp_path / "botmusica_test.db"
    store = SettingsStore(str(db_path))
    asyncio.run(store.initialize())

    for idx in range(140):
        asyncio.run(store.append_queue_event(11, "enqueue", f'{{"idx":{idx}}}'))
    events = asyncio.run(store.list_queue_events(11, limit=3))
    assert len(events) == 3
    assert events[0].action == "enqueue"
    assert '"idx":139' in events[0].details_json

    removed = asyncio.run(store.prune_queue_events(max_rows_per_guild=2))
    assert removed >= 0
    events_after = asyncio.run(store.list_queue_events(11, limit=200))
    assert len(events_after) <= 100


def test_queue_events_batch_insert(tmp_path: Path) -> None:
    db_path = tmp_path / "botmusica_test.db"
    store = SettingsStore(str(db_path))
    asyncio.run(store.initialize())

    asyncio.run(
        store.append_queue_events(
            [
                (11, "enqueue", '{"idx":1}'),
                (11, "enqueue", '{"idx":2}'),
                (11, "skip", '{"idx":3}'),
            ]
        )
    )
    events = asyncio.run(store.list_queue_events(11, limit=10))
    assert len(events) == 3
    assert events[0].action == "skip"
    assert '"idx":2' in events[1].details_json


def test_search_cache_and_query_stats_persistence(tmp_path: Path) -> None:
    db_path = tmp_path / "botmusica_test.db"
    store = SettingsStore(str(db_path))
    asyncio.run(store.initialize())

    payload = '[{"title":"Song A","source_query":"ytsearch:song-a","webpage_url":"https://example.com/a","requested_by":"tester"}]'
    asyncio.run(
        store.upsert_search_cache(
            guild_id=7,
            user_id=10,
            normalized_query="song a",
            result_limit=3,
            payload_json=payload,
            cached_at_unix=1_700_000_000,
        )
    )
    rows = asyncio.run(store.load_recent_search_cache(max_rows=5))
    assert len(rows) == 1
    assert rows[0].normalized_query == "song a"
    assert rows[0].payload_json == payload

    asyncio.run(store.record_query_usage(7, "Song A"))
    asyncio.run(store.record_query_usage(7, "Song B"))
    asyncio.run(store.record_query_usage(7, "Song A"))
    ranked = asyncio.run(store.list_popular_queries(7, prefix="song", limit=3))
    assert ranked[0] == "Song A"
    assert "Song B" in ranked


def test_query_usage_batch_accumulates_counts(tmp_path: Path) -> None:
    db_path = tmp_path / "botmusica_test.db"
    store = SettingsStore(str(db_path))
    asyncio.run(store.initialize())

    asyncio.run(
        store.record_query_usage_batch(
            7,
            ["Song A", "Song B", "Song A", "song a", " "],
        )
    )
    ranked = asyncio.run(store.list_popular_queries(7, prefix="song", limit=5))
    assert ranked[0] == "Song A"
    assert "Song B" in ranked
