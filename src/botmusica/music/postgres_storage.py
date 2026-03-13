from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from typing import Any, Iterable

from botmusica.music.storage import (
    ControlRoomStateRecord,
    FavoriteTrack,
    GuildSettings,
    NowPlayingStateRecord,
    PlayerRuntimeStateRecord,
    PlaylistTrack,
    QueueEventRecord,
    QueueTrack,
    SearchCacheRecord,
    SpotifyResolveCacheRecord,
    VoteStateRecord,
)


class PostgresSettingsStore:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        try:
            import psycopg  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "Backend postgres requer `psycopg[binary]`. "
                "Instale com `pip install -e .[postgres]` "
                "ou `pip install psycopg[binary]`."
            ) from exc
        self._psycopg = psycopg

    @contextmanager
    def _conn(self) -> Any:
        conn = self._psycopg.connect(self.dsn)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS guild_settings (
                        guild_id BIGINT PRIMARY KEY,
                        volume DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                        loop_mode TEXT NOT NULL DEFAULT 'off',
                        autoplay BOOLEAN NOT NULL DEFAULT FALSE,
                        stay_connected BOOLEAN NOT NULL DEFAULT FALSE,
                        audio_filter TEXT NOT NULL DEFAULT 'off',
                        max_track_duration_seconds INTEGER NOT NULL DEFAULT 0,
                        domain_whitelist TEXT NOT NULL DEFAULT '',
                        domain_blacklist TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS user_favorites (
                        guild_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        source_query TEXT NOT NULL,
                        webpage_url TEXT NOT NULL,
                        title TEXT NOT NULL,
                        duration_seconds INTEGER NULL,
                        created_at BIGINT NOT NULL DEFAULT (EXTRACT(EPOCH FROM NOW())::BIGINT),
                        PRIMARY KEY (guild_id, user_id, source_query)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS playlists (
                        guild_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        name TEXT NOT NULL,
                        created_at BIGINT NOT NULL DEFAULT (EXTRACT(EPOCH FROM NOW())::BIGINT),
                        PRIMARY KEY (guild_id, user_id, name)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS playlist_items (
                        guild_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        playlist_name TEXT NOT NULL,
                        position INTEGER NOT NULL,
                        source_query TEXT NOT NULL,
                        webpage_url TEXT NOT NULL,
                        title TEXT NOT NULL,
                        duration_seconds INTEGER NULL,
                        PRIMARY KEY (guild_id, user_id, playlist_name, position)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS guild_queue_state (
                        guild_id BIGINT NOT NULL,
                        position INTEGER NOT NULL,
                        source_query TEXT NOT NULL,
                        webpage_url TEXT NOT NULL,
                        title TEXT NOT NULL,
                        duration_seconds INTEGER NULL,
                        requested_by TEXT NOT NULL,
                        PRIMARY KEY (guild_id, position)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS guild_vote_state (
                        guild_id BIGINT NOT NULL,
                        action TEXT NOT NULL,
                        channel_id BIGINT NOT NULL,
                        required_votes INTEGER NOT NULL,
                        voters_csv TEXT NOT NULL DEFAULT '',
                        created_at_unix BIGINT NOT NULL,
                        PRIMARY KEY (guild_id, action)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS guild_nowplaying_state (
                        guild_id BIGINT PRIMARY KEY,
                        channel_id BIGINT NOT NULL,
                        message_id BIGINT NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS guild_control_room_state (
                        guild_id BIGINT PRIMARY KEY,
                        channel_id BIGINT NOT NULL,
                        message_id BIGINT NOT NULL,
                        operator_user_id BIGINT NOT NULL DEFAULT 0
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS guild_player_runtime_state (
                        guild_id BIGINT PRIMARY KEY,
                        state TEXT NOT NULL,
                        updated_at_unix BIGINT NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS guild_queue_events (
                        id BIGSERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        action TEXT NOT NULL,
                        details_json TEXT NOT NULL DEFAULT '{}',
                        created_at_unix BIGINT NOT NULL DEFAULT (EXTRACT(EPOCH FROM NOW())::BIGINT)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS guild_search_cache (
                        guild_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        normalized_query TEXT NOT NULL,
                        result_limit INTEGER NOT NULL,
                        payload_json TEXT NOT NULL,
                        cached_at_unix BIGINT NOT NULL,
                        PRIMARY KEY (guild_id, user_id, normalized_query, result_limit)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS guild_query_stats (
                        guild_id BIGINT NOT NULL,
                        query TEXT NOT NULL,
                        uses BIGINT NOT NULL DEFAULT 0,
                        last_used_unix BIGINT NOT NULL DEFAULT (EXTRACT(EPOCH FROM NOW())::BIGINT),
                        PRIMARY KEY (guild_id, query)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS spotify_resolve_cache (
                        spotify_track_id TEXT PRIMARY KEY,
                        status TEXT NOT NULL,
                        source_query TEXT NOT NULL DEFAULT '',
                        webpage_url TEXT NOT NULL DEFAULT '',
                        title TEXT NOT NULL DEFAULT '',
                        artist TEXT NOT NULL DEFAULT '',
                        duration_seconds INTEGER NULL,
                        isrc TEXT NOT NULL DEFAULT '',
                        failure_reason TEXT NOT NULL DEFAULT '',
                        cached_at_unix BIGINT NOT NULL
                    )
                    """
                )

    async def get(self, guild_id: int) -> GuildSettings | None:
        return await asyncio.to_thread(self._get_sync, guild_id)

    def _get_sync(self, guild_id: int) -> GuildSettings | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT volume, loop_mode, autoplay, stay_connected, audio_filter, max_track_duration_seconds, domain_whitelist, domain_blacklist
                FROM guild_settings
                WHERE guild_id = %s
                """,
                (guild_id,),
            ).fetchone()
        if row is None:
            return None
        return GuildSettings(
            volume=float(row[0]),
            loop_mode=str(row[1]),
            autoplay=bool(row[2]),
            stay_connected=bool(row[3]),
            audio_filter=str(row[4]),
            max_track_duration_seconds=int(row[5]) if row[5] is not None else 0,
            domain_whitelist=str(row[6] or ""),
            domain_blacklist=str(row[7] or ""),
        )

    async def upsert(self, guild_id: int, settings: GuildSettings) -> None:
        await asyncio.to_thread(self._upsert_sync, guild_id, settings)

    def _upsert_sync(self, guild_id: int, settings: GuildSettings) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO guild_settings
                (guild_id, volume, loop_mode, autoplay, stay_connected, audio_filter, max_track_duration_seconds, domain_whitelist, domain_blacklist)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(guild_id) DO UPDATE SET
                    volume = excluded.volume,
                    loop_mode = excluded.loop_mode,
                    autoplay = excluded.autoplay,
                    stay_connected = excluded.stay_connected,
                    audio_filter = excluded.audio_filter,
                    max_track_duration_seconds = excluded.max_track_duration_seconds,
                    domain_whitelist = excluded.domain_whitelist,
                    domain_blacklist = excluded.domain_blacklist
                """,
                (
                    guild_id,
                    settings.volume,
                    settings.loop_mode,
                    bool(settings.autoplay),
                    bool(settings.stay_connected),
                    settings.audio_filter,
                    int(settings.max_track_duration_seconds),
                    settings.domain_whitelist,
                    settings.domain_blacklist,
                ),
            )

    async def add_favorite(self, guild_id: int, user_id: int, track: FavoriteTrack) -> None:
        await asyncio.to_thread(self._add_favorite_sync, guild_id, user_id, track)

    def _add_favorite_sync(self, guild_id: int, user_id: int, track: FavoriteTrack) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO user_favorites
                (guild_id, user_id, source_query, webpage_url, title, duration_seconds)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(guild_id, user_id, source_query) DO UPDATE SET
                    webpage_url = excluded.webpage_url,
                    title = excluded.title,
                    duration_seconds = excluded.duration_seconds
                """,
                (guild_id, user_id, track.source_query, track.webpage_url, track.title, track.duration_seconds),
            )

    async def list_favorites(self, guild_id: int, user_id: int) -> list[FavoriteTrack]:
        return await asyncio.to_thread(self._list_favorites_sync, guild_id, user_id)

    def _list_favorites_sync(self, guild_id: int, user_id: int) -> list[FavoriteTrack]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT title, source_query, webpage_url, duration_seconds
                FROM user_favorites
                WHERE guild_id = %s AND user_id = %s
                ORDER BY created_at DESC
                """,
                (guild_id, user_id),
            ).fetchall()
        return [FavoriteTrack(title=row[0], source_query=row[1], webpage_url=row[2], duration_seconds=row[3]) for row in rows]

    async def remove_favorite(self, guild_id: int, user_id: int, source_query: str) -> int:
        return await asyncio.to_thread(self._remove_favorite_sync, guild_id, user_id, source_query)

    def _remove_favorite_sync(self, guild_id: int, user_id: int, source_query: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """
                DELETE FROM user_favorites
                WHERE guild_id = %s AND user_id = %s AND source_query = %s
                """,
                (guild_id, user_id, source_query),
            )
            return int(cur.rowcount)

    async def save_playlist(self, guild_id: int, user_id: int, name: str, tracks: list[PlaylistTrack]) -> None:
        await asyncio.to_thread(self._save_playlist_sync, guild_id, user_id, name, tracks)

    def _save_playlist_sync(self, guild_id: int, user_id: int, name: str, tracks: list[PlaylistTrack]) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO playlists (guild_id, user_id, name)
                VALUES (%s, %s, %s)
                ON CONFLICT (guild_id, user_id, name) DO UPDATE SET name = excluded.name
                """,
                (guild_id, user_id, name),
            )
            conn.execute(
                """
                DELETE FROM playlist_items
                WHERE guild_id = %s AND user_id = %s AND playlist_name = %s
                """,
                (guild_id, user_id, name),
            )
            for idx, track in enumerate(tracks, start=1):
                conn.execute(
                    """
                    INSERT INTO playlist_items
                    (guild_id, user_id, playlist_name, position, source_query, webpage_url, title, duration_seconds)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (guild_id, user_id, name, idx, track.source_query, track.webpage_url, track.title, track.duration_seconds),
                )

    async def list_playlists(self, guild_id: int, user_id: int) -> list[str]:
        return await asyncio.to_thread(self._list_playlists_sync, guild_id, user_id)

    def _list_playlists_sync(self, guild_id: int, user_id: int) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT name
                FROM playlists
                WHERE guild_id = %s AND user_id = %s
                ORDER BY created_at DESC
                """,
                (guild_id, user_id),
            ).fetchall()
        return [str(row[0]) for row in rows]

    async def load_playlist(self, guild_id: int, user_id: int, name: str) -> list[PlaylistTrack]:
        return await asyncio.to_thread(self._load_playlist_sync, guild_id, user_id, name)

    def _load_playlist_sync(self, guild_id: int, user_id: int, name: str) -> list[PlaylistTrack]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT title, source_query, webpage_url, duration_seconds
                FROM playlist_items
                WHERE guild_id = %s AND user_id = %s AND playlist_name = %s
                ORDER BY position ASC
                """,
                (guild_id, user_id, name),
            ).fetchall()
        return [PlaylistTrack(title=row[0], source_query=row[1], webpage_url=row[2], duration_seconds=row[3]) for row in rows]

    async def delete_playlist(self, guild_id: int, user_id: int, name: str) -> int:
        return await asyncio.to_thread(self._delete_playlist_sync, guild_id, user_id, name)

    def _delete_playlist_sync(self, guild_id: int, user_id: int, name: str) -> int:
        with self._conn() as conn:
            conn.execute(
                """
                DELETE FROM playlist_items
                WHERE guild_id = %s AND user_id = %s AND playlist_name = %s
                """,
                (guild_id, user_id, name),
            )
            cur = conn.execute(
                """
                DELETE FROM playlists
                WHERE guild_id = %s AND user_id = %s AND name = %s
                """,
                (guild_id, user_id, name),
            )
            return int(cur.rowcount)

    async def save_queue_state(self, guild_id: int, tracks: list[QueueTrack]) -> None:
        await asyncio.to_thread(self._save_queue_state_sync, guild_id, tracks)

    def _save_queue_state_sync(self, guild_id: int, tracks: list[QueueTrack]) -> None:
        with self._conn() as conn:
            max_position = 0
            for idx, track in enumerate(tracks, start=1):
                max_position = idx
                conn.execute(
                    """
                    INSERT INTO guild_queue_state
                    (guild_id, position, source_query, webpage_url, title, duration_seconds, requested_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(guild_id, position) DO UPDATE SET
                        source_query = excluded.source_query,
                        webpage_url = excluded.webpage_url,
                        title = excluded.title,
                        duration_seconds = excluded.duration_seconds,
                        requested_by = excluded.requested_by
                    """,
                    (guild_id, idx, track.source_query, track.webpage_url, track.title, track.duration_seconds, track.requested_by),
                )
            if max_position > 0:
                conn.execute(
                    "DELETE FROM guild_queue_state WHERE guild_id = %s AND position > %s",
                    (guild_id, max_position),
                )
            else:
                conn.execute("DELETE FROM guild_queue_state WHERE guild_id = %s", (guild_id,))

    async def load_queue_state(self, guild_id: int) -> list[QueueTrack]:
        return await asyncio.to_thread(self._load_queue_state_sync, guild_id)

    def _load_queue_state_sync(self, guild_id: int) -> list[QueueTrack]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT title, source_query, webpage_url, duration_seconds, requested_by
                FROM guild_queue_state
                WHERE guild_id = %s
                ORDER BY position ASC
                """,
                (guild_id,),
            ).fetchall()
        return [QueueTrack(title=row[0], source_query=row[1], webpage_url=row[2], duration_seconds=row[3], requested_by=row[4]) for row in rows]

    async def upsert_vote_state(self, record: VoteStateRecord) -> None:
        await asyncio.to_thread(self._upsert_vote_state_sync, record)

    def _upsert_vote_state_sync(self, record: VoteStateRecord) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO guild_vote_state
                (guild_id, action, channel_id, required_votes, voters_csv, created_at_unix)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(guild_id, action) DO UPDATE SET
                    channel_id = excluded.channel_id,
                    required_votes = excluded.required_votes,
                    voters_csv = excluded.voters_csv,
                    created_at_unix = excluded.created_at_unix
                """,
                (record.guild_id, record.action, record.channel_id, record.required_votes, record.voters_csv, record.created_at_unix),
            )

    async def get_vote_state(self, guild_id: int, action: str) -> VoteStateRecord | None:
        return await asyncio.to_thread(self._get_vote_state_sync, guild_id, action)

    def _get_vote_state_sync(self, guild_id: int, action: str) -> VoteStateRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT guild_id, action, channel_id, required_votes, voters_csv, created_at_unix
                FROM guild_vote_state
                WHERE guild_id = %s AND action = %s
                """,
                (guild_id, action),
            ).fetchone()
        if row is None:
            return None
        return VoteStateRecord(
            guild_id=int(row[0]),
            action=str(row[1]),
            channel_id=int(row[2]),
            required_votes=int(row[3]),
            voters_csv=str(row[4] or ""),
            created_at_unix=int(row[5]),
        )

    async def delete_vote_state(self, guild_id: int, action: str) -> None:
        await asyncio.to_thread(self._delete_vote_state_sync, guild_id, action)

    def _delete_vote_state_sync(self, guild_id: int, action: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM guild_vote_state WHERE guild_id = %s AND action = %s", (guild_id, action))

    async def cleanup_expired_votes(self, *, max_age_seconds: int, now_unix: int) -> int:
        return await asyncio.to_thread(self._cleanup_expired_votes_sync, max_age_seconds, now_unix)

    def _cleanup_expired_votes_sync(self, max_age_seconds: int, now_unix: int) -> int:
        cutoff = now_unix - max_age_seconds
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM guild_vote_state WHERE created_at_unix < %s", (cutoff,))
            return int(cur.rowcount)

    async def upsert_nowplaying_state(self, record: NowPlayingStateRecord) -> None:
        await asyncio.to_thread(self._upsert_nowplaying_state_sync, record)

    def _upsert_nowplaying_state_sync(self, record: NowPlayingStateRecord) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO guild_nowplaying_state (guild_id, channel_id, message_id)
                VALUES (%s, %s, %s)
                ON CONFLICT(guild_id) DO UPDATE SET
                    channel_id = excluded.channel_id,
                    message_id = excluded.message_id
                """,
                (record.guild_id, record.channel_id, record.message_id),
            )

    async def get_nowplaying_state(self, guild_id: int) -> NowPlayingStateRecord | None:
        return await asyncio.to_thread(self._get_nowplaying_state_sync, guild_id)

    def _get_nowplaying_state_sync(self, guild_id: int) -> NowPlayingStateRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT guild_id, channel_id, message_id
                FROM guild_nowplaying_state
                WHERE guild_id = %s
                """,
                (guild_id,),
            ).fetchone()
        if row is None:
            return None
        return NowPlayingStateRecord(guild_id=int(row[0]), channel_id=int(row[1]), message_id=int(row[2]))

    async def delete_nowplaying_state(self, guild_id: int) -> None:
        await asyncio.to_thread(self._delete_nowplaying_state_sync, guild_id)

    def _delete_nowplaying_state_sync(self, guild_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM guild_nowplaying_state WHERE guild_id = %s", (guild_id,))

    async def upsert_control_room_state(self, record: ControlRoomStateRecord) -> None:
        await asyncio.to_thread(self._upsert_control_room_state_sync, record)

    def _upsert_control_room_state_sync(self, record: ControlRoomStateRecord) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO guild_control_room_state (guild_id, channel_id, message_id, operator_user_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT(guild_id) DO UPDATE SET
                    channel_id = excluded.channel_id,
                    message_id = excluded.message_id,
                    operator_user_id = excluded.operator_user_id
                """,
                (record.guild_id, record.channel_id, record.message_id, record.operator_user_id),
            )

    async def get_control_room_state(self, guild_id: int) -> ControlRoomStateRecord | None:
        return await asyncio.to_thread(self._get_control_room_state_sync, guild_id)

    def _get_control_room_state_sync(self, guild_id: int) -> ControlRoomStateRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT guild_id, channel_id, message_id, operator_user_id
                FROM guild_control_room_state
                WHERE guild_id = %s
                """,
                (guild_id,),
            ).fetchone()
        if row is None:
            return None
        return ControlRoomStateRecord(
            guild_id=int(row[0]),
            channel_id=int(row[1]),
            message_id=int(row[2]),
            operator_user_id=int(row[3]),
        )

    async def list_control_room_states(self) -> list[ControlRoomStateRecord]:
        return await asyncio.to_thread(self._list_control_room_states_sync)

    def _list_control_room_states_sync(self) -> list[ControlRoomStateRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT guild_id, channel_id, message_id, operator_user_id
                FROM guild_control_room_state
                """
            ).fetchall()
        return [
            ControlRoomStateRecord(
                guild_id=int(row[0]),
                channel_id=int(row[1]),
                message_id=int(row[2]),
                operator_user_id=int(row[3]),
            )
            for row in rows
        ]

    async def delete_control_room_state(self, guild_id: int) -> None:
        await asyncio.to_thread(self._delete_control_room_state_sync, guild_id)

    def _delete_control_room_state_sync(self, guild_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM guild_control_room_state WHERE guild_id = %s", (guild_id,))

    async def upsert_player_runtime_state(self, guild_id: int, state: str, updated_at_unix: int) -> None:
        await asyncio.to_thread(self._upsert_player_runtime_state_sync, guild_id, state, updated_at_unix)

    def _upsert_player_runtime_state_sync(self, guild_id: int, state: str, updated_at_unix: int) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO guild_player_runtime_state (guild_id, state, updated_at_unix)
                VALUES (%s, %s, %s)
                ON CONFLICT(guild_id) DO UPDATE SET
                    state = excluded.state,
                    updated_at_unix = excluded.updated_at_unix
                """,
                (guild_id, state, updated_at_unix),
            )

    async def get_player_runtime_state(self, guild_id: int) -> PlayerRuntimeStateRecord | None:
        return await asyncio.to_thread(self._get_player_runtime_state_sync, guild_id)

    def _get_player_runtime_state_sync(self, guild_id: int) -> PlayerRuntimeStateRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT guild_id, state, updated_at_unix
                FROM guild_player_runtime_state
                WHERE guild_id = %s
                """,
                (guild_id,),
            ).fetchone()
        if row is None:
            return None
        return PlayerRuntimeStateRecord(guild_id=int(row[0]), state=str(row[1]), updated_at_unix=int(row[2]))

    async def delete_player_runtime_state(self, guild_id: int) -> None:
        await asyncio.to_thread(self._delete_player_runtime_state_sync, guild_id)

    def _delete_player_runtime_state_sync(self, guild_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM guild_player_runtime_state WHERE guild_id = %s", (guild_id,))

    async def append_queue_event(self, guild_id: int, action: str, details_json: str) -> None:
        await asyncio.to_thread(self._append_queue_event_sync, guild_id, action, details_json)

    def _append_queue_event_sync(self, guild_id: int, action: str, details_json: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO guild_queue_events (guild_id, action, details_json)
                VALUES (%s, %s, %s)
                """,
                (guild_id, action, details_json),
            )

    async def append_queue_events(self, rows: list[tuple[int, str, str]]) -> None:
        await asyncio.to_thread(self._append_queue_events_sync, rows)

    def _append_queue_events_sync(self, rows: list[tuple[int, str, str]]) -> None:
        if not rows:
            return
        payload = [(int(gid), str(action), str(details)) for gid, action, details in rows]
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO guild_queue_events (guild_id, action, details_json)
                    VALUES (%s, %s, %s)
                    """,
                    payload,
                )

    async def list_queue_events(self, guild_id: int, *, limit: int = 100) -> list[QueueEventRecord]:
        return await asyncio.to_thread(self._list_queue_events_sync, guild_id, limit)

    def _list_queue_events_sync(self, guild_id: int, limit: int) -> list[QueueEventRecord]:
        safe_limit = max(min(int(limit), 500), 1)
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, guild_id, action, details_json, created_at_unix
                FROM guild_queue_events
                WHERE guild_id = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (guild_id, safe_limit),
            ).fetchall()
        return [QueueEventRecord(id=int(r[0]), guild_id=int(r[1]), action=str(r[2]), details_json=str(r[3] or "{}"), created_at_unix=int(r[4])) for r in rows]

    async def prune_queue_events(self, *, max_rows_per_guild: int = 2000) -> int:
        return await asyncio.to_thread(self._prune_queue_events_sync, max_rows_per_guild)

    def _prune_queue_events_sync(self, max_rows_per_guild: int) -> int:
        safe_limit = max(int(max_rows_per_guild), 100)
        with self._conn() as conn:
            cur = conn.execute(
                """
                WITH ranked AS (
                    SELECT id, guild_id, ROW_NUMBER() OVER (PARTITION BY guild_id ORDER BY id DESC) AS rn
                    FROM guild_queue_events
                )
                DELETE FROM guild_queue_events q
                USING ranked r
                WHERE q.id = r.id AND r.rn > %s
                """,
                (safe_limit,),
            )
            return int(cur.rowcount)

    async def upsert_search_cache(
        self,
        *,
        guild_id: int,
        user_id: int,
        normalized_query: str,
        result_limit: int,
        payload_json: str,
        cached_at_unix: int | None = None,
    ) -> None:
        await asyncio.to_thread(
            self._upsert_search_cache_sync,
            guild_id,
            user_id,
            normalized_query,
            result_limit,
            payload_json,
            cached_at_unix,
        )

    def _upsert_search_cache_sync(
        self,
        guild_id: int,
        user_id: int,
        normalized_query: str,
        result_limit: int,
        payload_json: str,
        cached_at_unix: int | None,
    ) -> None:
        query = normalized_query.strip()
        if not query:
            return
        payload = payload_json.strip() or "[]"
        when = int(cached_at_unix) if cached_at_unix is not None else int(time.time())
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO guild_search_cache
                (guild_id, user_id, normalized_query, result_limit, payload_json, cached_at_unix)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(guild_id, user_id, normalized_query, result_limit) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    cached_at_unix = excluded.cached_at_unix
                """,
                (int(guild_id), int(user_id), query, max(int(result_limit), 1), payload, when),
            )

    async def load_recent_search_cache(self, *, max_rows: int = 1500) -> list[SearchCacheRecord]:
        return await asyncio.to_thread(self._load_recent_search_cache_sync, max_rows)

    def _load_recent_search_cache_sync(self, max_rows: int) -> list[SearchCacheRecord]:
        safe_limit = max(min(int(max_rows), 10000), 1)
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT guild_id, user_id, normalized_query, result_limit, payload_json, cached_at_unix
                FROM guild_search_cache
                ORDER BY cached_at_unix DESC
                LIMIT %s
                """,
                (safe_limit,),
            ).fetchall()
        return [
            SearchCacheRecord(
                guild_id=int(r[0]),
                user_id=int(r[1]),
                normalized_query=str(r[2]),
                result_limit=max(int(r[3]), 1),
                payload_json=str(r[4] or "[]"),
                cached_at_unix=int(r[5]),
            )
            for r in rows
        ]

    async def prune_search_cache(self, *, max_age_seconds: int = 3600) -> int:
        return await asyncio.to_thread(self._prune_search_cache_sync, max_age_seconds)

    def _prune_search_cache_sync(self, max_age_seconds: int) -> int:
        ttl = max(int(max_age_seconds), 60)
        cutoff = int(time.time()) - ttl
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM guild_search_cache WHERE cached_at_unix < %s", (cutoff,))
            return int(cur.rowcount)

    async def get_spotify_resolve_cache(self, spotify_track_id: str) -> SpotifyResolveCacheRecord | None:
        return await asyncio.to_thread(self._get_spotify_resolve_cache_sync, spotify_track_id)

    def _get_spotify_resolve_cache_sync(self, spotify_track_id: str) -> SpotifyResolveCacheRecord | None:
        spotify_id = spotify_track_id.strip()
        if not spotify_id:
            return None
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT
                    spotify_track_id,
                    status,
                    source_query,
                    webpage_url,
                    title,
                    artist,
                    duration_seconds,
                    isrc,
                    failure_reason,
                    cached_at_unix
                FROM spotify_resolve_cache
                WHERE spotify_track_id = %s
                """,
                (spotify_id,),
            ).fetchone()
        if row is None:
            return None
        return SpotifyResolveCacheRecord(
            spotify_track_id=str(row[0]),
            status=str(row[1] or "miss"),
            source_query=str(row[2] or ""),
            webpage_url=str(row[3] or ""),
            title=str(row[4] or ""),
            artist=str(row[5] or ""),
            duration_seconds=int(row[6]) if row[6] is not None else None,
            isrc=str(row[7] or ""),
            failure_reason=str(row[8] or ""),
            cached_at_unix=int(row[9]),
        )

    async def upsert_spotify_resolve_cache(
        self,
        *,
        spotify_track_id: str,
        status: str,
        source_query: str = "",
        webpage_url: str = "",
        title: str = "",
        artist: str = "",
        duration_seconds: int | None = None,
        isrc: str = "",
        failure_reason: str = "",
        cached_at_unix: int | None = None,
    ) -> None:
        await asyncio.to_thread(
            self._upsert_spotify_resolve_cache_sync,
            spotify_track_id,
            status,
            source_query,
            webpage_url,
            title,
            artist,
            duration_seconds,
            isrc,
            failure_reason,
            cached_at_unix,
        )

    def _upsert_spotify_resolve_cache_sync(
        self,
        spotify_track_id: str,
        status: str,
        source_query: str,
        webpage_url: str,
        title: str,
        artist: str,
        duration_seconds: int | None,
        isrc: str,
        failure_reason: str,
        cached_at_unix: int | None,
    ) -> None:
        spotify_id = spotify_track_id.strip()
        cache_status = status.strip().casefold() or "miss"
        if not spotify_id:
            return
        when = int(cached_at_unix) if cached_at_unix is not None else int(time.time())
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO spotify_resolve_cache (
                    spotify_track_id,
                    status,
                    source_query,
                    webpage_url,
                    title,
                    artist,
                    duration_seconds,
                    isrc,
                    failure_reason,
                    cached_at_unix
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(spotify_track_id) DO UPDATE SET
                    status = excluded.status,
                    source_query = excluded.source_query,
                    webpage_url = excluded.webpage_url,
                    title = excluded.title,
                    artist = excluded.artist,
                    duration_seconds = excluded.duration_seconds,
                    isrc = excluded.isrc,
                    failure_reason = excluded.failure_reason,
                    cached_at_unix = excluded.cached_at_unix
                """,
                (
                    spotify_id,
                    cache_status,
                    source_query.strip(),
                    webpage_url.strip(),
                    title.strip(),
                    artist.strip(),
                    int(duration_seconds) if duration_seconds is not None else None,
                    isrc.strip(),
                    failure_reason.strip(),
                    when,
                ),
            )

    async def prune_spotify_resolve_cache(self, *, max_age_seconds: int = 604800) -> int:
        return await asyncio.to_thread(self._prune_spotify_resolve_cache_sync, max_age_seconds)

    def _prune_spotify_resolve_cache_sync(self, max_age_seconds: int) -> int:
        ttl = max(int(max_age_seconds), 60)
        cutoff = int(time.time()) - ttl
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM spotify_resolve_cache WHERE cached_at_unix < %s", (cutoff,))
            return int(cur.rowcount)

    async def record_query_usage(self, guild_id: int, query: str) -> None:
        await asyncio.to_thread(self._record_query_usage_sync, guild_id, query)

    def _record_query_usage_sync(self, guild_id: int, query: str) -> None:
        value = " ".join(query.strip().split())
        if not value:
            return
        now_unix = int(time.time())
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO guild_query_stats (guild_id, query, uses, last_used_unix)
                VALUES (%s, %s, 1, %s)
                ON CONFLICT(guild_id, query) DO UPDATE SET
                    uses = guild_query_stats.uses + 1,
                    last_used_unix = excluded.last_used_unix
                """,
                (int(guild_id), value, now_unix),
            )

    async def record_query_usage_batch(self, guild_id: int, queries: list[str]) -> None:
        await asyncio.to_thread(self._record_query_usage_batch_sync, guild_id, queries)

    def _record_query_usage_batch_sync(self, guild_id: int, queries: list[str]) -> None:
        if not queries:
            return
        normalized: dict[str, int] = {}
        for query in queries:
            value = " ".join(query.strip().split())
            if not value:
                continue
            normalized[value] = normalized.get(value, 0) + 1
        if not normalized:
            return
        now_unix = int(time.time())
        with self._conn() as conn:
            for value, count in normalized.items():
                conn.execute(
                    """
                    INSERT INTO guild_query_stats (guild_id, query, uses, last_used_unix)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT(guild_id, query) DO UPDATE SET
                        uses = guild_query_stats.uses + excluded.uses,
                        last_used_unix = excluded.last_used_unix
                    """,
                    (int(guild_id), value, int(count), now_unix),
                )

    async def list_popular_queries(self, guild_id: int, *, prefix: str, limit: int = 10) -> list[str]:
        return await asyncio.to_thread(self._list_popular_queries_sync, guild_id, prefix, limit)

    def _list_popular_queries_sync(self, guild_id: int, prefix: str, limit: int) -> list[str]:
        safe_limit = max(min(int(limit), 50), 1)
        normalized = prefix.strip().casefold()
        with self._conn() as conn:
            if normalized:
                like_value = f"%{normalized}%"
                rows = conn.execute(
                    """
                    SELECT query
                    FROM guild_query_stats
                    WHERE guild_id = %s AND lower(query) LIKE %s
                    ORDER BY uses DESC, last_used_unix DESC
                    LIMIT %s
                    """,
                    (int(guild_id), like_value, safe_limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT query
                    FROM guild_query_stats
                    WHERE guild_id = %s
                    ORDER BY uses DESC, last_used_unix DESC
                    LIMIT %s
                    """,
                    (int(guild_id), safe_limit),
                ).fetchall()
        return [str(r[0]) for r in rows if r and r[0]]

    @staticmethod
    def voters_to_csv(voters: Iterable[int]) -> str:
        return ",".join(str(item) for item in sorted(set(voters)))

    @staticmethod
    def voters_from_csv(value: str) -> set[int]:
        out: set[int] = set()
        for token in value.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                out.add(int(token))
            except ValueError:
                continue
        return out
