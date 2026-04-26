from __future__ import annotations

import asyncio
import os
import random
import re
import shutil
import tempfile
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import parse_qs, urlparse
from urllib.parse import urlunparse

import discord
import yt_dlp

LOGGER = __import__("logging").getLogger("botmusica.music")

YTDL_OPTIONS: dict[str, Any] = {
    "format": "bestaudio[acodec^=opus]/bestaudio[ext=webm]/bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "default_search": "auto",
    "extract_flat": False,
    "prefer_ffmpeg": True,
    "format_sort": ["acodec:opus", "abr", "asr", "channels"],
    "retries": 5,
    "extractor_retries": 3,
    "fragment_retries": 5,
    "socket_timeout": 15,
    "ignoreerrors": True,
    # Ordem de preferência de clientes:
    # - tv_embedded: mais resistente ao bot detection sem precisar de cookies
    # - android_vr: alternativa quando web retorna URLs SABR/403
    # - web: fallback padrão
    "extractor_args": {"youtube": {"player_client": ["tv_embedded", "android_vr", "web"]}},
}

BASE_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FILTERS: dict[str, str] = {
    "off": "anull",
    "bassboost": "bass=g=8",
    "nightcore": "asetrate=48000*1.1,aresample=48000,atempo=1.0",
    "vaporwave": "asetrate=48000*0.8,aresample=48000,atempo=1.0",
    "karaoke": "pan=stereo|c0=c0-c1|c1=c1-c0",
}


@dataclass(slots=True)
class Track:
    source_query: str
    title: str
    webpage_url: str
    requested_by: str
    artist: str | None = None
    duration_seconds: int | None = None
    isrc: str | None = None


@dataclass(slots=True)
class TrackBatch:
    tracks: list[Track]
    total_items: int
    invalid_items: int


class GuildPlayer:
    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        self.queue: asyncio.Queue[Track] = asyncio.Queue()
        self.current: Track | None = None
        self.volume: float = 1.0
        self.loop_mode: str = "off"
        self.autoplay: bool = False
        self.stay_connected: bool = False
        self.audio_filter: str = "off"
        self.current_started_at: float | None = None
        self.pause_started_at: float | None = None
        self.paused_accumulated_seconds: float = 0.0
        self.pending_seek_seconds: int = 0
        self.suppress_after_playback: bool = False
        self.restored_queue_pending_activation: bool = False

    async def enqueue(self, track: Track) -> None:
        await self.queue.put(track)

    def enqueue_front(self, track: Track) -> None:
        self.queue._queue.appendleft(track)  # noqa: SLF001 - ajuste controlado da fila

    def clear_queue(self) -> list[Track]:
        removed: list[Track] = []
        while not self.queue.empty():
            removed.append(self.queue.get_nowait())
            self.queue.task_done()
        return removed

    def snapshot_queue(self) -> list[Track]:
        return list(self.queue._queue)  # noqa: SLF001 - leitura controlada para exibir fila

    def remove_from_queue(self, position: int) -> Track:
        if position < 1:
            raise ValueError("Posicao deve comecar em 1.")

        items = self.snapshot_queue()
        if position > len(items):
            raise IndexError("Posicao fora da fila.")

        removed = items.pop(position - 1)
        self.queue._queue.clear()  # noqa: SLF001 - ajuste controlado da fila
        self.queue._queue.extend(items)  # noqa: SLF001 - ajuste controlado da fila
        return removed

    def shuffle_queue(self) -> int:
        items = self.snapshot_queue()
        if len(items) <= 1:
            return len(items)

        random.shuffle(items)
        self.queue._queue.clear()  # noqa: SLF001 - ajuste controlado da fila
        self.queue._queue.extend(items)  # noqa: SLF001 - ajuste controlado da fila
        return len(items)

    def move_in_queue(self, source_pos: int, target_pos: int) -> Track:
        items = self.snapshot_queue()
        if source_pos < 1 or target_pos < 1 or source_pos > len(items) or target_pos > len(items):
            raise IndexError("Posicao invalida.")

        moved = items.pop(source_pos - 1)
        items.insert(target_pos - 1, moved)
        self.queue._queue.clear()  # noqa: SLF001 - ajuste controlado da fila
        self.queue._queue.extend(items)  # noqa: SLF001 - ajuste controlado da fila
        return moved

    def jump_to_front(self, position: int) -> Track:
        items = self.snapshot_queue()
        if position < 1 or position > len(items):
            raise IndexError("Posicao invalida.")

        picked = items.pop(position - 1)
        items.insert(0, picked)
        self.queue._queue.clear()  # noqa: SLF001 - ajuste controlado da fila
        self.queue._queue.extend(items)  # noqa: SLF001 - ajuste controlado da fila
        return picked


class MusicService:
    def __init__(self) -> None:
        self._hq_audio_enabled = os.getenv("MUSIC_HQ_AUDIO", "true").strip().casefold() in {"1", "true", "yes", "on"}
        self._fast_mode = os.getenv("MUSIC_FAST_MODE", "true").strip().casefold() in {"1", "true", "yes", "on"}
        cookies_file = os.getenv("YTDLP_COOKIES_FILE", "").strip()
        cookies_from_browser = os.getenv("YTDLP_COOKIES_FROM_BROWSER", "").strip()
        js_runtime = os.getenv("YTDLP_JS_RUNTIME", "").strip()
        if js_runtime:
            runtime_name, _, runtime_path = js_runtime.partition(":")
            runtime_name = runtime_name.strip()
            runtime_path = runtime_path.strip()
            if runtime_path and not os.path.exists(runtime_path):
                LOGGER.warning("Ignorando YTDLP_JS_RUNTIME invalido: %s", js_runtime)
                js_runtime = ""
        if not js_runtime:
            deno_path = shutil.which("deno")
            node_path = shutil.which("node")
            if deno_path:
                js_runtime = f"deno:{deno_path}"
            elif node_path:
                js_runtime = f"node:{node_path}"

        if cookies_file:
            cookies_file = self._prepare_cookiefile(cookies_file)

        remote_components = os.getenv("YTDLP_REMOTE_COMPONENTS", "ejs:github").strip()
        ytdl_options = dict(YTDL_OPTIONS)
        if self._fast_mode:
            ytdl_options["retries"] = 2
            ytdl_options["extractor_retries"] = 1
            ytdl_options["fragment_retries"] = 1
            ytdl_options["socket_timeout"] = 8
        if cookies_file:
            ytdl_options["cookiefile"] = cookies_file
        if cookies_from_browser:
            # Ex.: chrome, firefox, safari, brave
            ytdl_options["cookiesfrombrowser"] = (cookies_from_browser,)
        if js_runtime:
            runtime_name, _, runtime_path = js_runtime.partition(":")
            runtime_name = runtime_name.strip()
            runtime_cfg: dict[str, str] = {}
            if runtime_path.strip():
                runtime_cfg["path"] = runtime_path.strip()
            if runtime_name:
                ytdl_options["js_runtimes"] = {runtime_name: runtime_cfg}
        if remote_components:
            ytdl_options["remote_components"] = [item.strip() for item in remote_components.split(",") if item.strip()]
        self._players: dict[int, GuildPlayer] = {}
        self._ytdl = yt_dlp.YoutubeDL(ytdl_options)
        ytdl_playlist_options = dict(ytdl_options)
        ytdl_playlist_options["noplaylist"] = False
        # Extracao "flat" acelera muito playlists grandes (metadados leves).
        # O stream real continua sendo resolvido apenas quando a faixa tocar.
        ytdl_playlist_options["extract_flat"] = "in_playlist"
        # Em playlists grandes, alguns itens podem estar privados/indisponiveis.
        # Com ignoreerrors, o yt-dlp segue com os demais itens publicos.
        ytdl_playlist_options["ignoreerrors"] = True
        self._ytdl_playlist_options = dict(ytdl_playlist_options)
        self._ytdl_playlist = yt_dlp.YoutubeDL(self._ytdl_playlist_options)
        self._cache_ttl_seconds = max(int(os.getenv("YTDLP_CACHE_SECONDS", "600").strip() or "600"), 0)
        self._stream_cache_ttl_seconds = max(int(os.getenv("YTDLP_STREAM_CACHE_SECONDS", "1800").strip() or "1800"), 0)
        self._cache_max_entries = max(int(os.getenv("YTDLP_CACHE_MAX_ENTRIES", "512").strip() or "512"), 32)
        self._retry_delays: tuple[float, ...] = (0.0, 0.35) if self._fast_mode else (0.0, 0.8, 1.6)
        self._extract_cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._stream_url_cache: OrderedDict[str, tuple[float, str, dict[str, str]]] = OrderedDict()
        self._worker_concurrency = max(int(os.getenv("YTDLP_WORKER_CONCURRENCY", "2").strip() or "2"), 1)
        self._worker_queue_maxsize = max(int(os.getenv("YTDLP_WORKER_QUEUE_SIZE", "128").strip() or "128"), 16)
        self._extract_jobs: asyncio.Queue[tuple[yt_dlp.YoutubeDL, str, asyncio.Future[dict[str, Any]]]] | None = None
        self._extract_workers: list[asyncio.Task[None]] = []
        self._backpressure_enabled = os.getenv("FEATURE_EXTRACTION_BACKPRESSURE_ENABLED", "true").strip().casefold() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._global_extract_semaphore = asyncio.Semaphore(
            max(int(os.getenv("YTDLP_GLOBAL_CONCURRENCY", "6").strip() or "6"), 1)
        )
        provider_limit = max(int(os.getenv("YTDLP_PROVIDER_CONCURRENCY", "3").strip() or "3"), 1)
        self._provider_extract_semaphores: dict[str, asyncio.Semaphore] = {
            "youtube": asyncio.Semaphore(provider_limit),
            "spotify": asyncio.Semaphore(provider_limit),
            "other": asyncio.Semaphore(provider_limit),
        }

    @staticmethod
    def _prepare_cookiefile(cookiefile: str) -> str:
        path = (cookiefile or "").strip()
        if not path:
            return path
        if not os.path.exists(path):
            return path
        if os.access(path, os.W_OK):
            return path
        fd, writable_copy = tempfile.mkstemp(prefix="yt-dlp-cookies-", suffix=".txt")
        os.close(fd)
        shutil.copyfile(path, writable_copy)
        return writable_copy

    def _ensure_extract_workers(self) -> asyncio.Queue[tuple[yt_dlp.YoutubeDL, str, asyncio.Future[dict[str, Any]]]]:
        queue = self._extract_jobs
        if queue is None:
            queue = asyncio.Queue(maxsize=self._worker_queue_maxsize)
            self._extract_jobs = queue
        if not self._extract_workers:
            for _ in range(self._worker_concurrency):
                self._extract_workers.append(asyncio.create_task(self._extract_worker_loop(queue)))
        return queue

    async def _extract_worker_loop(
        self,
        queue: asyncio.Queue[tuple[yt_dlp.YoutubeDL, str, asyncio.Future[dict[str, Any]]]],
    ) -> None:
        while True:
            ytdl, query, future = await queue.get()
            try:
                if future.cancelled():
                    continue
                payload = await asyncio.to_thread(ytdl.extract_info, query, False)
                if payload is None:
                    raise RuntimeError("Nao foi possivel extrair informacoes desse link.")
                if not isinstance(payload, dict):
                    raise RuntimeError("Resposta invalida do extrator.")
                if not future.done():
                    future.set_result(cast(dict[str, Any], payload))
            except Exception as exc:  # noqa: BLE001
                if not future.done():
                    future.set_exception(exc)
            finally:
                queue.task_done()

    async def _extract_with_worker(self, ytdl: yt_dlp.YoutubeDL, query: str) -> dict[str, Any]:
        queue = self._ensure_extract_workers()
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        await queue.put((ytdl, query, future))
        return await future

    def get_player(self, guild_id: int) -> GuildPlayer:
        player = self._players.get(guild_id)
        if player is None:
            player = GuildPlayer(guild_id)
            self._players[guild_id] = player
        return player

    def extract_backlog_stats(self) -> tuple[int, int]:
        queue = self._extract_jobs
        if queue is None:
            return 0, self._worker_queue_maxsize
        return queue.qsize(), queue.maxsize

    def remove_player(self, guild_id: int) -> None:
        self._players.pop(guild_id, None)

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        message = str(exc).lower()
        retry_tokens = (
            "http error 429",
            "http error 503",
            "too many requests",
            "service unavailable",
            "timed out",
            "temporarily unavailable",
        )
        return any(token in message for token in retry_tokens)

    def _cache_get_extract(self, key: str) -> dict[str, Any] | None:
        if self._cache_ttl_seconds <= 0:
            return None
        cached = self._extract_cache.get(key)
        if cached is None:
            return None
        expires_at, payload = cached
        if expires_at < time.monotonic():
            self._extract_cache.pop(key, None)
            return None
        self._extract_cache.move_to_end(key)
        return payload

    def _cache_put_extract(self, key: str, payload: dict[str, Any]) -> None:
        if self._cache_ttl_seconds <= 0:
            return
        self._extract_cache[key] = (time.monotonic() + self._cache_ttl_seconds, payload)
        self._extract_cache.move_to_end(key)
        while len(self._extract_cache) > self._cache_max_entries:
            self._extract_cache.popitem(last=False)

    def _cache_get_stream_url(self, source_query: str) -> tuple[str, dict[str, str]] | None:
        if self._stream_cache_ttl_seconds <= 0:
            return None
        cached = self._stream_url_cache.get(source_query)
        if cached is None:
            return None
        expires_at, stream_url, headers = cached
        if expires_at < time.monotonic():
            self._stream_url_cache.pop(source_query, None)
            LOGGER.info("stream_cache expired query=%s", self._redact_url_for_log(source_query))
            return None
        self._stream_url_cache.move_to_end(source_query)
        LOGGER.info(
            "stream_cache hit query=%s stream=%s header_keys=%s",
            self._redact_url_for_log(source_query),
            self._redact_url_for_log(stream_url),
            sorted(headers.keys()),
        )
        return stream_url, headers

    def _cache_put_stream_url(self, source_query: str, stream_url: str, headers: dict[str, str] | None = None) -> None:
        if self._stream_cache_ttl_seconds <= 0:
            return
        self._stream_url_cache[source_query] = (
            time.monotonic() + self._stream_cache_ttl_seconds,
            stream_url,
            dict(headers or {}),
        )
        self._stream_url_cache.move_to_end(source_query)
        LOGGER.info(
            "stream_cache put query=%s stream=%s ttl=%ss header_keys=%s",
            self._redact_url_for_log(source_query),
            self._redact_url_for_log(stream_url),
            self._stream_cache_ttl_seconds,
            sorted((headers or {}).keys()),
        )
        while len(self._stream_url_cache) > self._cache_max_entries:
            self._stream_url_cache.popitem(last=False)

    def drop_stream_cache(self, source_query: str) -> None:
        removed = self._stream_url_cache.pop(source_query, None)
        extract_removed = self._extract_cache.pop(f"stream:{source_query}", None)
        canonical_query = self._canonicalize_query_url(source_query)
        if canonical_query != source_query:
            self._extract_cache.pop(f"stream:{canonical_query}", None)
        if removed is not None:
            LOGGER.info("stream_cache drop query=%s", self._redact_url_for_log(source_query))
        if extract_removed is not None:
            LOGGER.info("extract_cache drop key=stream:%s", self._redact_url_for_log(source_query))

    @staticmethod
    def _redact_url_for_log(value: str | None) -> str:
        raw = (value or "").strip()
        if not raw:
            return ""
        if "://" not in raw:
            return raw[:180]
        try:
            parsed = urlparse(raw)
        except ValueError:
            return raw[:180]
        query = "<query-redacted>" if parsed.query else ""
        redacted = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", query, ""))
        return redacted[:220]

    async def _extract_info_with_retry(self, ytdl: yt_dlp.YoutubeDL, query: str, *, cache_key: str) -> dict[str, Any]:
        cached_payload = self._cache_get_extract(cache_key)
        if cached_payload is not None:
            return cached_payload

        last_error: Exception | None = None
        for delay_seconds in self._retry_delays:
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
            try:
                if self._backpressure_enabled:
                    provider_key = self._provider_key_from_query(query)
                    provider_sem = self._provider_extract_semaphores.get(provider_key, self._provider_extract_semaphores["other"])
                    async with self._global_extract_semaphore:
                        async with provider_sem:
                            payload = await self._extract_with_worker(ytdl, query)
                else:
                    payload = await self._extract_with_worker(ytdl, query)
                self._cache_put_extract(cache_key, payload)
                return payload
            except Exception as exc:  # noqa: BLE001 - excecao propagada com contexto no final
                last_error = exc
                if not self._is_retryable_error(exc):
                    break
        if last_error is not None:
            raise last_error
        raise RuntimeError("Falha ao extrair informacoes.")

    @staticmethod
    def _canonicalize_query_url(query: str) -> str:
        raw = (query or "").strip()
        lowered = raw.casefold()
        if lowered.startswith("ytmsearch:"):
            terms = raw.split(":", 1)[1].strip()
            return f"ytsearch5:{terms}" if terms else "ytsearch5:audio"
        if "://" not in raw:
            return raw
        try:
            parsed = urlparse(raw)
        except ValueError:
            return raw
        host = (parsed.hostname or "").casefold()
        if host != "music.youtube.com":
            return raw
        # yt-dlp/lavaplayer são mais estáveis com www.youtube.com.
        netloc = "www.youtube.com"
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        converted = parsed._replace(netloc=netloc)
        return urlunparse(converted)

    @staticmethod
    def _clean_search_terms(value: str) -> str:
        cleaned = (value or "").strip()
        cleaned = re.sub(r'"', ' ', cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"[\[\](){}|]+", " ", cleaned)
        cleaned = re.sub(r"\b(feat|ft)\.?\b.*$", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(official|video|audio|lyrics|visualizer|remaster(?:ed)?)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_:")
        return cleaned

    @staticmethod
    def _is_uploaderish_artist(value: str) -> bool:
        lowered = (value or "").casefold()
        if not lowered:
            return False
        return any(token in lowered for token in ("vevo", "topic", "records", "musicbr", "official"))

    @classmethod
    def _title_variants(cls, title: str, artist: str) -> list[str]:
        variants: list[str] = []

        def _add(value: str) -> None:
            cleaned = cls._clean_search_terms(value)
            if cleaned and cleaned not in variants:
                variants.append(cleaned)

        _add(title)
        if " - " in title:
            left, right = [part.strip() for part in title.split(" - ", 1)]
            _add(right)
            if artist and left.casefold() != artist.casefold():
                _add(f"{left} {right}")
        return variants

    @classmethod
    def _candidate_source_queries(cls, track: Track) -> list[str]:
        primary = cls._canonicalize_query_url(track.source_query)
        candidates: list[str] = []

        def _add(value: str) -> None:
            normalized = cls._canonicalize_query_url(value)
            if normalized and normalized not in candidates:
                candidates.append(normalized)

        _add(primary)
        artist = cls._clean_search_terms(track.artist or "")
        if cls._is_uploaderish_artist(artist):
            artist = ""
        titles = cls._title_variants(track.title, artist)
        for title in titles:
            if title and artist:
                _add(f"ytsearch5:{title} {artist} audio")
                _add(f"ytsearch5:{artist} {title} audio")
            if title:
                _add(f"ytsearch5:{title} audio")
                _add(f"ytsearch5:{title}")
        if artist and titles:
            _add(f"ytsearch5:{artist} {titles[0]}".strip())
        return candidates

    @staticmethod
    def _provider_key_from_query(query: str) -> str:
        value = (query or "").casefold()
        if "youtube.com" in value or "youtu.be" in value or value.startswith("ytsearch"):
            return "youtube"
        if "spotify.com" in value:
            return "spotify"
        return "other"

    @staticmethod
    def _extract_entry(data: dict[str, Any]) -> dict[str, Any]:
        if "entries" not in data:
            return data

        entry = next((item for item in data["entries"] if item), None)
        if entry is None:
            raise RuntimeError("Nenhum audio valido foi encontrado para esse item.")
        return entry

    @classmethod
    def _entry_source_queries_from_payload(cls, payload: dict[str, Any], fallback_query: str) -> list[str]:
        entries = payload.get("entries")
        if not isinstance(entries, list):
            return []
        queries: list[str] = []
        for item in entries:
            if not isinstance(item, dict):
                continue
            candidate = cls._normalize_source_query(item, fallback_query)
            candidate = cls._canonicalize_query_url(candidate)
            if not candidate or candidate in queries:
                continue
            queries.append(candidate)
        return queries

    @staticmethod
    def _headers_from_payload(payload: dict[str, Any]) -> dict[str, str]:
        headers_raw = payload.get("http_headers")
        if not isinstance(headers_raw, dict):
            return {}
        return {str(key): str(value) for key, value in headers_raw.items() if value is not None}

    @staticmethod
    def _format_client_tag(item: dict[str, Any]) -> str:
        raw_url = item.get("url")
        if not isinstance(raw_url, str) or not raw_url:
            return ""
        try:
            parsed = urlparse(raw_url)
        except ValueError:
            return ""
        return (parse_qs(parsed.query).get("c") or [""])[0].strip().upper()

    @staticmethod
    def _is_audio_capable_format(item: dict[str, Any]) -> bool:
        if not isinstance(item, dict):
            return False
        if not item.get("url"):
            return False
        acodec = str(item.get("acodec") or "none").casefold()
        vcodec = str(item.get("vcodec") or "none").casefold()
        if acodec in {"", "none"}:
            return False
        # Ignora formatos de imagem/storyboard ou similares sem midia utilizavel.
        if vcodec in {"mhtml"}:
            return False
        return True

    @staticmethod
    def _is_audio_only_format(item: dict[str, Any]) -> bool:
        if not MusicService._is_audio_capable_format(item):
            return False
        return str(item.get("vcodec") or "none").casefold() == "none"

    @classmethod
    def _format_preference_key(cls, item: dict[str, Any]) -> tuple[int, int, int, int, float, float]:
        client_tag = cls._format_client_tag(item)
        client_penalty = 1 if client_tag in {"", "WEB", "WEB_SAFARI"} else 0
        vcodec_penalty = 1 if str(item.get("vcodec") or "none").casefold() != "none" else 0
        acodec_penalty = 1 if str(item.get("acodec") or "").casefold() != "opus" else 0
        ext_penalty = 1 if str(item.get("ext") or "").casefold() not in {"webm", "m4a"} else 0
        abr = float(item.get("abr") or 0.0)
        asr = float(item.get("asr") or 0.0)
        return (client_penalty, vcodec_penalty, acodec_penalty, ext_penalty, -abr, -asr)

    @classmethod
    def _stream_from_payload(cls, payload: dict[str, Any]) -> tuple[str | None, dict[str, str]]:
        requested_formats = payload.get("requested_formats")
        if isinstance(requested_formats, list):
            requested_candidates = [item for item in requested_formats if cls._is_audio_capable_format(item)]
            requested_audio_only = [item for item in requested_candidates if cls._is_audio_only_format(item)]
            preferred_requested = sorted(
                requested_audio_only or requested_candidates,
                key=cls._format_preference_key,
            )
            audio_format = preferred_requested[0] if preferred_requested else None
            if isinstance(audio_format, dict):
                LOGGER.info(
                    "build_audio_source selected requested_format id=%s acodec=%s vcodec=%s ext=%s client=%s audio_only_available=%s",
                    audio_format.get("format_id"),
                    audio_format.get("acodec"),
                    audio_format.get("vcodec"),
                    audio_format.get("ext"),
                    cls._format_client_tag(audio_format),
                    bool(requested_audio_only),
                )
                return str(audio_format.get("url") or ""), cls._headers_from_payload(audio_format)

        formats = payload.get("formats")
        if isinstance(formats, list):
            audio_candidates: list[dict[str, Any]] = [
                item
                for item in formats
                if cls._is_audio_capable_format(item)
            ]
            if audio_candidates:
                audio_only_candidates = [item for item in audio_candidates if cls._is_audio_only_format(item)]
                preferred = sorted(audio_only_candidates or audio_candidates, key=cls._format_preference_key)[0]
                LOGGER.info(
                    "build_audio_source selected format id=%s acodec=%s vcodec=%s ext=%s client=%s audio_only_available=%s",
                    preferred.get("format_id"),
                    preferred.get("acodec"),
                    preferred.get("vcodec"),
                    preferred.get("ext"),
                    cls._format_client_tag(preferred),
                    bool(audio_only_candidates),
                )
                return str(preferred.get("url") or ""), cls._headers_from_payload(preferred)

        direct_url = payload.get("url")
        if isinstance(direct_url, str) and direct_url.strip():
            if not cls._is_audio_capable_format(payload):
                LOGGER.info(
                    "build_audio_source ignored direct url without audio format metadata extractor=%s vcodec=%s acodec=%s",
                    payload.get("extractor"),
                    payload.get("vcodec"),
                    payload.get("acodec"),
                )
                return None, {}
            if str(payload.get("vcodec") or "none").casefold() != "none":
                LOGGER.info(
                    "build_audio_source ignored muxed direct url extractor=%s format_id=%s client=%s",
                    payload.get("extractor"),
                    payload.get("format_id"),
                    cls._format_client_tag(payload),
                )
                return None, {}
            return direct_url.strip(), cls._headers_from_payload(payload)
        return None, {}

    @staticmethod
    def _normalize_source_query(data: dict[str, Any], fallback_query: str) -> str:
        raw_url = data.get("webpage_url") or data.get("original_url") or data.get("url") or fallback_query
        if not isinstance(raw_url, str):
            return fallback_query
        value = raw_url.strip()
        if "://" in value:
            return value

        ie_key = str(data.get("ie_key") or "").casefold()
        extractor = str(data.get("extractor") or "").casefold()
        if "youtube" in ie_key or "youtube" in extractor:
            normalized = f"https://www.youtube.com/watch?v={value}"
            return MusicService._canonicalize_query_url(normalized)
        return MusicService._canonicalize_query_url(value or fallback_query)

    @classmethod
    def _track_from_data(cls, data: dict[str, Any], fallback_query: str, requester: str) -> Track:
        page_url = cls._normalize_source_query(data, fallback_query)
        title = data.get("title") or page_url
        duration_raw = data.get("duration")
        duration = int(duration_raw) if isinstance(duration_raw, (int, float)) else None
        artist_raw = (
            data.get("artist")
            or data.get("uploader")
            or data.get("channel")
            or data.get("creator")
            or data.get("uploader_id")
            or None
        )
        artist = str(artist_raw).strip() if artist_raw is not None else None
        if artist == "":
            artist = None
        return Track(
            source_query=page_url,
            title=title,
            webpage_url=page_url,
            requested_by=requester,
            artist=artist,
            duration_seconds=duration,
        )

    async def extract_track(self, query: str, requester: str) -> Track:
        normalized_query = self._canonicalize_query_url(query)
        data = await self._extract_info_with_retry(self._ytdl, normalized_query, cache_key=f"single:{normalized_query}")
        data = self._extract_entry(data)
        return self._track_from_data(data, fallback_query=normalized_query, requester=requester)

    @staticmethod
    def _youtube_playlist_url_from_query(query: str) -> str | None:
        raw = query.strip()
        if "://" not in raw:
            return None
        try:
            parsed = urlparse(raw)
        except ValueError:
            return None
        host = (parsed.hostname or "").casefold()
        if host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}:
            return None
        params = parse_qs(parsed.query)
        list_ids = params.get("list") or []
        if not list_ids:
            return None
        list_id = list_ids[0].strip()
        if not list_id:
            return None
        return f"https://www.youtube.com/playlist?list={list_id}"

    def _build_batch_from_payload(self, data: dict[str, Any], *, fallback_query: str, requester: str) -> TrackBatch:
        entries_raw = data.get("entries") if isinstance(data, dict) else None
        if isinstance(entries_raw, list):
            total_items_raw = data.get("playlist_count") if isinstance(data, dict) else None
            total_items = int(total_items_raw) if isinstance(total_items_raw, (int, float)) else len(entries_raw)
            total_items = max(total_items, len(entries_raw))
            tracks: list[Track] = []
            invalid_items = 0
            for entry in entries_raw:
                if not entry:
                    invalid_items += 1
                    continue
                try:
                    tracks.append(self._track_from_data(entry, fallback_query=fallback_query, requester=requester))
                except Exception:
                    invalid_items += 1
            if not tracks:
                raise RuntimeError("Nenhum audio valido foi encontrado para esse item.")
            return TrackBatch(tracks=tracks, total_items=total_items, invalid_items=invalid_items)

        track = self._track_from_data(self._extract_entry(data), fallback_query=fallback_query, requester=requester)
        return TrackBatch(tracks=[track], total_items=1, invalid_items=0)

    async def extract_tracks(self, query: str, requester: str, *, max_items: int | None = None) -> TrackBatch:
        normalized_query = self._canonicalize_query_url(query)
        extractor = self._ytdl_playlist
        cache_key = f"playlist:{normalized_query}"
        if max_items is not None and max_items > 0:
            partial_options = dict(self._ytdl_playlist_options)
            partial_options["playlist_items"] = f"1-{max_items}"
            extractor = yt_dlp.YoutubeDL(partial_options)
            cache_key = f"playlist:{max_items}:{normalized_query}"

        data = await self._extract_info_with_retry(extractor, normalized_query, cache_key=cache_key)
        batch = self._build_batch_from_payload(data, fallback_query=normalized_query, requester=requester)
        if batch.total_items > 1:
            return batch

        playlist_url = self._youtube_playlist_url_from_query(normalized_query)
        if playlist_url and playlist_url != normalized_query:
            retry_payload = await self._extract_info_with_retry(
                extractor,
                playlist_url,
                cache_key=f"{cache_key}:{playlist_url}",
            )
            retry_batch = self._build_batch_from_payload(retry_payload, fallback_query=playlist_url, requester=requester)
            if retry_batch.total_items > 1:
                return retry_batch
        return batch

    async def search_tracks(self, query: str, requester: str, *, limit: int = 5) -> list[Track]:
        if limit < 1:
            return []

        payload = await self._extract_info_with_retry(
            self._ytdl,
            f"ytsearch{limit}:{query}",
            cache_key=f"search:{limit}:{query}",
        )

        entries: list[dict[str, Any]] = []
        if "entries" in payload and isinstance(payload["entries"], list):
            entries = [item for item in payload["entries"] if item]
        elif isinstance(payload, dict):
            entries = [payload]

        tracks: list[Track] = []
        for entry in entries:
            try:
                tracks.append(self._track_from_data(entry, fallback_query=query, requester=requester))
            except Exception:
                continue
        return tracks

    @staticmethod
    def _build_ffmpeg_options(
        audio_filter: str,
        start_seconds: int,
        *,
        hq_audio_enabled: bool = True,
        request_headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        before_options = BASE_BEFORE_OPTIONS
        if start_seconds > 0:
            before_options = f"{before_options} -ss {start_seconds}"
        if request_headers:
            header_lines = "".join(f"{key}: {value}\r\n" for key, value in request_headers.items() if value)
            if header_lines:
                sanitized = header_lines.replace('"', '\\"')
                before_options = f'{before_options} -headers "{sanitized}"'

        # Qualidade padrao: force stereo/48k para Discord.
        # Modo HQ usa resampler soxr para reduzir artefatos de transcodificacao.
        filter_chain: list[str] = []
        if hq_audio_enabled:
            filter_chain.extend(
                [
                    "aformat=sample_fmts=s16:channel_layouts=stereo",
                    "aresample=48000:resampler=soxr:precision=20",
                ]
            )
        selected_filter = FILTERS.get(audio_filter, FILTERS["off"])
        if selected_filter and selected_filter != "anull":
            filter_chain.append(selected_filter)
        if not filter_chain:
            filter_chain.append("anull")
        # FFmpegPCMAudio ja fixa output em 48k/estereo; evitar flags duplicadas.
        options = "-vn -sn -dn"
        options = f"{options} -af {','.join(filter_chain)}"
        return {"before_options": before_options, "options": options}

    @staticmethod
    def _ffmpeg_options_for_log(ffmpeg_options: dict[str, str]) -> dict[str, str]:
        logged = dict(ffmpeg_options)
        before_options = logged.get("before_options", "")
        if "-headers" in before_options:
            logged["before_options"] = "<contains-redacted-http-headers>"
        return logged

    async def build_audio_source(
        self,
        track: Track,
        *,
        volume: float,
        audio_filter: str,
        start_seconds: int = 0,
    ) -> discord.AudioSource:
        source_queries = self._candidate_source_queries(track)
        LOGGER.info(
            "build_audio_source start title=%s artist=%s source_candidates=%s volume=%.2f filter=%s seek=%s",
            track.title,
            track.artist,
            [self._redact_url_for_log(query) for query in source_queries],
            volume,
            audio_filter,
            start_seconds,
        )
        stream_url: str | None = None
        request_headers: dict[str, str] = {}
        last_error: Exception | None = None
        resolved_query = source_queries[0]
        for source_query in source_queries:
            resolved_query = source_query
            cached_stream = self._cache_get_stream_url(source_query)
            if cached_stream:
                stream_url, request_headers = cached_stream
                break
            try:
                LOGGER.info(
                    "build_audio_source attempt title=%s artist=%s query=%s",
                    track.title,
                    track.artist,
                    source_query,
                )
                data = await self._extract_info_with_retry(
                    self._ytdl,
                    source_query,
                    cache_key=f"stream:{source_query}",
                )
                LOGGER.info(
                    "build_audio_source extracted query=%s extractor=%s has_entries=%s has_formats=%s",
                    self._redact_url_for_log(source_query),
                    data.get("extractor"),
                    isinstance(data.get("entries"), list),
                    isinstance(data.get("formats"), list),
                )
                search_entry_queries = self._entry_source_queries_from_payload(data, source_query)
                if search_entry_queries:
                    LOGGER.info(
                        "build_audio_source search entries title=%s entries=%s",
                        track.title,
                        [self._redact_url_for_log(query) for query in search_entry_queries[:5]],
                    )
                    entry_error: Exception | None = None
                    for entry_query in search_entry_queries:
                        cached_entry_stream = self._cache_get_stream_url(entry_query)
                        if cached_entry_stream:
                            stream_url, request_headers = cached_entry_stream
                            if entry_query != track.source_query:
                                track.source_query = entry_query
                            break
                        try:
                            entry_data = await self._extract_info_with_retry(
                                self._ytdl,
                                entry_query,
                                cache_key=f"stream:{entry_query}",
                            )
                            LOGGER.info(
                                "build_audio_source extracted entry=%s extractor=%s has_formats=%s",
                                self._redact_url_for_log(entry_query),
                                entry_data.get("extractor"),
                                isinstance(entry_data.get("formats"), list),
                            )
                            data = self._extract_entry(entry_data)
                            source_query = entry_query
                            break
                        except Exception as exc:  # noqa: BLE001
                            entry_error = exc
                            continue
                    if stream_url:
                        break
                    if search_entry_queries and entry_error is not None and "entries" in data:
                        raise entry_error
                data = self._extract_entry(data)
                if not track.duration_seconds:
                    duration_raw = data.get("duration")
                    if isinstance(duration_raw, (int, float)) and duration_raw > 0:
                        track.duration_seconds = int(duration_raw)
                artist_raw = (
                    data.get("artist")
                    or data.get("uploader")
                    or data.get("channel")
                    or data.get("creator")
                    or data.get("uploader_id")
                    or None
                )
                if not track.artist and artist_raw is not None:
                    artist = str(artist_raw).strip()
                    if artist:
                        track.artist = artist
                page_url = self._normalize_source_query(data, source_query)
                if page_url:
                    track.webpage_url = page_url
                title_raw = str(data.get("title") or "").strip()
                if title_raw:
                    track.title = title_raw
                stream_url, request_headers = self._stream_from_payload(data)
                if not stream_url:
                    raise RuntimeError("O provedor nao retornou uma URL de stream valida.")
                self._cache_put_stream_url(source_query, stream_url, request_headers)
                if source_query != track.source_query:
                    track.source_query = source_query
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                LOGGER.warning(
                    "build_audio_source failed title=%s artist=%s query=%s",
                    track.title,
                    track.artist,
                    source_query,
                    exc_info=True,
                )
        if not stream_url:
            if last_error is not None:
                raise last_error
            raise RuntimeError(f"Nao foi possivel resolver stream para {resolved_query}.")

        ffmpeg_options = self._build_ffmpeg_options(
            audio_filter=audio_filter,
            start_seconds=start_seconds,
            hq_audio_enabled=self._hq_audio_enabled,
            request_headers=request_headers,
        )
        LOGGER.info(
            "build_audio_source ffmpeg title=%s query=%s stream=%s options=%s header_keys=%s",
            track.title,
            self._redact_url_for_log(resolved_query),
            self._redact_url_for_log(stream_url),
            self._ffmpeg_options_for_log(ffmpeg_options),
            sorted(request_headers.keys()),
        )
        base_source = discord.FFmpegPCMAudio(stream_url, **ffmpeg_options)
        process = getattr(base_source, "_process", None)
        LOGGER.info(
            "build_audio_source ffmpeg_spawned title=%s pid=%s",
            track.title,
            getattr(process, "pid", None),
        )
        return discord.PCMVolumeTransformer(base_source, volume=volume)

    async def prefetch_stream_url(self, track: Track) -> None:
        source_query = self._canonicalize_query_url(track.source_query)
        cached = self._cache_get_stream_url(source_query)
        if cached:
            return
        data = await self._extract_info_with_retry(self._ytdl, source_query, cache_key=f"stream:{source_query}")
        data = self._extract_entry(data)
        stream_url, headers = self._stream_from_payload(data)
        if stream_url:
            self._cache_put_stream_url(source_query, stream_url, headers)

    async def extract_recommended_track(self, from_track: Track, requester: str) -> Track:
        query = f"ytsearch5:{from_track.title} audio"
        return await self.extract_track(query, requester=requester)
