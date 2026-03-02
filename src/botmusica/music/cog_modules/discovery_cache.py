from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from collections import deque
from typing import Any

import discord
from aiohttp import ClientError, ClientSession, ClientTimeout

from botmusica.music.player import GuildPlayer, Track
from botmusica.music.views import NowPlayingView

LOGGER = logging.getLogger("botmusica.music")


class DiscoveryCacheMixin:
    async def _clear_nowplaying_message(self, guild_id: int) -> None:
        message = self.nowplaying.messages.get(guild_id)
        self._cancel_nowplaying_updater(guild_id)
        if message is not None:
            try:
                await message.delete()
            except Exception:
                pass
        self.nowplaying.forget(guild_id)
        await self.store.delete_nowplaying_state(guild_id)

    def _record_query(self, guild_id: int, query: str) -> None:
        value = query.strip()
        if not value:
            return
        history = self._query_history[guild_id]
        lowered = value.casefold()
        deduped = [item for item in history if item.casefold() != lowered]
        history.clear()
        history.extendleft(reversed(deduped))
        history.append(value)
        self._autocomplete_rank_cache.pop((guild_id, "", max(self.search_autocomplete_limit, 1)), None)
        pending = self._pending_query_usage.setdefault(guild_id, [])
        pending.append(value)
        if len(pending) >= self.batch_write_max_items:
            self._schedule_query_usage_flush(immediate=True)
        else:
            self._schedule_query_usage_flush()

    def _schedule_query_usage_flush(self, *, immediate: bool = False) -> None:
        task = self._query_usage_flush_task
        if task and not task.done():
            return

        async def worker() -> None:
            if not immediate:
                await asyncio.sleep(self.batch_write_interval_seconds)
            await self._flush_query_usage_batch()

        self._query_usage_flush_task = self.bot.loop.create_task(worker())

    async def _flush_query_usage_batch(self) -> None:
        if not self._pending_query_usage:
            return
        async with self._query_usage_flush_lock:
            items = self._pending_query_usage
            self._pending_query_usage = {}
        for guild_id, queries in items.items():
            if not queries:
                continue
            task = self.bot.loop.create_task(self.store.record_query_usage_batch(guild_id, queries))
            self._query_usage_write_tasks.add(task)
            task.add_done_callback(self._query_usage_write_tasks.discard)

    def _check_cooldown(self, user_id: int, key: str, cooldown_seconds: float) -> float:
        if cooldown_seconds <= 0:
            return 0.0
        now = time.monotonic()
        slot = (user_id, key)
        expires_at = self._cooldowns.get(slot, 0.0)
        if now < expires_at:
            return expires_at - now
        self._cooldowns[slot] = now + cooldown_seconds
        return 0.0

    def _check_button_cooldown(self, *, guild_id: int, user_id: int, action: str) -> float:
        if self.nowplaying_button_cooldown_seconds <= 0:
            return 0.0
        now = time.monotonic()
        key = (guild_id, user_id, action)
        expires_at = self._interaction_button_cooldowns.get(key, 0.0)
        if now < expires_at:
            return expires_at - now
        self._interaction_button_cooldowns[key] = now + self.nowplaying_button_cooldown_seconds
        return 0.0

    @staticmethod
    def _enforce_window(bucket: deque[float], *, window_seconds: float, max_requests: int) -> float:
        if window_seconds <= 0 or max_requests <= 0:
            return 0.0
        now = time.monotonic()
        while bucket and (now - bucket[0]) > window_seconds:
            bucket.popleft()
        if len(bucket) >= max_requests:
            return max(window_seconds - (now - bucket[0]), 0.0)
        bucket.append(now)
        return 0.0

    def _check_play_rate_limits(self, *, guild_id: int, user_id: int, key: str, channel_id: int = 0) -> float:
        user_window_seconds = self.play_user_window_seconds
        user_max_requests = self.play_user_max_requests
        guild_window_seconds = self.play_guild_window_seconds
        guild_max_requests = self.play_guild_max_requests
        if key == "search":
            user_window_seconds = self.search_user_window_seconds
            user_max_requests = self.search_user_max_requests
            guild_window_seconds = self.search_guild_window_seconds
            guild_max_requests = self.search_guild_max_requests
        elif key == "playlist_load":
            user_window_seconds = self.playlist_load_user_window_seconds
            user_max_requests = self.playlist_load_user_max_requests
            guild_window_seconds = self.playlist_load_guild_window_seconds
            guild_max_requests = self.playlist_load_guild_max_requests

        user_bucket = self._rate_user[(user_id, key)]
        left = self._enforce_window(
            user_bucket,
            window_seconds=user_window_seconds,
            max_requests=user_max_requests,
        )
        if left > 0:
            return left

        guild_bucket = self._rate_guild[(guild_id, key)]
        left = self._enforce_window(
            guild_bucket,
            window_seconds=guild_window_seconds,
            max_requests=guild_max_requests,
        )
        if left > 0:
            return left
        if channel_id > 0 and self.rate_limit_channel_window_seconds > 0 and self.rate_limit_channel_max_requests > 0:
            channel_bucket = self._rate_channel[(channel_id, key)]
            left = self._enforce_window(
                channel_bucket,
                window_seconds=self.rate_limit_channel_window_seconds,
                max_requests=self.rate_limit_channel_max_requests,
            )
        return left

    @staticmethod
    def _structured_value(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        text = str(value).replace("\n", " ").strip()
        text = re.sub(r"\s+", " ", text)
        return text or "-"

    def _log_event(self, event: str, **fields: Any) -> None:
        payload = " ".join(f"{k}={self._structured_value(v)}" for k, v in fields.items())
        LOGGER.info("event=%s %s", event, payload)

    def _maybe_profile(self, event: str, **fields: Any) -> None:
        ratio = max(min(self.profiler_sample_ratio, 1.0), 0.0)
        if ratio <= 0:
            return
        if random.random() > ratio:
            return
        self._log_event(f"profile_{event}", **fields)

    async def _record_queue_event(self, guild_id: int, action: str, **details: Any) -> None:
        payload = (guild_id, action, json.dumps(details, ensure_ascii=True, separators=(",", ":")))
        self._pending_queue_events.append(payload)
        if len(self._pending_queue_events) >= self.batch_write_max_items:
            await self._flush_queue_events_batch()
            return
        self._schedule_queue_events_flush()

    def _schedule_queue_events_flush(self) -> None:
        task = self._queue_event_flush_task
        if task and not task.done():
            return

        async def worker() -> None:
            await asyncio.sleep(self.batch_write_interval_seconds)
            await self._flush_queue_events_batch()

        self._queue_event_flush_task = self.bot.loop.create_task(worker())

    async def _flush_queue_events_batch(self) -> None:
        if not self._pending_queue_events:
            return
        async with self._queue_event_flush_lock:
            rows = self._pending_queue_events
            self._pending_queue_events = []
        try:
            await self.store.append_queue_events(rows)
        except Exception:
            LOGGER.debug("Falha ao gravar batch de eventos de fila (%s itens)", len(rows), exc_info=True)

    @staticmethod
    def _normalize_search_query(query: str) -> str:
        return re.sub(r"\s+", " ", query.strip().casefold())

    def _cache_get_search(self, key: tuple[int, int, str, int], *, allow_stale: bool = False) -> tuple[list[Track] | None, bool]:
        if self.search_cache_ttl_seconds <= 0:
            self._metrics["search_cache_miss"] += 1
            return None, False
        cached = self._search_cache.get(key)
        if cached is None:
            self._metrics["search_cache_miss"] += 1
            return None, False
        expires_at, cached_at, tracks = cached
        now = time.monotonic()
        if expires_at >= now:
            self._search_cache.move_to_end(key)
            self._metrics["search_cache_hit"] += 1
            return tracks, False
        if allow_stale and self.search_cache_stale_ttl_seconds > 0 and (now - cached_at) <= self.search_cache_stale_ttl_seconds:
            self._search_cache.move_to_end(key)
            self._metrics["search_cache_stale_hit"] += 1
            return tracks, True
        self._search_cache.pop(key, None)
        self._metrics["search_cache_miss"] += 1
        return None, False

    def _cache_put_search(self, key: tuple[int, int, str, int], tracks: list[Track]) -> None:
        if self.search_cache_ttl_seconds <= 0 or self.search_cache_max_entries < 1:
            return
        now = time.monotonic()
        self._search_cache[key] = (now + self.search_cache_ttl_seconds, now, tracks)
        self._search_cache.move_to_end(key)
        while len(self._search_cache) > self.search_cache_max_entries:
            self._search_cache.popitem(last=False)
        self._persist_search_cache_entry(key, tracks)

    def _serialize_tracks_for_cache(self, tracks: list[Track]) -> str:
        payload = [
            {
                "source_query": track.source_query,
                "title": track.title,
                "webpage_url": track.webpage_url,
                "requested_by": track.requested_by,
                "artist": track.artist,
                "duration_seconds": track.duration_seconds,
            }
            for track in tracks
        ]
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))

    @staticmethod
    def _deserialize_tracks_from_cache(payload_json: str) -> list[Track]:
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        out: list[Track] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            source_query = str(item.get("source_query") or "").strip()
            webpage_url = str(item.get("webpage_url") or source_query).strip()
            requested_by = str(item.get("requested_by") or "cache").strip() or "cache"
            artist_raw = item.get("artist")
            artist = str(artist_raw).strip() if artist_raw is not None else None
            if artist == "":
                artist = None
            duration_raw = item.get("duration_seconds")
            duration = int(duration_raw) if isinstance(duration_raw, (int, float)) else None
            if not title or not source_query:
                continue
            out.append(
                Track(
                    source_query=source_query,
                    title=title,
                    webpage_url=webpage_url,
                    requested_by=requested_by,
                    artist=artist,
                    duration_seconds=duration,
                )
            )
        return out

    def _persist_search_cache_entry(self, key: tuple[int, int, str, int], tracks: list[Track]) -> None:
        guild_id, user_id, normalized_query, result_limit = key
        payload_json = self._serialize_tracks_for_cache(tracks)

        async def worker() -> None:
            try:
                await self.store.upsert_search_cache(
                    guild_id=guild_id,
                    user_id=user_id,
                    normalized_query=normalized_query,
                    result_limit=result_limit,
                    payload_json=payload_json,
                    cached_at_unix=int(time.time()),
                )
            except Exception:
                LOGGER.debug("Falha ao persistir search cache no SQLite", exc_info=True)

        task = self.bot.loop.create_task(worker())
        self._search_cache_write_tasks.add(task)
        task.add_done_callback(self._search_cache_write_tasks.discard)

    async def _restore_search_cache_from_store(self) -> None:
        if self.search_cache_ttl_seconds <= 0:
            return
        try:
            records = await self.store.load_recent_search_cache(max_rows=self.search_cache_max_entries)
        except Exception:
            LOGGER.debug("Falha ao restaurar search cache do SQLite", exc_info=True)
            return
        now = time.time()
        ttl = max(self.search_cache_ttl_seconds + self.search_cache_stale_ttl_seconds, 1.0)
        restored = 0
        for record in records:
            age = max(now - float(record.cached_at_unix), 0.0)
            if age > ttl:
                continue
            tracks = self._deserialize_tracks_from_cache(record.payload_json)
            if not tracks:
                continue
            cached_at_mono = max(time.monotonic() - age, 0.0)
            expires_at = cached_at_mono + self.search_cache_ttl_seconds
            key = (record.guild_id, record.user_id, record.normalized_query, max(record.result_limit, 1))
            self._search_cache[key] = (expires_at, cached_at_mono, tracks)
            self._search_cache.move_to_end(key)
            restored += 1
        while len(self._search_cache) > self.search_cache_max_entries:
            self._search_cache.popitem(last=False)
        if restored:
            LOGGER.info("Search cache restaurado do SQLite: %s entradas", restored)

    async def _schedule_startup_warmup(self) -> None:
        if self._startup_warmup_done:
            return
        self._startup_warmup_done = True
        if self._startup_warmup_task and not self._startup_warmup_task.done():
            return

        async def worker() -> None:
            await asyncio.sleep(2.0)
            guilds = list(getattr(self.bot, "guilds", []))
            for guild in guilds:
                # Warm de estado do player/fila para reduzir custo no primeiro comando do guild.
                try:
                    player = await self._get_player(int(guild.id))
                    self._schedule_prefetch_next(int(guild.id), player)
                except Exception:
                    LOGGER.debug("Warmup: falha ao aquecer player do guild %s", getattr(guild, "id", "?"), exc_info=True)
                try:
                    queries = await self.store.list_popular_queries(
                        int(guild.id),
                        prefix="",
                        limit=max(self.search_startup_warmup_queries, 1),
                    )
                except Exception:
                    LOGGER.debug("Warmup: falha ao carregar queries do guild %s", getattr(guild, "id", "?"), exc_info=True)
                    continue
                for query in queries:
                    normalized_query = self._normalize_search_query(query)
                    if not normalized_query:
                        continue
                    key = (int(guild.id), 0, normalized_query, self.search_results_limit)
                    cached, stale = self._cache_get_search(key, allow_stale=True)
                    if cached is not None and not stale:
                        continue
                    try:
                        tracks = await self._search_tracks_guarded(
                            query,
                            requester="startup-warmup",
                            limit=self.search_results_limit,
                            guild_id=int(guild.id),
                            user_id=0,
                        )
                    except Exception:
                        continue
                    if tracks:
                        self._cache_put_search(key, tracks)
                    await asyncio.sleep(0.05)

        self._startup_warmup_task = self.bot.loop.create_task(worker())

    async def _popular_queries_cached(self, guild_id: int, current: str, limit: int) -> list[str]:
        normalized_prefix = current.strip().casefold()
        key = (guild_id, normalized_prefix, max(limit, 1))
        now = time.monotonic()
        cached = self._autocomplete_rank_cache.get(key)
        if cached is not None and cached[0] >= now:
            self._metrics["autocomplete_cache_hit"] += 1
            return cached[1]
        self._metrics["autocomplete_cache_miss"] += 1
        try:
            ranked = await self.store.list_popular_queries(
                guild_id,
                prefix=current,
                limit=max(limit, 1),
            )
        except Exception:
            LOGGER.debug("Falha ao carregar ranking de autocomplete", exc_info=True)
            ranked = []
        self._autocomplete_rank_cache[key] = (now + self.autocomplete_rank_cache_ttl_seconds, ranked)
        return ranked

    def _schedule_search_refresh(self, key: tuple[int, int, str, int], query: str, requester: str, limit: int) -> None:
        if key in self._search_refreshing:
            return
        self._search_refreshing.add(key)

        async def worker() -> None:
            try:
                tracks = await self._search_tracks_guarded(
                    query,
                    requester=requester,
                    limit=limit,
                    guild_id=key[0],
                    user_id=key[1],
                )
                if tracks:
                    self._cache_put_search(key, tracks)
            except Exception:
                return
            finally:
                self._search_refreshing.discard(key)

        self.bot.loop.create_task(worker())

    def _cache_get_lyrics(self, key: str) -> str | None:
        cached = self._lyrics_cache.get(key)
        if cached is None:
            return None
        expires_at, lyrics = cached
        if expires_at < time.monotonic():
            self._lyrics_cache.pop(key, None)
            return None
        self._lyrics_cache.move_to_end(key)
        return lyrics

    def _cache_put_lyrics(self, key: str, lyrics: str) -> None:
        self._lyrics_cache[key] = (time.monotonic() + self.lyrics_cache_ttl_seconds, lyrics)
        self._lyrics_cache.move_to_end(key)
        while len(self._lyrics_cache) > self.lyrics_cache_max_entries:
            self._lyrics_cache.popitem(last=False)

    async def _search_lyrics(self, title: str) -> str | None:
        normalized_key = re.sub(r"\s+", " ", title.strip().casefold())
        if not normalized_key:
            return None
        cached = self._cache_get_lyrics(normalized_key)
        if cached is not None:
            return cached

        session = self._http_session
        if session is None or session.closed:
            session = ClientSession(timeout=ClientTimeout(total=6))
            self._http_session = session

        endpoint = "https://lrclib.net/api/search"
        try:
            async with session.get(endpoint, params={"q": title}) as resp:
                if resp.status != 200:
                    return None
                payload = await resp.json()
        except (ClientError, asyncio.TimeoutError, ValueError):
            return None

        if not isinstance(payload, list):
            return None
        best_text = ""
        for item in payload:
            if not isinstance(item, dict):
                continue
            synced = str(item.get("syncedLyrics") or "").strip()
            plain = str(item.get("plainLyrics") or "").strip()
            candidate = synced or plain
            if len(candidate) > len(best_text):
                best_text = candidate
        if not best_text:
            return None
        self._cache_put_lyrics(normalized_key, best_text)
        return best_text

    @staticmethod
    def _format_progress_bar(elapsed_seconds: int, total_seconds: int, *, size: int = 14) -> str:
        safe_total = max(total_seconds, 1)
        clamped = max(0, min(elapsed_seconds, safe_total))
        filled = int((clamped / safe_total) * size)
        left = "█" * max(filled, 0)
        right = "░" * max(size - filled, 0)
        return f"{left}{right}"

    @staticmethod
    def _compute_elapsed_seconds(player: GuildPlayer) -> int:
        if player.current_started_at is None:
            return 0
        elapsed = time.monotonic() - player.current_started_at - player.paused_accumulated_seconds
        if player.pause_started_at is not None:
            elapsed -= max(time.monotonic() - player.pause_started_at, 0.0)
        return max(int(elapsed), 0)

    def _build_nowplaying_embed(self, player: GuildPlayer, track: Track) -> discord.Embed:
        elapsed = self._compute_elapsed_seconds(player)
        duration = track.duration_seconds
        progress_value = "`ao vivo`"
        if duration and duration > 0:
            bar = self._format_progress_bar(elapsed, duration)
            progress_value = f"`{self._format_duration(elapsed)} / {self._format_duration(duration)}`\n`{bar}`"
        compact_mode = player.guild_id in self._nowplaying_compact_mode_guilds
        return self.embeds.build_nowplaying_embed(
            track=track,
            progress_value=progress_value,
            duration_text=self._format_duration(track.duration_seconds),
            audio_filter=player.audio_filter,
            requested_by=track.requested_by,
            source_url=track.webpage_url,
            volume_percent=int(player.volume * 100),
            loop_mode=player.loop_mode,
            autoplay_on=player.autoplay,
            compact_mode=compact_mode,
        )

    @staticmethod
    def _resolve_nowplaying_channel(
        guild: discord.Guild,
        preferred: discord.abc.Messageable | None,
    ) -> discord.TextChannel | discord.Thread | None:
        if isinstance(preferred, (discord.TextChannel, discord.Thread)):
            return preferred
        if preferred is not None and hasattr(preferred, "id"):
            maybe = guild.get_channel(getattr(preferred, "id"))
            if isinstance(maybe, (discord.TextChannel, discord.Thread)):
                return maybe
        return None

    def _cancel_nowplaying_updater(self, guild_id: int) -> None:
        self.nowplaying.cancel_updater(guild_id)

    async def _restore_nowplaying_message_if_needed(self, guild_id: int) -> None:
        try:
            await self.nowplaying.restore_message_if_needed(
                guild_id=guild_id,
                bot=self.bot,
                store=self.store,
            )
        except Exception:
            LOGGER.debug("Falha ao restaurar nowplaying para guild %s", guild_id, exc_info=True)

    async def _upsert_nowplaying_message(
        self,
        guild: discord.Guild,
        text_channel: discord.abc.Messageable | None,
    ) -> None:
        player = await self._get_player(guild.id)
        current = player.current
        if current is None:
            return
        await self.nowplaying.upsert_message(
            guild=guild,
            text_channel=text_channel,
            store=self.store,
            nowplaying_auto_pin=self.nowplaying_auto_pin,
            nowplaying_repost_on_track_change=self.nowplaying_repost_on_track_change,
            build_embed=lambda: self._build_nowplaying_embed(player, current),
            build_view=lambda: NowPlayingView(self, guild_id=guild.id, author_id=0),
            track_key=lambda: self._track_key(current),
            resolve_channel=self._resolve_nowplaying_channel,
        )

    def _schedule_nowplaying_updater(self, guild: discord.Guild) -> None:
        async def get_embed() -> discord.Embed | None:
            player = await self._get_player(guild.id)
            if player.current is None:
                return None
            return self._build_nowplaying_embed(player, player.current)

        self.nowplaying.schedule_updater(
            guild=guild,
            get_build_embed=get_embed,
            build_view=lambda: NowPlayingView(self, guild_id=guild.id, author_id=0),
            on_message_lost=lambda guild_id: self.nowplaying.messages.pop(guild_id, None),
            interval_seconds=5.0,
        )

    @staticmethod
    def _guess_artist(title: str) -> str:
        clean = re.sub(r"\s+", " ", title).strip()
        for sep in (" - ", " – ", " — ", " | ", " ~ "):
            if sep in clean:
                left, _right = clean.split(sep, 1)
                left = left.strip()
                if 1 <= len(left) <= 60:
                    return left
        return ""

    @staticmethod
    def _track_key(track: Track) -> str:
        primary = track.webpage_url or track.source_query or track.title
        return re.sub(r"\s+", " ", primary.strip().casefold())

    def _remember_finished_track(self, guild_id: int, track: Track) -> None:
        key = self._track_key(track)
        title = re.sub(r"\s+", " ", track.title.strip())
        if not key or not title:
            return
        recent_keys = self._autoplay_recent_keys[guild_id]
        recent_titles = self._autoplay_recent_titles[guild_id]
        recent_keys.append(key)
        recent_titles.append(title)
        while len(recent_keys) > self.autoplay_history_size:
            recent_keys.popleft()
        while len(recent_titles) > self.autoplay_history_size:
            recent_titles.popleft()
        self._schedule_search_prewarm(guild_id, track)

    def _schedule_search_prewarm(self, guild_id: int, track: Track) -> None:
        if not self.search_prewarm_enabled:
            return
        running = self._search_prewarm_tasks.get(guild_id)
        if running and not running.done():
            return

        async def worker() -> None:
            try:
                queries = self._autoplay_seed_queries(guild_id, track)[: max(self.search_prewarm_query_count, 1)]
                for query in queries:
                    normalized = self._normalize_search_query(query)
                    key = (guild_id, 0, normalized, self.search_results_limit)
                    cached, stale = self._cache_get_search(key, allow_stale=True)
                    if cached is not None and not stale:
                        continue
                    try:
                        tracks = await self._search_tracks_guarded(
                            query,
                            requester="prewarm",
                            limit=self.search_results_limit,
                            guild_id=guild_id,
                            user_id=0,
                        )
                    except Exception:
                        continue
                    if tracks:
                        self._cache_put_search(key, tracks)
                    await asyncio.sleep(0.05)
            finally:
                self._search_prewarm_tasks.pop(guild_id, None)

        self._search_prewarm_tasks[guild_id] = self.bot.loop.create_task(worker())

    def _autoplay_seed_queries(self, guild_id: int, from_track: Track) -> list[str]:
        seeds: list[str] = []
        seen: set[str] = set()

        def add_seed(value: str) -> None:
            normalized = re.sub(r"\s+", " ", value.strip())
            if not normalized:
                return
            key = normalized.casefold()
            if key in seen:
                return
            seen.add(key)
            seeds.append(normalized)

        add_seed(f"{from_track.title} audio")
        from_artist = self._guess_artist(from_track.title)
        if from_artist:
            add_seed(f"{from_artist} top tracks")

        recent_titles = list(self._autoplay_recent_titles.get(guild_id, deque()))[-6:]
        for title in reversed(recent_titles):
            add_seed(f"{title} audio")
            artist = self._guess_artist(title)
            if artist:
                add_seed(f"{artist} top tracks")

        return seeds[: self.autoplay_max_queries]

    async def _pick_autoplay_recommendation(self, guild_id: int, player: GuildPlayer, from_track: Track) -> Track | None:
        blocked_keys: set[str] = set(self._autoplay_recent_keys.get(guild_id, deque()))
        if player.current:
            blocked_keys.add(self._track_key(player.current))
        for queued in player.snapshot_queue():
            blocked_keys.add(self._track_key(queued))

        queries = self._autoplay_seed_queries(guild_id, from_track)
        for query in queries:
            candidates = await self._search_tracks_guarded(
                query,
                requester="autoplay",
                limit=self.autoplay_search_limit,
                guild_id=guild_id,
                user_id=0,
            )
            for candidate in candidates:
                if self._track_key(candidate) in blocked_keys:
                    continue
                if self._track_policy_error(guild_id, candidate):
                    continue
                return candidate

        if not self._provider_available("extract"):
            return None
        try:
            fallback = await self.resolver.extract_recommended_track(from_track, requester="autoplay")
        except Exception:
            self._provider_failure("extract")
            return None
        self._provider_success("extract")
        if self._track_key(fallback) in blocked_keys:
            return None
        if self._track_policy_error(guild_id, fallback):
            return None
        return fallback
