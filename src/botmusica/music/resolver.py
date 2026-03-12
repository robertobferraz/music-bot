from __future__ import annotations

import asyncio
import difflib
import logging
import os
import re
import time
from collections import OrderedDict
from typing import Any
from urllib.parse import urlparse

from aiohttp import BasicAuth, ClientError, ClientSession, ClientTimeout

from botmusica.music.player import MusicService, Track, TrackBatch

LOGGER = logging.getLogger("botmusica.music")


class MusicResolver:
    def __init__(
        self,
        music: MusicService,
        *,
        store: Any | None = None,
        spotify_strict_match: bool,
        spotify_match_threshold: float,
        spotify_candidate_limit: int,
        spotify_meta_cache_ttl_seconds: float,
        spotify_meta_cache_max_entries: int,
    ) -> None:
        self.music = music
        self.store = store
        self.spotify_strict_match = spotify_strict_match
        self.spotify_match_threshold = spotify_match_threshold
        self.spotify_candidate_limit = spotify_candidate_limit
        self.spotify_meta_cache_ttl_seconds = spotify_meta_cache_ttl_seconds
        self.spotify_meta_cache_max_entries = spotify_meta_cache_max_entries
        self._spotify_meta_cache: OrderedDict[str, tuple[float, tuple[str, str]]] = OrderedDict()
        self._http_session: ClientSession | None = None
        self._spotify_client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
        self._spotify_client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
        self._spotify_user_access_token = os.getenv("SPOTIFY_USER_ACCESS_TOKEN", "").strip()
        self._spotify_user_refresh_token = os.getenv("SPOTIFY_USER_REFRESH_TOKEN", "").strip()
        self._spotify_market = os.getenv("SPOTIFY_MARKET", "").strip().upper()
        self._spotify_access_token: str = ""
        self._spotify_access_token_expires_at: float = 0.0
        self._spotify_user_access_token_expires_at: float = 0.0
        self._spotify_frontend_fallback_enabled = os.getenv("SPOTIFY_FRONTEND_FALLBACK", "false").strip().casefold() in {"1", "true", "yes", "on"}
        self._spotify_frontend_provider_url = os.getenv("SPOTIFY_FRONTEND_PROVIDER_URL", "").strip()
        self._spotify_frontend_provider_token = os.getenv("SPOTIFY_FRONTEND_PROVIDER_TOKEN", "").strip()
        self._spotify_resolve_cache_ttl_seconds = max(
            int(os.getenv("SPOTIFY_RESOLVE_CACHE_TTL_SECONDS", "604800").strip() or "604800"),
            60,
        )
        self._spotify_resolve_failure_cache_ttl_seconds = max(
            int(os.getenv("SPOTIFY_RESOLVE_FAILURE_CACHE_TTL_SECONDS", "1800").strip() or "1800"),
            60,
        )
        self._spotify_resolve_concurrency = max(
            int(os.getenv("SPOTIFY_RESOLVE_CONCURRENCY", "6").strip() or "6"),
            1,
        )
        self._spotify_track_details_forbidden_logged = False
        LOGGER.info(
            "spotify_api_enabled=%s spotify_user_token=%s spotify_user_refresh=%s market=%s strict_match=%s candidate_limit=%s resolve_cache_ttl=%s failure_cache_ttl=%s resolve_concurrency=%s spotify_frontend_fallback=%s spotify_frontend_provider=%s",
            bool(
                self._spotify_user_access_token
                or self._spotify_user_refresh_token
                or (self._spotify_client_id and self._spotify_client_secret)
            ),
            bool(self._spotify_user_access_token),
            bool(self._spotify_user_refresh_token),
            self._spotify_market or "default",
            self.spotify_strict_match,
            self.spotify_candidate_limit,
            self._spotify_resolve_cache_ttl_seconds,
            self._spotify_resolve_failure_cache_ttl_seconds,
            self._spotify_resolve_concurrency,
            self._spotify_frontend_fallback_enabled,
            bool(self._spotify_frontend_provider_url),
        )

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

        resolved_via_frontend = False
        try:
            api_batch = await self._spotify_batch_via_api(link, requester=requester, max_items=max_items)
        except RuntimeError as exc:
            lowered = str(exc).casefold()
            if self._is_spotify_collection_url(link) and ("spotify playlist nao acessivel pela api" in lowered or "spotify album nao acessivel pela api" in lowered):
                api_batch = await self._spotify_batch_via_frontend_provider(link, requester=requester, max_items=max_items)
                resolved_via_frontend = api_batch is not None
                if api_batch is None:
                    raise
            else:
                raise
        if api_batch is not None:
            if resolved_via_frontend:
                LOGGER.info("Spotify batch resolvido via provider externo url=%s total_items=%s", link, api_batch.total_items)
            else:
                LOGGER.info("Spotify batch resolvido via API url=%s total_items=%s", link, api_batch.total_items)
            return api_batch, True

        if self._is_spotify_collection_url(link):
            try:
                native_batch = await self.extract_tracks(link, requester=requester, max_items=max_items)
            except RuntimeError as exc:
                if "spotify playlist nao acessivel pela api" in str(exc).casefold():
                    raise
            except Exception:
                LOGGER.info("Spotify collection fallback nativo falhou url=%s", link, exc_info=True)
                native_batch = None
            if native_batch is not None:
                converted = self._spotify_batch_to_search_batch(native_batch, original_link=link, requester=requester)
                if converted is not None:
                    LOGGER.info("Spotify batch convertido via fallback nativo url=%s total_items=%s", link, converted.total_items)
                    return converted, True

        spotify_meta = await self._spotify_oembed_meta(link)
        if not spotify_meta:
            raise RuntimeError("Spotify nao resolvido: nao consegui obter metadados para busca.")

        try:
            candidates = await asyncio.wait_for(
                self.search_tracks(
                    spotify_meta[0] if spotify_meta[0] else spotify_meta[1],
                    requester=requester,
                    limit=self.spotify_candidate_limit,
                ),
                timeout=8.0,
            )
        except asyncio.TimeoutError:
            fallback_track = self._spotify_fallback_track(spotify_meta, link, requester=requester)
            return TrackBatch(tracks=[fallback_track], total_items=1, invalid_items=0), True
        if not candidates:
            fallback_track = self._spotify_fallback_track(spotify_meta, link, requester=requester)
            return TrackBatch(tracks=[fallback_track], total_items=1, invalid_items=0), True
        picked, score = self._pick_spotify_candidate((spotify_meta[0], spotify_meta[1], None), candidates)
        if picked is None:
            fallback_track = self._spotify_fallback_track(spotify_meta, link, requester=requester)
            return TrackBatch(tracks=[fallback_track], total_items=1, invalid_items=0), True
        return TrackBatch(tracks=[picked], total_items=1, invalid_items=0), True

    async def extract_track_with_spotify_fallback(self, *, link: str, requester: str) -> tuple[Track, bool]:
        if self._is_known_unsupported_music_url(link):
            raise RuntimeError("Fonte nao suportada: links de Apple Music nao podem ser reproduzidos diretamente.")
        if not self._is_spotify_url(link):
            return await self.extract_track(link, requester=requester), False

        kind, spotify_id = self._spotify_kind_and_id_from_url(link)
        if kind == "track" and spotify_id:
            cached = await self._spotify_cached_track(
                spotify_track_id=spotify_id,
                requester=requester,
                original_link=link,
            )
            if cached is not None:
                return cached, True

        spotify_meta = await self._spotify_track_meta_via_api(link)
        if spotify_meta is None:
            spotify_meta = await self._spotify_oembed_meta(link)
        else:
            LOGGER.info("Spotify track resolvido via API url=%s", link)
        if not spotify_meta:
            raise RuntimeError("Spotify nao resolvido: nao consegui obter metadados para busca.")

        resolved = await self._resolve_spotify_track_candidate(
            spotify_track_id=spotify_id,
            spotify_meta=spotify_meta,
            link=link,
            requester=requester,
        )
        return resolved, True

    async def _resolve_spotify_meta_to_track(
        self,
        *,
        spotify_track_id: str | None,
        spotify_meta: tuple[str, str, int | None],
        link: str,
        requester: str,
    ) -> Track:
        return await self._resolve_spotify_track_candidate(
            spotify_track_id=spotify_track_id,
            spotify_meta=spotify_meta,
            link=link,
            requester=requester,
        )

    @staticmethod
    def _spotify_track_payload_meta(payload: dict[str, object]) -> tuple[str, str, int | None] | None:
        title = str(payload.get("name") or "").strip()
        artist = MusicResolver._spotify_join_artists(payload.get("artists")) or ""
        duration_seconds = int(payload.get("duration_ms") // 1000) if isinstance(payload.get("duration_ms"), int) else None
        if not title and not artist:
            return None
        return title, artist, duration_seconds

    @staticmethod
    def _spotify_track_payload_isrc(payload: dict[str, object]) -> str | None:
        external_ids = payload.get("external_ids")
        if not isinstance(external_ids, dict):
            return None
        isrc = str(external_ids.get("isrc") or "").strip().upper()
        return isrc or None

    @staticmethod
    def _native_search_query(terms: str, *, limit: int = 5) -> str:
        cleaned_terms = (terms or "").strip()
        safe_limit = max(1, int(limit))
        if cleaned_terms:
            return f"ytsearch{safe_limit}:{cleaned_terms} audio"
        return f"ytsearch{safe_limit}:spotify track audio"

    @staticmethod
    def _spotify_fallback_track(meta: tuple[str, str], original_link: str, *, requester: str) -> Track:
        title = (meta[0] or "").strip() or "Faixa Spotify"
        artist = (meta[1] or "").strip() or None
        terms = f"{title} {artist or ''}".strip()
        query = MusicResolver._native_search_query(terms)
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
            query = MusicResolver._native_search_query(terms)
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
    def _spotify_search_track(
        *,
        title: str,
        artist: str | None,
        original_link: str,
        requester: str,
        duration_seconds: int | None = None,
    ) -> Track | None:
        safe_title = (title or "").strip()
        safe_artist = (artist or "").strip() or None
        terms = f"{safe_title} {safe_artist or ''}".strip()
        if not terms:
            return None
        return Track(
            source_query=MusicResolver._native_search_query(terms),
            title=safe_title or "Faixa Spotify",
            webpage_url=original_link,
            requested_by=requester,
            artist=safe_artist,
            duration_seconds=duration_seconds,
        )

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

    @classmethod
    def _spotify_kind_and_id_from_url(cls, value: str) -> tuple[str | None, str | None]:
        if "://" not in value:
            return None, None
        try:
            parsed = urlparse(value)
        except ValueError:
            return None, None
        host = (parsed.hostname or "").casefold()
        if host != "open.spotify.com" and not host.endswith(".spotify.com"):
            return None, None
        parts = [part for part in parsed.path.split("/") if part]
        if not parts:
            return None, None
        if parts[0].startswith("intl-") and len(parts) >= 3:
            kind = parts[1].casefold()
            spotify_id = parts[2].strip()
            return kind, spotify_id or None
        if len(parts) < 2:
            return None, None
        kind = parts[0].casefold()
        spotify_id = parts[1].strip()
        return kind, spotify_id or None

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

    def _spotify_api_enabled(self) -> bool:
        return bool(
            self._spotify_user_access_token
            or self._spotify_user_refresh_token
            or (self._spotify_client_id and self._spotify_client_secret)
        )

    def _spotify_frontend_provider_enabled(self) -> bool:
        return self._spotify_frontend_fallback_enabled and bool(self._spotify_frontend_provider_url)

    async def _spotify_batch_via_frontend_provider(
        self,
        spotify_url: str,
        *,
        requester: str,
        max_items: int | None,
    ) -> TrackBatch | None:
        if not self._spotify_frontend_provider_enabled():
            return None
        kind, _spotify_id = self._spotify_kind_and_id_from_url(spotify_url)
        if kind not in {"playlist", "album"}:
            return None
        session = await self._ensure_http_session()
        params = {"url": spotify_url, "kind": kind}
        if max_items is not None and max_items > 0:
            params["limit"] = str(max_items)
        headers: dict[str, str] = {}
        if self._spotify_frontend_provider_token:
            headers["Authorization"] = f"Bearer {self._spotify_frontend_provider_token}"
        try:
            async with session.get(self._spotify_frontend_provider_url, params=params, headers=headers) as resp:
                if resp.status != 200:
                    LOGGER.warning("Spotify frontend provider falhou status=%s kind=%s", resp.status, kind)
                    return None
                payload = await resp.json()
        except (ClientError, ValueError):
            LOGGER.info("Spotify frontend provider falhou kind=%s", kind, exc_info=True)
            return None
        if not isinstance(payload, dict):
            return None
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            return None
        limit = max_items if max_items is not None and max_items > 0 else len(items)
        tracks: list[Track] = []
        invalid = int(payload.get("invalid_items") or 0)
        for raw in items:
            if not isinstance(raw, dict):
                invalid += 1
                continue
            title = str(raw.get("title") or raw.get("name") or "").strip()
            artist = str(raw.get("artist") or "").strip()
            if not artist and isinstance(raw.get("artists"), list):
                artist = ", ".join(str(item).strip() for item in raw.get("artists") if str(item).strip())
            if not title:
                invalid += 1
                continue
            item_link = str(raw.get("spotify_url") or raw.get("webpage_url") or spotify_url).strip() or spotify_url
            duration_seconds = raw.get("duration_seconds")
            if duration_seconds is None:
                duration_ms = raw.get("duration_ms")
                if duration_ms not in (None, ""):
                    try:
                        duration_seconds = max(1, int(duration_ms) // 1000)
                    except (TypeError, ValueError):
                        duration_seconds = None
            else:
                try:
                    duration_seconds = int(duration_seconds)
                except (TypeError, ValueError):
                    duration_seconds = None
            track = self._spotify_fallback_track((title, artist), item_link, requester=requester)
            track.duration_seconds = duration_seconds
            track.artist = artist or None
            isrc = str(raw.get("isrc") or "").strip() or None
            track.isrc = isrc
            tracks.append(track)
            if len(tracks) >= limit:
                break
        if not tracks:
            return None
        total_items = int(payload.get("total") or 0)
        if total_items <= 0:
            total_items = len(tracks) + invalid
        LOGGER.info("Spotify frontend provider resolveu url=%s total_items=%s invalid_items=%s", spotify_url, total_items, invalid)
        return TrackBatch(tracks=tracks, total_items=max(total_items, len(tracks) + invalid), invalid_items=invalid)

    async def _ensure_http_session(self) -> ClientSession:
        session = self._http_session
        if session is None or session.closed:
            session = ClientSession(timeout=ClientTimeout(total=8))
            self._http_session = session
        return session

    async def _spotify_access_token_value(self) -> str | None:
        if self._spotify_user_refresh_token:
            refreshed = await self._spotify_refresh_user_access_token()
            if refreshed:
                return refreshed
        if self._spotify_user_access_token:
            return self._spotify_user_access_token
        if not self._spotify_api_enabled():
            LOGGER.info("Spotify API desabilitada: SPOTIFY_CLIENT_ID/SECRET ausentes.")
            return None
        if self._spotify_access_token and self._spotify_access_token_expires_at > time.monotonic():
            return self._spotify_access_token
        session = await self._ensure_http_session()
        try:
            async with session.post(
                "https://accounts.spotify.com/api/token",
                data={"grant_type": "client_credentials"},
                auth=BasicAuth(self._spotify_client_id, self._spotify_client_secret),
            ) as resp:
                if resp.status != 200:
                    LOGGER.warning("Spotify token request falhou status=%s", resp.status)
                    return None
                payload = await resp.json()
        except (ClientError, ValueError):
            LOGGER.debug("Falha ao obter token Spotify", exc_info=True)
            return None
        token = str(payload.get("access_token") or "").strip()
        expires_in = int(payload.get("expires_in") or 0)
        if not token:
            return None
        self._spotify_access_token = token
        self._spotify_access_token_expires_at = time.monotonic() + max(expires_in - 30, 30)
        return token

    async def _spotify_refresh_user_access_token(self, *, force: bool = False) -> str | None:
        if not self._spotify_user_refresh_token:
            return None
        if not force and self._spotify_user_access_token and self._spotify_user_access_token_expires_at > time.monotonic():
            return self._spotify_user_access_token
        if not self._spotify_client_id or not self._spotify_client_secret:
            LOGGER.warning("Spotify user refresh indisponivel: SPOTIFY_CLIENT_ID/SECRET ausentes.")
            return self._spotify_user_access_token or None
        session = await self._ensure_http_session()
        try:
            async with session.post(
                "https://accounts.spotify.com/api/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._spotify_user_refresh_token,
                },
                auth=BasicAuth(self._spotify_client_id, self._spotify_client_secret),
            ) as resp:
                if resp.status != 200:
                    LOGGER.warning("Spotify user token refresh falhou status=%s", resp.status)
                    return self._spotify_user_access_token or None
                payload = await resp.json()
        except (ClientError, ValueError):
            LOGGER.debug("Falha ao renovar token de usuario Spotify", exc_info=True)
            return self._spotify_user_access_token or None
        token = str(payload.get("access_token") or "").strip()
        expires_in = int(payload.get("expires_in") or 0)
        if not token:
            return self._spotify_user_access_token or None
        self._spotify_user_access_token = token
        self._spotify_user_access_token_expires_at = time.monotonic() + max(expires_in - 30, 30)
        LOGGER.info("Spotify user token renovado expires_in=%s", expires_in)
        return token

    async def _spotify_api_get_json(self, path: str, *, params: dict[str, str] | None = None) -> dict | None:
        status, payload = await self._spotify_api_get_json_with_status(path, params=params)
        if status != 200:
            return None
        return payload

    async def _spotify_api_get_json_with_status(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> tuple[int | None, dict | None]:
        session = await self._ensure_http_session()
        retried = False
        while True:
            token = await self._spotify_access_token_value()
            if not token:
                return None, None
            try:
                async with session.get(
                    f"https://api.spotify.com/v1/{path.lstrip('/')}",
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                ) as resp:
                    if resp.status == 401 and self._spotify_user_refresh_token and not retried:
                        retried = True
                        self._spotify_user_access_token_expires_at = 0.0
                        await self._spotify_refresh_user_access_token(force=True)
                        continue
                    if resp.status != 200:
                        LOGGER.warning("Spotify API GET falhou path=%s status=%s", path, resp.status)
                        return resp.status, None
                    payload = await resp.json()
            except (ClientError, ValueError):
                LOGGER.debug("Falha consultando Spotify API path=%s", path, exc_info=True)
                return None, None
            if not isinstance(payload, dict):
                return 200, None
            return 200, payload

    @staticmethod
    def _spotify_join_artists(artists_payload: object) -> str | None:
        if not isinstance(artists_payload, list):
            return None
        names = [str(item.get("name") or "").strip() for item in artists_payload if isinstance(item, dict)]
        names = [name for name in names if name]
        if not names:
            return None
        return ", ".join(names[:3])

    async def _spotify_track_meta_via_api(self, spotify_url: str) -> tuple[str, str, int | None] | None:
        kind, spotify_id = self._spotify_kind_and_id_from_url(spotify_url)
        if kind != "track" or not spotify_id:
            return None
        payload = await self._spotify_api_get_json(f"tracks/{spotify_id}")
        if not payload:
            return None
        meta = self._spotify_track_payload_meta(payload)
        if not meta:
            return None
        self._cache_put_spotify_meta(spotify_url, (meta[0], meta[1] or ""))
        return meta

    async def _spotify_playlist_summary(self, spotify_id: str) -> tuple[int | None, dict | None]:
        params = {
            "fields": "name,owner(display_name),tracks(total)",
            "additional_types": "track",
        }
        if self._spotify_market:
            params["market"] = self._spotify_market
        return await self._spotify_api_get_json_with_status(f"playlists/{spotify_id}", params=params)

    async def _spotify_batch_via_api(
        self,
        spotify_url: str,
        *,
        requester: str,
        max_items: int | None,
    ) -> TrackBatch | None:
        kind, spotify_id = self._spotify_kind_and_id_from_url(spotify_url)
        if not kind or not spotify_id:
            return None
        LOGGER.info("Spotify API tentando resolver kind=%s id=%s", kind, spotify_id)
        if kind == "track":
            meta = await self._spotify_track_meta_via_api(spotify_url)
            if not meta:
                return None
            track = await self._resolve_spotify_meta_to_track(
                spotify_track_id=spotify_id,
                spotify_meta=meta,
                link=spotify_url,
                requester=requester,
            )
            return TrackBatch(tracks=[track], total_items=1, invalid_items=0)

        limit = max_items if max_items is not None and max_items > 0 else 100
        if kind == "album":
            tracks: list[Track] = []
            invalid = 0
            offset = 0
            total_items = 0
            while len(tracks) < limit:
                page_limit = min(50, limit - len(tracks))
                status, payload = await self._spotify_api_get_json_with_status(
                    f"albums/{spotify_id}/tracks",
                    params={"limit": str(page_limit), "offset": str(offset)},
                )
                if status == 403:
                    raise RuntimeError(
                        "Spotify album nao acessivel pela API. Links de colecao do Spotify dependem de metadados publicos; quando a API bloqueia acesso, o bot nao tenta reproduzir o link direto por DRM."
                    )
                items = payload.get("items") if payload else None
                if not isinstance(items, list) or not items:
                    break
                total_items = int(payload.get("total") or 0) if payload else total_items
                for item in items:
                    if not isinstance(item, dict):
                        invalid += 1
                        continue
                    meta = self._spotify_track_payload_meta(item)
                    if meta is None:
                        invalid += 1
                        continue
                resolved = await self._resolve_spotify_page_tracks(
                    items=items,
                    requester=requester,
                    original_link=spotify_url,
                )
                tracks.extend(resolved[: max(limit - len(tracks), 0)])
                if len(tracks) >= limit:
                    tracks = tracks[:limit]
                    break
                offset += len(items)
                if total_items and offset >= total_items:
                    break
            if not tracks:
                return None
            if total_items <= 0:
                total_items = len(tracks) + invalid
            return TrackBatch(tracks=tracks, total_items=max(total_items, len(tracks) + invalid), invalid_items=invalid)

        if kind == "playlist":
            offset = 0
            tracks: list[Track] = []
            invalid = 0
            total_items = 0
            summary_status, summary_payload = await self._spotify_playlist_summary(spotify_id)
            if summary_status == 403:
                raise RuntimeError(
                    "Spotify playlist nao acessivel pela API. Playlists do Spotify so podem ser convertidas por metadados quando a API permite acesso; o bot nao tenta extrair o link direto por DRM."
                )
            if summary_payload:
                total_items = int(((summary_payload.get("tracks") or {}) if isinstance(summary_payload.get("tracks"), dict) else {}).get("total") or 0)
                LOGGER.info(
                    "Spotify playlist summary id=%s name=%s owner=%s total=%s",
                    spotify_id,
                    str(summary_payload.get("name") or "").strip() or "<sem-nome>",
                    str(((summary_payload.get("owner") or {}) if isinstance(summary_payload.get("owner"), dict) else {}).get("display_name") or "").strip() or "<sem-owner>",
                    total_items,
                )
            while len(tracks) < limit:
                page_limit = min(100, limit - len(tracks))
                page_params = {
                    "limit": str(page_limit),
                    "offset": str(offset),
                    "fields": "items(item(id,name,duration_ms,is_local,artists(name),external_urls(spotify))),total",
                    "additional_types": "track",
                }
                if self._spotify_market:
                    page_params["market"] = self._spotify_market
                status, payload = await self._spotify_api_get_json_with_status(
                    f"playlists/{spotify_id}/items",
                    params=page_params,
                )
                if status == 403:
                    raise RuntimeError(
                        "Spotify playlist nao acessivel pela API. Playlists do Spotify so podem ser convertidas por metadados quando a API permite acesso; o bot nao tenta extrair o link direto por DRM."
                    )
                items = payload.get("items") if payload else None
                if not isinstance(items, list) or not items:
                    break
                total_items = int(payload.get("total") or 0) if payload else total_items
                if limit == 1:
                    first_track = self._spotify_playlist_bootstrap_track(
                        items=items,
                        requester=requester,
                        original_link=spotify_url,
                    )
                    if first_track is not None:
                        effective_total = total_items if total_items > 0 else 1
                        return TrackBatch(tracks=[first_track], total_items=effective_total, invalid_items=invalid)
                    invalid += len(items)
                    break
                converted: list[Track] = []
                for item in items:
                    track_payload = (
                        item.get("item")
                        if isinstance(item, dict) and isinstance(item.get("item"), dict)
                        else item.get("track")
                        if isinstance(item, dict)
                        else None
                    )
                    if not isinstance(track_payload, dict):
                        invalid += 1
                        continue
                    if str(track_payload.get("is_local") or "").casefold() == "true":
                        invalid += 1
                        continue
                    meta = self._spotify_track_payload_meta(track_payload)
                    if meta is None:
                        invalid += 1
                        continue
                    isrc = self._spotify_track_payload_isrc(track_payload)
                    item_link = str(
                        ((track_payload.get("external_urls") or {}) if isinstance(track_payload.get("external_urls"), dict) else {}).get("spotify")
                        or spotify_url
                    )
                    fallback = self._spotify_fallback_track((meta[0], meta[1]), item_link, requester=requester)
                    fallback.duration_seconds = meta[2]
                    fallback.artist = meta[1] or None
                    fallback.isrc = isrc
                    converted.append(fallback)
                tracks.extend(converted[: max(limit - len(tracks), 0)])
                if len(tracks) >= limit:
                    tracks = tracks[:limit]
                    break
                offset += len(items)
                if total_items and offset >= total_items:
                    break
            if not tracks:
                return None
            if total_items <= 0:
                total_items = len(tracks) + invalid
            return TrackBatch(tracks=tracks, total_items=max(total_items, len(tracks) + invalid), invalid_items=invalid)
        return None

    def _spotify_playlist_bootstrap_track(
        self,
        *,
        items: list[dict] | list[object],
        requester: str,
        original_link: str,
    ) -> Track | None:
        for item in items:
            track_payload = (
                item.get("item")
                if isinstance(item, dict) and isinstance(item.get("item"), dict)
                else item.get("track")
                if isinstance(item, dict) and isinstance(item.get("track"), dict)
                else item
            )
            if not isinstance(track_payload, dict):
                continue
            if str(track_payload.get("is_local") or "").casefold() == "true":
                continue
            meta = self._spotify_track_payload_meta(track_payload)
            if meta is None:
                continue
            isrc = self._spotify_track_payload_isrc(track_payload)
            item_link = str(
                ((track_payload.get("external_urls") or {}) if isinstance(track_payload.get("external_urls"), dict) else {}).get("spotify")
                or original_link
            )
            bootstrap = self._spotify_fallback_track((meta[0], meta[1]), item_link, requester=requester)
            bootstrap.duration_seconds = meta[2]
            bootstrap.artist = meta[1] or None
            bootstrap.isrc = isrc
            return bootstrap
        return None

    @staticmethod
    def _normalize_text(value: str) -> str:
        lowered = value.casefold()
        normalized = re.sub(r"[^a-z0-9 ]+", " ", lowered)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    @staticmethod
    def _spotify_meta_with_duration(
        meta: tuple[str, str] | tuple[str, str, int | None] | tuple[str, str, int | None, str | None]
    ) -> tuple[str, str, int | None]:
        if len(meta) >= 3:
            return meta[0], meta[1], meta[2]
        return meta[0], meta[1], None

    def _spotify_match_score(self, meta: tuple[str, str] | tuple[str, str, int | None], track: Track) -> float:
        full_meta = self._spotify_meta_with_duration(meta)
        source = self._normalize_text(f"{full_meta[0]} {full_meta[1]}".strip())
        candidate = self._normalize_text(f"{track.title} {track.artist or ''}".strip())
        if not source or not candidate:
            return 0.0
        ratio = difflib.SequenceMatcher(None, source, candidate).ratio()
        source_tokens = set(source.split())
        candidate_tokens = set(candidate.split())
        overlap = 0.0
        duration_score = 0.0
        if source_tokens and candidate_tokens:
            overlap = len(source_tokens & candidate_tokens) / len(source_tokens)
        if full_meta[2] is not None and track.duration_seconds is not None and full_meta[2] > 0:
            duration_delta = abs(full_meta[2] - track.duration_seconds)
            duration_score = max(0.0, 1.0 - (duration_delta / max(full_meta[2], 1)))
        return (ratio * 0.55) + (overlap * 0.15) + (duration_score * 0.30)

    def _pick_spotify_candidate(
        self,
        meta: tuple[str, str] | tuple[str, str, int | None],
        candidates: list[Track],
    ) -> tuple[Track | None, float]:
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

    async def _resolve_spotify_page_tracks(
        self,
        *,
        items: list[dict] | list[object],
        requester: str,
        original_link: str,
    ) -> list[Track]:
        semaphore = asyncio.Semaphore(self._spotify_resolve_concurrency)
        out: list[Track] = []

        async def _resolve_one(
            spotify_track_id: str | None,
            meta: tuple[str, str, int | None, str | None],
            item_link: str,
        ) -> Track:
            async with semaphore:
                return await self._resolve_spotify_track_candidate(
                    spotify_track_id=spotify_track_id,
                    spotify_meta=meta,
                    link=item_link,
                    requester=requester,
                )

        tasks: list[asyncio.Task[Track]] = []
        for item in items:
            track_payload = (
                item.get("item")
                if isinstance(item, dict) and isinstance(item.get("item"), dict)
                else item.get("track")
                if isinstance(item, dict) and isinstance(item.get("track"), dict)
                else item
            )
            if not isinstance(track_payload, dict):
                continue
            if str(track_payload.get("is_local") or "").casefold() == "true":
                continue
            spotify_track_id = str(track_payload.get("id") or "").strip() or None
            meta = self._spotify_track_payload_meta(track_payload)
            if meta is None:
                continue
            isrc = self._spotify_track_payload_isrc(track_payload)
            item_link = str(
                ((track_payload.get("external_urls") or {}) if isinstance(track_payload.get("external_urls"), dict) else {}).get("spotify")
                or original_link
            )
            tasks.append(asyncio.create_task(_resolve_one(spotify_track_id, (meta[0], meta[1], meta[2], isrc), item_link)))
        if not tasks:
            return out
        for result in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(result, Track):
                out.append(result)
        return out

    async def _resolve_spotify_track_candidate(
        self,
        *,
        spotify_track_id: str | None,
        spotify_meta: tuple[str, str] | tuple[str, str, int | None] | tuple[str, str, int | None, str | None],
        link: str,
        requester: str,
    ) -> Track:
        full_meta = self._spotify_meta_with_duration(spotify_meta)
        isrc = spotify_meta[3] if len(spotify_meta) >= 4 else None
        if spotify_track_id:
            try:
                cached = await self._spotify_cached_track(
                    spotify_track_id=spotify_track_id,
                    requester=requester,
                    original_link=link,
                )
            except RuntimeError:
                fallback = self._spotify_fallback_track((full_meta[0], full_meta[1]), link, requester=requester)
                fallback.duration_seconds = full_meta[2]
                return fallback
            if cached is not None:
                return cached

        try:
            candidates = await asyncio.wait_for(
                self._search_spotify_candidates(
                    title=full_meta[0],
                    artist=full_meta[1],
                    isrc=isrc,
                    requester=requester,
                ),
                timeout=8.0,
            )
        except asyncio.TimeoutError:
            candidates = []

        if not candidates:
            if spotify_track_id:
                await self._store_spotify_cache_miss(spotify_track_id, "no_candidates")
            fallback = self._spotify_fallback_track((full_meta[0], full_meta[1]), link, requester=requester)
            fallback.duration_seconds = full_meta[2]
            return fallback

        picked, _score = self._pick_spotify_candidate(full_meta, candidates)
        if picked is None:
            if spotify_track_id:
                await self._store_spotify_cache_miss(spotify_track_id, "low_confidence_match")
            fallback = self._spotify_fallback_track((full_meta[0], full_meta[1]), link, requester=requester)
            fallback.duration_seconds = full_meta[2]
            return fallback

        if picked.duration_seconds is None:
            picked.duration_seconds = full_meta[2]
        if not picked.artist:
            picked.artist = full_meta[1] or None
        if not picked.isrc and isrc:
            picked.isrc = isrc
        if spotify_track_id:
            await self._store_spotify_cache_hit(spotify_track_id, picked)
        return picked

    async def _search_spotify_candidates(
        self,
        *,
        title: str,
        artist: str,
        isrc: str | None,
        requester: str,
    ) -> list[Track]:
        queries: list[str] = []

        def _add(value: str) -> None:
            normalized = " ".join(value.strip().split())
            if normalized and normalized not in queries:
                queries.append(normalized)

        if isrc:
            _add(f"{title} {artist} {isrc}")
        _add(f"{title} {artist}")
        _add(f"{artist} {title}")
        _add(f"{title} audio")

        candidates: list[Track] = []
        seen_keys: set[tuple[str, str]] = set()
        for query in queries[:3]:
            results = await self.search_tracks(query, requester=requester, limit=self.spotify_candidate_limit)
            for item in results:
                key = (item.source_query, item.webpage_url)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                candidates.append(item)
        return candidates

    async def _spotify_cached_track(
        self,
        *,
        spotify_track_id: str,
        requester: str,
        original_link: str,
    ) -> Track | None:
        record = await self._spotify_resolve_cache_record(spotify_track_id)
        if record is None:
            return None
        age = int(time.time()) - int(record.cached_at_unix)
        if record.status == "ok":
            if age > self._spotify_resolve_cache_ttl_seconds:
                return None
            LOGGER.info("spotify_resolve_cache_hit track_id=%s status=ok age=%s", spotify_track_id, age)
            return Track(
                source_query=record.source_query,
                title=record.title,
                webpage_url=record.webpage_url or original_link,
                requested_by=requester,
                artist=record.artist or None,
                duration_seconds=record.duration_seconds,
                isrc=record.isrc or None,
            )
        if age <= self._spotify_resolve_failure_cache_ttl_seconds:
            LOGGER.info(
                "spotify_resolve_cache_hit track_id=%s status=miss age=%s reason=%s",
                spotify_track_id,
                age,
                record.failure_reason or "unknown",
            )
            raise RuntimeError("Spotify nao resolvido: correspondencia reproduzivel indisponivel em cache recente.")
        return None

    async def _spotify_resolve_cache_record(self, spotify_track_id: str) -> Any | None:
        if self.store is None or not hasattr(self.store, "get_spotify_resolve_cache"):
            return None
        return await self.store.get_spotify_resolve_cache(spotify_track_id)

    async def _store_spotify_cache_hit(self, spotify_track_id: str, track: Track) -> None:
        if self.store is None or not hasattr(self.store, "upsert_spotify_resolve_cache"):
            return
        await self.store.upsert_spotify_resolve_cache(
            spotify_track_id=spotify_track_id,
            status="ok",
            source_query=track.source_query,
            webpage_url=track.webpage_url,
            title=track.title,
            artist=track.artist or "",
            duration_seconds=track.duration_seconds,
            isrc=track.isrc or "",
            failure_reason="",
        )

    async def _store_spotify_cache_miss(self, spotify_track_id: str, reason: str) -> None:
        if self.store is None or not hasattr(self.store, "upsert_spotify_resolve_cache"):
            return
        await self.store.upsert_spotify_resolve_cache(
            spotify_track_id=spotify_track_id,
            status="miss",
            failure_reason=reason,
        )
