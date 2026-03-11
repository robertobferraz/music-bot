from __future__ import annotations

import asyncio
import difflib
import re
from collections import OrderedDict
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from botmusica.music.player import MusicService, Track, TrackBatch


class MusicResolver:
    def __init__(
        self,
        music: MusicService,
        *,
        spotify_strict_match: bool,
        spotify_match_threshold: float,
        spotify_candidate_limit: int,
        spotify_meta_cache_ttl_seconds: float,
        spotify_meta_cache_max_entries: int,
    ) -> None:
        self.music = music
        self.spotify_strict_match = spotify_strict_match
        self.spotify_match_threshold = spotify_match_threshold
        self.spotify_candidate_limit = spotify_candidate_limit
        self.spotify_meta_cache_ttl_seconds = spotify_meta_cache_ttl_seconds
        self.spotify_meta_cache_max_entries = spotify_meta_cache_max_entries
        self._spotify_meta_cache: OrderedDict[str, tuple[float, tuple[str, str]]] = OrderedDict()
        self._http_session: ClientSession | None = None

    @staticmethod
    def _is_spotify_retryable_error(exc: Exception) -> bool:
        text = str(exc).casefold()
        return "429" in text or "too many requests" in text or "temporarily" in text

    async def _run_with_spotify_retry(self, operation: str, fn: Any) -> Any:
        retries = 3
        base_delay = 0.8
        last_exc: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                return await fn()
            except Exception as exc:
                last_exc = exc
                if attempt >= retries or not self._is_spotify_retryable_error(exc):
                    raise
                await asyncio.sleep(base_delay * attempt)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"{operation} failed")

    async def close(self) -> None:
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
        self._http_session = None

    async def extract_tracks(self, link: str, requester: str, *, max_items: int | None = None) -> TrackBatch:
        return await self.music.extract_tracks(link, requester=requester, max_items=max_items)

    async def extract_track(self, link: str, requester: str) -> Track:
        return await self.music.extract_track(link, requester=requester)

    async def search_tracks(self, query: str, requester: str, *, limit: int = 5) -> list[Track]:
        return await self.music.search_tracks(query, requester=requester, limit=limit)

    async def extract_recommended_track(self, from_track: Track, requester: str) -> Track:
        return await self.music.extract_recommended_track(from_track, requester=requester)

    async def extract_batch_with_spotify_fallback(
        self,
        *,
        link: str,
        requester: str,
        max_items: int | None = None,
    ) -> tuple[TrackBatch, bool]:
        if self._is_known_unsupported_music_url(link):
            raise RuntimeError("Fonte nao suportada: links de Apple Music nao podem ser reproduzidos diretamente.")
        if not self._is_spotify_url(link):
            return await self.extract_tracks(link, requester=requester, max_items=max_items), False

        if self._is_spotify_collection_url(link):
            try:
                native_batch = await self._run_with_spotify_retry(
                    "spotify_collection_extract",
                    lambda: self.extract_tracks(link, requester=requester, max_items=max_items),
                )
            except Exception:
                native_batch = None
            if native_batch is not None:
                converted = self._spotify_batch_to_search_batch(native_batch, original_link=link, requester=requester)
                if converted is not None:
                    return converted, True

        spotify_meta = await self._spotify_oembed_meta(link)
        if not spotify_meta:
            raise RuntimeError("Spotify nao resolvido: nao consegui obter metadados para busca.")

        try:
            candidates = await self._run_with_spotify_retry(
                "spotify_candidates_search",
                lambda: asyncio.wait_for(
                    self.search_tracks(
                        spotify_meta[0] if spotify_meta[0] else spotify_meta[1],
                        requester=requester,
                        limit=self.spotify_candidate_limit,
                    ),
                    timeout=8.0,
                ),
            )
        except asyncio.TimeoutError:
            fallback_track = self._spotify_fallback_track(spotify_meta, link, requester=requester)
            return TrackBatch(tracks=[fallback_track], total_items=1, invalid_items=0), True
        if not candidates:
            fallback_track = self._spotify_fallback_track(spotify_meta, link, requester=requester)
            return TrackBatch(tracks=[fallback_track], total_items=1, invalid_items=0), True
        picked, score = self._pick_spotify_candidate(spotify_meta, candidates)
        if picked is None:
            fallback_track = self._spotify_fallback_track(spotify_meta, link, requester=requester)
            return TrackBatch(tracks=[fallback_track], total_items=1, invalid_items=0), True
        return TrackBatch(tracks=[picked], total_items=1, invalid_items=0), True

    async def extract_track_with_spotify_fallback(self, *, link: str, requester: str) -> tuple[Track, bool]:
        if self._is_known_unsupported_music_url(link):
            raise RuntimeError("Fonte nao suportada: links de Apple Music nao podem ser reproduzidos diretamente.")
        if not self._is_spotify_url(link):
            return await self.extract_track(link, requester=requester), False

        spotify_meta = await self._spotify_oembed_meta(link)
        if not spotify_meta:
            raise RuntimeError("Spotify nao resolvido: nao consegui obter metadados para busca.")

        try:
            candidates = await self._run_with_spotify_retry(
                "spotify_track_search",
                lambda: asyncio.wait_for(
                    self.search_tracks(
                        spotify_meta[0] if spotify_meta[0] else spotify_meta[1],
                        requester=requester,
                        limit=self.spotify_candidate_limit,
                    ),
                    timeout=8.0,
                ),
            )
        except asyncio.TimeoutError:
            return self._spotify_fallback_track(spotify_meta, link, requester=requester), True
        if not candidates:
            return self._spotify_fallback_track(spotify_meta, link, requester=requester), True
        picked, score = self._pick_spotify_candidate(spotify_meta, candidates)
        if picked is None:
            return self._spotify_fallback_track(spotify_meta, link, requester=requester), True
        return picked, True

    @staticmethod
    def _spotify_fallback_track(meta: tuple[str, str], original_link: str, *, requester: str) -> Track:
        title = (meta[0] or "").strip() or "Faixa Spotify"
        artist = (meta[1] or "").strip() or None
        terms = f"{title} {artist or ''}".strip()
        query = f"ytsearch1:{terms} audio" if terms else "ytsearch1:spotify track audio"
        return Track(
            source_query=query,
            title=title,
            webpage_url=original_link,
            requested_by=requester,
            artist=artist,
            duration_seconds=None,
        )

    @staticmethod
    def _spotify_batch_to_search_batch(
        batch: TrackBatch,
        *,
        original_link: str,
        requester: str,
    ) -> TrackBatch | None:
        converted: list[Track] = []
        extra_invalid = 0
        for item in batch.tracks:
            title = (item.title or "").strip()
            artist = (item.artist or "").strip()
            terms = f"{title} {artist}".strip()
            if not terms:
                extra_invalid += 1
                continue
            query = f"ytsearch1:{terms} audio"
            converted.append(
                Track(
                    source_query=query,
                    title=title or "Faixa Spotify",
                    webpage_url=(item.webpage_url or original_link).strip() or original_link,
                    requested_by=requester,
                    artist=artist or None,
                    duration_seconds=item.duration_seconds,
                )
            )
        if not converted:
            return None
        total_items = max(batch.total_items, len(converted) + extra_invalid)
        invalid_items = batch.invalid_items + extra_invalid
        return TrackBatch(tracks=converted, total_items=total_items, invalid_items=invalid_items)

    @staticmethod
    def _is_spotify_url(value: str) -> bool:
        if "://" not in value:
            return False
        host = value.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0].casefold()
        return host == "open.spotify.com" or host.endswith(".spotify.com")

    @classmethod
    def _is_spotify_collection_url(cls, value: str) -> bool:
        kind = cls._spotify_kind_from_url(value)
        return kind in {"playlist", "album"}

    @staticmethod
    def _spotify_kind_from_url(value: str) -> str | None:
        if "://" not in value:
            return None
        try:
            from urllib.parse import urlparse

            parsed = urlparse(value)
        except ValueError:
            return None
        host = (parsed.hostname or "").casefold()
        if host != "open.spotify.com" and not host.endswith(".spotify.com"):
            return None
        parts = [part for part in parsed.path.split("/") if part]
        if not parts:
            return None
        if parts[0].startswith("intl-") and len(parts) >= 2:
            return parts[1].casefold()
        return parts[0].casefold()

    @staticmethod
    def _is_known_unsupported_music_url(value: str) -> bool:
        if "://" not in value:
            return False
        host = value.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0].casefold()
        return host == "music.apple.com" or host.endswith(".music.apple.com")

    def _cache_get_spotify_meta(self, spotify_url: str) -> tuple[str, str] | None:
        import time

        if self.spotify_meta_cache_ttl_seconds <= 0:
            return None
        cached = self._spotify_meta_cache.get(spotify_url)
        if cached is None:
            return None
        expires_at, meta = cached
        if expires_at < time.monotonic():
            self._spotify_meta_cache.pop(spotify_url, None)
            return None
        self._spotify_meta_cache.move_to_end(spotify_url)
        return meta

    def _cache_put_spotify_meta(self, spotify_url: str, meta: tuple[str, str]) -> None:
        import time

        if self.spotify_meta_cache_ttl_seconds <= 0 or self.spotify_meta_cache_max_entries < 1:
            return
        self._spotify_meta_cache[spotify_url] = (time.monotonic() + self.spotify_meta_cache_ttl_seconds, meta)
        self._spotify_meta_cache.move_to_end(spotify_url)
        while len(self._spotify_meta_cache) > self.spotify_meta_cache_max_entries:
            self._spotify_meta_cache.popitem(last=False)

    async def _spotify_oembed_meta(self, spotify_url: str) -> tuple[str, str] | None:
        cached_meta = self._cache_get_spotify_meta(spotify_url)
        if cached_meta is not None:
            return cached_meta

        endpoint = "https://open.spotify.com/oembed"
        session = self._http_session
        if session is None or session.closed:
            session = ClientSession(timeout=ClientTimeout(total=6))
            self._http_session = session
        try:
            async with session.get(endpoint, params={"url": spotify_url}) as resp:
                if resp.status != 200:
                    return None
                payload = await resp.json()
        except (ClientError, ValueError):
            return None

        title = str(payload.get("title") or "").strip()
        author = str(payload.get("author_name") or "").strip()
        if not title and not author:
            return None
        meta = (title, author)
        self._cache_put_spotify_meta(spotify_url, meta)
        return meta

    @staticmethod
    def _normalize_text(value: str) -> str:
        lowered = value.casefold()
        normalized = re.sub(r"[^a-z0-9 ]+", " ", lowered)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _spotify_match_score(self, meta: tuple[str, str], track: Track) -> float:
        source = self._normalize_text(f"{meta[0]} {meta[1]}".strip())
        candidate = self._normalize_text(f"{track.title} {track.artist or ''}".strip())
        if not source or not candidate:
            return 0.0
        ratio = difflib.SequenceMatcher(None, source, candidate).ratio()
        source_tokens = set(source.split())
        candidate_tokens = set(candidate.split())
        overlap = 0.0
        if source_tokens and candidate_tokens:
            overlap = len(source_tokens & candidate_tokens) / len(source_tokens)
        return (ratio * 0.75) + (overlap * 0.25)

    def _pick_spotify_candidate(self, meta: tuple[str, str], candidates: list[Track]) -> tuple[Track | None, float]:
        best_track: Track | None = None
        best_score = 0.0
        for track in candidates:
            score = self._spotify_match_score(meta, track)
            if score > best_score:
                best_score = score
                best_track = track
        if best_track is None:
            return None, 0.0
        if self.spotify_strict_match and best_score < self.spotify_match_threshold:
            return None, best_score
        return best_track, best_score
