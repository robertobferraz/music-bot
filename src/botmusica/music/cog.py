from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
import os
import time
from collections import OrderedDict, defaultdict, deque
from dataclasses import dataclass
from urllib.parse import urlparse

import discord
from aiohttp import ClientSession, ClientTimeout, web
from discord import app_commands
from discord.ext import commands

from botmusica.music.embeds import MusicEmbeds
from botmusica.music.circuit_breaker import CircuitBreaker
from botmusica.music.autocomplete_utils import merge_suggestions
from botmusica.music.errors import map_extraction_exception, should_count_provider_failure
from botmusica.music.player import FILTERS, GuildPlayer, MusicService, Track, TrackBatch
from botmusica.music.queue_service import QueueService
from botmusica.music.repository import create_repository
from botmusica.music.resolver import MusicResolver
from botmusica.music.services.command_metrics import CommandMetricsWindow
from botmusica.music.services.command_service import CommandService
from botmusica.music.services.dns_cache import DnsCache
from botmusica.music.services.feature_flags import FeatureFlags
from botmusica.music.services.nowplaying_controller import NowPlayingController
from botmusica.music.services.playback_scheduler import PlaybackScheduler
from botmusica.music.services.playlist_jobs import PlaylistJobQueue
from botmusica.music.services.player_state import PlayerState, PlayerStateMachine
from botmusica.music.services.prefetch import pick_prefetch_candidates
from botmusica.music.services.reconnection import ReconnectPolicy
from botmusica.music.services.repositories_split import (
    FavoritesRepository,
    GuildSettingsRepository,
    PlaylistRepository,
    QueueRepository,
)
from botmusica.music.services.search_pipeline import SearchPipeline, SearchPipelineRequest
from botmusica.music.cog_modules.admin_commands import AdminCommandsMixin
from botmusica.music.cog_modules.discovery_cache import DiscoveryCacheMixin
from botmusica.music.cog_modules.event_handlers import EventHandlersMixin
from botmusica.music.cog_modules.interaction import InteractionResponseMixin
from botmusica.music.cog_modules.play_commands import PlayCommandsMixin
from botmusica.music.cog_modules.player_commands import PlayerCommandsMixin
from botmusica.music.cog_modules.playlist_commands import PlaylistFavoritesCommandsMixin
from botmusica.music.cog_modules.runtime_playback import RuntimePlaybackMixin
from botmusica.music.cog_modules.state_policy import GuildPolicy, StatePolicyMixin
from botmusica.music.cog_modules.web_panel import WebPanelMixin
from botmusica.music.storage import (
    SettingsStore,
    VoteStateRecord,
)

LOGGER = logging.getLogger("botmusica.music")


@dataclass(slots=True)
class MetricSnapshot:
    command_calls: int
    command_errors: int
    extraction_failures: int
    playback_failures: int
    average_latency_ms: float


@dataclass(slots=True)
class VoteState:
    channel_id: int
    required: int
    voters: set[int]
    action: str
    created_at: float


class MusicCog(
    InteractionResponseMixin,
    WebPanelMixin,
    DiscoveryCacheMixin,
    PlayCommandsMixin,
    PlaylistFavoritesCommandsMixin,
    PlayerCommandsMixin,
    AdminCommandsMixin,
    RuntimePlaybackMixin,
    EventHandlersMixin,
    StatePolicyMixin,
    commands.Cog,
):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.embeds = MusicEmbeds(bot)
        self.music = MusicService()
        self.store = create_repository(
            db_path=getattr(bot, "db_path", "botmusica.db"),
            backend=str(getattr(bot, "repository_backend", "sqlite")),
            postgres_dsn=str(getattr(bot, "postgres_dsn", "")),
        )
        self.resolver = MusicResolver(
            self.music,
            store=self.store,
            spotify_strict_match=bool(getattr(bot, "spotify_strict_match", True)),
            spotify_match_threshold=float(getattr(bot, "spotify_match_threshold", 0.55)),
            spotify_candidate_limit=int(getattr(bot, "spotify_candidate_limit", 3)),
            spotify_meta_cache_ttl_seconds=float(getattr(bot, "spotify_meta_cache_ttl_seconds", 900.0)),
            spotify_meta_cache_max_entries=int(getattr(bot, "spotify_meta_cache_max_entries", 256)),
        )
        self.queue_service = QueueService()
        self._play_locks: dict[int, asyncio.Lock] = {}
        self._domain_locks: dict[tuple[int, str], asyncio.Lock] = {}
        self._idle_tasks: dict[int, asyncio.Task[None]] = {}
        self._loaded_settings: set[int] = set()
        self._health_task: asyncio.Task[None] | None = None
        self._query_history: dict[int, deque[str]] = defaultdict(lambda: deque(maxlen=40))
        self._autocomplete_rank_cache: dict[tuple[int, str, int], tuple[float, list[str]]] = {}
        self._search_cache: OrderedDict[tuple[int, int, str, int], tuple[float, float, list[Track]]] = OrderedDict()
        self._search_refreshing: set[tuple[int, int, str, int]] = set()
        self._search_prewarm_tasks: dict[int, asyncio.Task[None]] = {}
        self._lyrics_cache: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._autoplay_recent_keys: dict[int, deque[str]] = defaultdict(deque)
        self._autoplay_recent_titles: dict[int, deque[str]] = defaultdict(deque)
        self._cooldowns: dict[tuple[int, str], float] = {}
        self._interaction_button_cooldowns: dict[tuple[int, int, str], float] = {}
        self._rate_user: dict[tuple[int, str], deque[float]] = defaultdict(deque)
        self._rate_guild: dict[tuple[int, str], deque[float]] = defaultdict(deque)
        self._rate_channel: dict[tuple[int, str], deque[float]] = defaultdict(deque)
        self._metrics: dict[str, int] = defaultdict(int)
        self._command_latency_ms: dict[str, float] = defaultdict(float)
        self._command_latency_count: dict[str, int] = defaultdict(int)
        self._command_metrics_window = CommandMetricsWindow()
        self._votes: dict[tuple[int, str], VoteState] = {}
        self._prefetch_tasks: dict[int, asyncio.Task[None]] = {}
        self._playlist_import_tasks: dict[int, asyncio.Task[None]] = {}
        self.nowplaying = NowPlayingController(loop=self.bot.loop)
        self.player_state = PlayerStateMachine()
        self.feature_flags = FeatureFlags.from_env()
        self.command_service = CommandService()
        self.playlist_jobs = PlaylistJobQueue()
        self._last_text_channel_id: dict[int, int] = {}
        self._web_runner: web.AppRunner | None = None
        self._web_site: web.TCPSite | None = None
        self._health_runner_http: web.AppRunner | None = None
        self._health_site_http: web.TCPSite | None = None
        self._retention_task: asyncio.Task[None] | None = None
        self._startup_warmup_task: asyncio.Task[None] | None = None
        self._startup_warmup_done: bool = False
        self._control_room_restore_task: asyncio.Task[None] | None = None
        self._control_room_restore_done: bool = False
        self._store_init_retry_attempts = max(int(os.getenv("STORE_INIT_RETRY_ATTEMPTS", "20").strip() or "20"), 1)
        self._store_init_retry_delay_seconds = max(
            float(os.getenv("STORE_INIT_RETRY_DELAY_SECONDS", "3").strip() or "3"),
            1.0,
        )
        self._critical_worker_restart_delay_seconds = max(
            float(os.getenv("CRITICAL_WORKER_RESTART_DELAY_SECONDS", "5").strip() or "5"),
            1.0,
        )
        self._last_health_alert_at: dict[str, float] = {}
        self._latency_total_ms: float = 0.0
        self._latency_count: int = 0
        self._boot_started_mono: float = time.monotonic()
        self._health_ticks: int = 0
        self._guild_policy: dict[int, GuildPolicy] = {}
        self._search_cache_write_tasks: set[asyncio.Task[None]] = set()
        self._query_usage_write_tasks: set[asyncio.Task[None]] = set()
        self._pending_queue_events: list[tuple[int, str, str]] = []
        self._pending_query_usage: dict[int, list[str]] = {}
        self._queue_event_flush_task: asyncio.Task[None] | None = None
        self._query_usage_flush_task: asyncio.Task[None] | None = None
        self._queue_event_flush_lock = asyncio.Lock()
        self._query_usage_flush_lock = asyncio.Lock()
        self._voice_reconnect_required: set[int] = set()
        self._voice_became_idle_at: dict[int, float] = {}
        self._voice_refresh_in_progress: set[int] = set()
        self._playback_watchdog_tasks: dict[int, asyncio.Task[None]] = {}
        self._playback_error_retries: dict[tuple[int, str], int] = {}
        self._control_room_state_cache: dict[int, tuple[int, int]] = {}
        self._control_room_operator: dict[int, int] = {}
        self._control_room_action_locks: dict[int, asyncio.Lock] = {}
        self._control_room_status_tasks: dict[int, asyncio.Task[None]] = {}
        self._control_room_history: dict[int, deque[str]] = defaultdict(lambda: deque(maxlen=12))
        self._control_room_preset_cursor: dict[int, int] = {}
        self._voice_mini_panel_state: dict[int, tuple[int, int]] = {}
        self.idle_disconnect_seconds = int(getattr(bot, "idle_disconnect_seconds", 300))
        self.voice_idle_reconnect_seconds = int(os.getenv("VOICE_IDLE_RECONNECT_SECONDS", "30").strip() or "30")
        self.max_queue_size = int(getattr(bot, "max_queue_size", 50))
        self.max_user_queue_items = int(getattr(bot, "max_user_queue_items", 0))
        self.max_playlist_import = int(getattr(bot, "max_playlist_import", 100))
        self.restore_queue_on_startup = os.getenv("QUEUE_RESTORE_ON_STARTUP", "true").strip().casefold() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.play_cooldown_seconds = float(getattr(bot, "play_cooldown_seconds", 3.0))
        self.default_max_track_duration_seconds = int(getattr(bot, "max_track_duration_seconds", 0))
        self.default_domain_whitelist = {item.casefold() for item in getattr(bot, "domain_whitelist", tuple()) if item}
        self.default_domain_blacklist = {item.casefold() for item in getattr(bot, "domain_blacklist", tuple()) if item}
        self.web_panel_enabled = bool(getattr(bot, "web_panel_enabled", False))
        self.web_panel_host = str(getattr(bot, "web_panel_host", "127.0.0.1"))
        self.web_panel_port = int(getattr(bot, "web_panel_port", 8080))
        self.admin_slash_enabled = bool(getattr(bot, "admin_slash_enabled", False))
        self.web_panel_oauth_client_id = str(getattr(bot, "web_panel_oauth_client_id", "")).strip()
        self.web_panel_oauth_client_secret = str(getattr(bot, "web_panel_oauth_client_secret", "")).strip()
        self.web_panel_oauth_redirect_uri = str(getattr(bot, "web_panel_oauth_redirect_uri", "")).strip()
        self.web_panel_session_secret = str(getattr(bot, "web_panel_session_secret", "")).strip()
        self.web_panel_admin_user_ids = {int(v) for v in getattr(bot, "web_panel_admin_user_ids", tuple()) if int(v) > 0}
        self.web_panel_dj_user_ids = {int(v) for v in getattr(bot, "web_panel_dj_user_ids", tuple()) if int(v) > 0}
        self.play_user_window_seconds = float(getattr(bot, "play_user_window_seconds", 10.0))
        self.play_user_max_requests = int(getattr(bot, "play_user_max_requests", 4))
        self.play_guild_window_seconds = float(getattr(bot, "play_guild_window_seconds", 10.0))
        self.play_guild_max_requests = int(getattr(bot, "play_guild_max_requests", 10))
        self.search_user_window_seconds = float(getattr(bot, "search_user_window_seconds", self.play_user_window_seconds))
        self.search_user_max_requests = int(getattr(bot, "search_user_max_requests", self.play_user_max_requests))
        self.search_guild_window_seconds = float(getattr(bot, "search_guild_window_seconds", self.play_guild_window_seconds))
        self.search_guild_max_requests = int(getattr(bot, "search_guild_max_requests", self.play_guild_max_requests))
        self.playlist_load_user_window_seconds = float(
            getattr(bot, "playlist_load_user_window_seconds", self.play_user_window_seconds)
        )
        self.playlist_load_user_max_requests = int(getattr(bot, "playlist_load_user_max_requests", self.play_user_max_requests))
        self.playlist_load_guild_window_seconds = float(
            getattr(bot, "playlist_load_guild_window_seconds", self.play_guild_window_seconds)
        )
        self.playlist_load_guild_max_requests = int(
            getattr(bot, "playlist_load_guild_max_requests", self.play_guild_max_requests)
        )
        self.spotify_strict_match = bool(getattr(bot, "spotify_strict_match", True))
        self.spotify_match_threshold = float(getattr(bot, "spotify_match_threshold", 0.55))
        self.search_results_limit = int(getattr(bot, "search_results_limit", 3))
        self.spotify_candidate_limit = int(getattr(bot, "spotify_candidate_limit", 3))
        self.music_fast_mode = bool(getattr(bot, "music_fast_mode", True))
        self.playlist_incremental_enabled = bool(getattr(bot, "playlist_incremental_enabled", True))
        self.playlist_initial_enqueue = int(getattr(bot, "playlist_initial_enqueue", 10))
        self.playlist_incremental_chunk_size = int(getattr(bot, "playlist_incremental_chunk_size", 20))
        self.playlist_incremental_chunk_delay_seconds = float(getattr(bot, "playlist_incremental_chunk_delay_seconds", 0.15))
        self.playlist_lazy_resolve_start_delay_seconds = float(
            os.getenv("PLAYLIST_LAZY_RESOLVE_START_DELAY_SECONDS", "4.0").strip() or "4.0"
        )
        self.playlist_chunk_retry_attempts = 3
        self.playlist_chunk_retry_base_delay_seconds = 0.45
        self.search_cache_ttl_seconds = float(getattr(bot, "search_cache_ttl_seconds", 30.0))
        self.search_cache_max_entries = int(getattr(bot, "search_cache_max_entries", 256))
        self.search_cache_stale_ttl_seconds = float(getattr(bot, "search_cache_stale_ttl_seconds", 300.0))
        self.search_timeout_seconds = float(getattr(bot, "search_timeout_seconds", 4.0))
        self.search_prewarm_enabled = bool(getattr(bot, "search_prewarm_enabled", True))
        self.search_prewarm_query_count = int(getattr(bot, "search_prewarm_query_count", 2))
        self.search_autocomplete_limit = int(getattr(bot, "search_autocomplete_limit", 8))
        self.autocomplete_rank_cache_ttl_seconds = float(
            os.getenv("AUTOCOMPLETE_RANK_CACHE_TTL_SECONDS", "45").strip() or "45"
        )
        self.search_startup_warmup_queries = int(
            os.getenv("SEARCH_STARTUP_WARMUP_QUERIES", "0").strip() or "0"
        )
        self.state_snapshot_interval_ticks = int(
            os.getenv("STATE_SNAPSHOT_INTERVAL_TICKS", "6").strip() or "6"
        )
        self.nowplaying_button_cooldown_seconds = float(
            os.getenv("NOWPLAYING_BUTTON_COOLDOWN_SECONDS", "1.25").strip() or "1.25"
        )
        self.health_alert_cooldown_seconds = float(
            os.getenv("HEALTH_ALERT_COOLDOWN_SECONDS", "180").strip() or "180"
        )
        self.health_alert_latency_ms_threshold = float(
            os.getenv("HEALTH_ALERT_LATENCY_MS_THRESHOLD", "2500").strip() or "2500"
        )
        self.health_alert_channel_id = int((os.getenv("HEALTH_ALERT_CHANNEL_ID", "0").strip() or "0"))
        self.web_panel_admin_token = os.getenv("WEB_PANEL_ADMIN_TOKEN", "").strip()
        self.profiler_sample_ratio = float(os.getenv("PROFILER_SAMPLE_RATIO", "0.03").strip() or "0.03")
        self.adaptive_search_enabled = os.getenv("ADAPTIVE_SEARCH_ENABLED", "true").strip().casefold() in {"1", "true", "yes", "on"}
        self.adaptive_search_latency_ms = float(os.getenv("ADAPTIVE_SEARCH_LATENCY_MS", "2000").strip() or "2000")
        self.adaptive_search_min_limit = int(os.getenv("ADAPTIVE_SEARCH_MIN_LIMIT", "2").strip() or "2")
        self.playlist_batch_ack_threshold = int(os.getenv("PLAYLIST_BATCH_ACK_THRESHOLD", "80").strip() or "80")
        LOGGER.info(
            "playlist_limits max_import=%s initial_enqueue=%s chunk_size=%s batch_ack_threshold=%s incremental=%s",
            self.max_playlist_import,
            self.playlist_initial_enqueue,
            self.playlist_incremental_chunk_size,
            self.playlist_batch_ack_threshold,
            self.playlist_incremental_enabled,
        )
        self._button_debounce_until: dict[tuple[int, str], float] = {}
        self.rate_limit_channel_window_seconds = float(os.getenv("PLAY_CHANNEL_WINDOW_SECONDS", "10").strip() or "10")
        self.rate_limit_channel_max_requests = int(os.getenv("PLAY_CHANNEL_MAX_REQUESTS", "8").strip() or "8")
        self.retention_daily_seconds = float(os.getenv("RETENTION_DAILY_SECONDS", "86400").strip() or "86400")
        self.retention_queue_events_max_rows = int(os.getenv("RETENTION_QUEUE_EVENTS_MAX_ROWS", "2000").strip() or "2000")
        self.retention_search_cache_max_age_seconds = int(os.getenv("RETENTION_SEARCH_CACHE_MAX_AGE_SECONDS", "7200").strip() or "7200")
        self.smart_prefetch_count = int(os.getenv("SMART_PREFETCH_COUNT", "2").strip() or "2")
        if self.autocomplete_rank_cache_ttl_seconds < 0:
            self.autocomplete_rank_cache_ttl_seconds = 0.0
        if self.search_startup_warmup_queries < 0:
            self.search_startup_warmup_queries = 0
        if self.state_snapshot_interval_ticks < 0:
            self.state_snapshot_interval_ticks = 0
        if self.nowplaying_button_cooldown_seconds < 0:
            self.nowplaying_button_cooldown_seconds = 0.0
        if self.health_alert_cooldown_seconds < 10:
            self.health_alert_cooldown_seconds = 10.0
        if self.health_alert_latency_ms_threshold < 100:
            self.health_alert_latency_ms_threshold = 100.0
        if self.rate_limit_channel_window_seconds < 0:
            self.rate_limit_channel_window_seconds = 0.0
        if self.rate_limit_channel_max_requests < 1:
            self.rate_limit_channel_max_requests = 1
        if self.retention_daily_seconds < 60:
            self.retention_daily_seconds = 60.0
        if self.retention_queue_events_max_rows < 100:
            self.retention_queue_events_max_rows = 100
        if self.retention_search_cache_max_age_seconds < 300:
            self.retention_search_cache_max_age_seconds = 300
        if self.smart_prefetch_count < 1:
            self.smart_prefetch_count = 1
        if self.smart_prefetch_count > 4:
            self.smart_prefetch_count = 4
        self.public_message_delete_after_seconds = float(getattr(bot, "public_message_delete_after_seconds", 30.0))
        auto_delete_exempt_raw = os.getenv(
            "AUTO_DELETE_EXEMPT_COMMANDS",
            "help,metrics,diagnostics,diagnostico,settings,cache,queue_events",
        )
        self.auto_delete_exempt_commands = {
            item.strip().casefold()
            for item in auto_delete_exempt_raw.split(",")
            if item.strip()
        }
        self.spotify_meta_cache_ttl_seconds = float(getattr(bot, "spotify_meta_cache_ttl_seconds", 900.0))
        self.spotify_meta_cache_max_entries = int(getattr(bot, "spotify_meta_cache_max_entries", 256))
        self.autoplay_history_size = int(getattr(bot, "autoplay_history_size", 25))
        self.autoplay_search_limit = int(getattr(bot, "autoplay_search_limit", 6))
        self.autoplay_max_queries = int(getattr(bot, "autoplay_max_queries", 4))
        self.provider_failure_threshold = int(getattr(bot, "provider_failure_threshold", 5))
        self.provider_recovery_seconds = float(getattr(bot, "provider_recovery_seconds", 20.0))
        self.provider_half_open_max_calls = int(getattr(bot, "provider_half_open_max_calls", 1))
        self.lyrics_cache_ttl_seconds = 1800.0
        self.lyrics_cache_max_entries = 256
        self.nowplaying_auto_pin = os.getenv("NOWPLAYING_AUTO_PIN", "false").strip().casefold() in {"1", "true", "yes", "on"}
        self.nowplaying_repost_on_track_change = os.getenv("NOWPLAYING_REPOST_ON_TRACK_CHANGE", "true").strip().casefold() in {"1", "true", "yes", "on"}
        self.control_room_restrict_music_commands = os.getenv("CONTROL_ROOM_RESTRICT_MUSIC_COMMANDS", "false").strip().casefold() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.control_room_lock_operator_enabled = os.getenv("CONTROL_ROOM_LOCK_OPERATOR_ENABLED", "true").strip().casefold() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.control_room_status_interval_seconds = float(
            os.getenv("CONTROL_ROOM_STATUS_INTERVAL_SECONDS", "7").strip() or "7"
        )
        if self.control_room_status_interval_seconds < 2.0:
            self.control_room_status_interval_seconds = 2.0
        self.playback_watchdog_interval_seconds = float(
            os.getenv("PLAYBACK_WATCHDOG_INTERVAL_SECONDS", "4").strip() or "4"
        )
        if self.playback_watchdog_interval_seconds < 1.0:
            self.playback_watchdog_interval_seconds = 1.0
        self.playback_watchdog_stall_seconds = float(
            os.getenv("PLAYBACK_WATCHDOG_STALL_SECONDS", "8").strip() or "8"
        )
        if self.playback_watchdog_stall_seconds < 3.0:
            self.playback_watchdog_stall_seconds = 3.0
        self.audio_backend = "native_ffmpeg"
        self.voice_connect_timeout_seconds = float(getattr(bot, "voice_connect_timeout_seconds", 8.0))
        self.bot_healthcheck_enabled = bool(getattr(bot, "bot_healthcheck_enabled", True))
        self.bot_healthcheck_host = str(getattr(bot, "bot_healthcheck_host", "0.0.0.0"))
        self.bot_healthcheck_port = int(getattr(bot, "bot_healthcheck_port", 8090))
        self.batch_write_interval_seconds = float(getattr(bot, "batch_write_interval_seconds", 0.35))
        self.batch_write_max_items = int(getattr(bot, "batch_write_max_items", 40))
        self.play_backpressure_threshold_ratio = float(getattr(bot, "play_backpressure_threshold_ratio", 0.75))
        self.play_backpressure_active_imports = int(getattr(bot, "play_backpressure_active_imports", 4))
        if self.batch_write_interval_seconds < 0.05:
            self.batch_write_interval_seconds = 0.05
        if self.batch_write_max_items < 5:
            self.batch_write_max_items = 5
        if self.play_backpressure_threshold_ratio < 0.1:
            self.play_backpressure_threshold_ratio = 0.1
        if self.play_backpressure_threshold_ratio > 0.99:
            self.play_backpressure_threshold_ratio = 0.99
        if self.play_backpressure_active_imports < 1:
            self.play_backpressure_active_imports = 1
        if self.voice_connect_timeout_seconds < 2.0:
            self.voice_connect_timeout_seconds = 2.0
        self._provider_breakers: dict[str, CircuitBreaker] = {
            "extract": CircuitBreaker(
                failure_threshold=max(self.provider_failure_threshold, 1),
                recovery_seconds=max(self.provider_recovery_seconds, 1.0),
                half_open_max_calls=max(self.provider_half_open_max_calls, 1),
            ),
            "search": CircuitBreaker(
                failure_threshold=max(self.provider_failure_threshold, 1),
                recovery_seconds=max(self.provider_recovery_seconds, 1.0),
                half_open_max_calls=max(self.provider_half_open_max_calls, 1),
            ),
        }
        self.search_pipeline = SearchPipeline(
            cache_timeout_seconds=float(os.getenv("SEARCH_PIPELINE_CACHE_TIMEOUT_SECONDS", "0.12").strip() or "0.12"),
            resolver_timeout_seconds=self.search_timeout_seconds if self.search_timeout_seconds > 0 else 4.0,
        )
        self.guild_settings_repo = GuildSettingsRepository(self.store)
        self.queue_repo = QueueRepository(self.store)
        self.playlist_repo = PlaylistRepository(self.store)
        self.favorites_repo = FavoritesRepository(self.store)
        self.scheduler = PlaybackScheduler()
        self.reconnect_policy = ReconnectPolicy(
            attempts=int(os.getenv("VOICE_RECONNECT_ATTEMPTS", "4").strip() or "4"),
            base_delay_seconds=float(os.getenv("VOICE_RECONNECT_BASE_DELAY_SECONDS", "0.35").strip() or "0.35"),
            max_delay_seconds=float(os.getenv("VOICE_RECONNECT_MAX_DELAY_SECONDS", "3.5").strip() or "3.5"),
            jitter_ratio=float(os.getenv("VOICE_RECONNECT_JITTER_RATIO", "0.25").strip() or "0.25"),
        )
        self._nowplaying_compact_mode_guilds: set[int] = set()
        self._dns_cache = DnsCache(
            ttl_seconds=float(os.getenv("DNS_CACHE_TTL_SECONDS", "300").strip() or "300"),
            max_entries=int(os.getenv("DNS_CACHE_MAX_ENTRIES", "128").strip() or "128"),
        )
        self._http_session: ClientSession | None = None

    async def _initialize_runtime_state(self) -> None:
        last_exc: Exception | None = None
        for attempt in range(1, self._store_init_retry_attempts + 1):
            try:
                await self.store.initialize()
                await self.store.cleanup_expired_votes(max_age_seconds=120, now_unix=int(time.time()))
                await self._restore_search_cache_from_store()
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt >= self._store_init_retry_attempts:
                    break
                LOGGER.exception(
                    "Falha inicializando armazenamento do bot (tentativa %s/%s). Nova tentativa em %.1fs.",
                    attempt,
                    self._store_init_retry_attempts,
                    self._store_init_retry_delay_seconds,
                )
                await asyncio.sleep(self._store_init_retry_delay_seconds)
        if last_exc is not None:
            raise last_exc

    def _start_supervised_task(
        self,
        *,
        attr_name: str,
        label: str,
        factory: Callable[[], Awaitable[None]],
        restart_on_completion: bool,
    ) -> asyncio.Task[None]:
        existing = getattr(self, attr_name, None)
        if isinstance(existing, asyncio.Task) and not existing.done():
            return existing

        async def runner() -> None:
            while True:
                try:
                    await factory()
                    if not restart_on_completion:
                        return
                    LOGGER.warning("Worker critico '%s' encerrou. Reiniciando em %.1fs.", label, self._critical_worker_restart_delay_seconds)
                except asyncio.CancelledError:
                    return
                except Exception:
                    LOGGER.exception(
                        "Worker critico '%s' falhou. Reiniciando em %.1fs.",
                        label,
                        self._critical_worker_restart_delay_seconds,
                    )
                await asyncio.sleep(self._critical_worker_restart_delay_seconds)

        task = self.bot.loop.create_task(runner())
        setattr(self, attr_name, task)
        return task

    async def _run_control_room_restore_worker(self) -> None:
        await self.bot.wait_until_ready()
        if self._control_room_restore_done:
            return
        await self._restore_control_room_panels()
        self._control_room_restore_done = True

    async def cog_load(self) -> None:
        await self._initialize_runtime_state()
        await self._schedule_startup_warmup()
        self._http_session = ClientSession(timeout=ClientTimeout(total=6))
        self._start_supervised_task(
            attr_name="_health_task",
            label="health_worker",
            factory=self._health_worker,
            restart_on_completion=True,
        )
        self._start_supervised_task(
            attr_name="_retention_task",
            label="retention_worker",
            factory=self._retention_worker,
            restart_on_completion=True,
        )
        if self.web_panel_enabled:
            await self._start_web_panel()
        if self.bot_healthcheck_enabled:
            try:
                await self._start_healthcheck_endpoint()
            except Exception:
                LOGGER.exception("Falha ao iniciar endpoint de healthcheck HTTP.")
        self._schedule_control_room_restore()

    def _schedule_control_room_restore(self) -> None:
        if self._control_room_restore_done:
            return
        self._start_supervised_task(
            attr_name="_control_room_restore_task",
            label="control_room_restore",
            factory=self._run_control_room_restore_worker,
            restart_on_completion=False,
        )

    def cog_unload(self) -> None:
        for guild_id in list(self._idle_tasks):
            self._cancel_idle_timer(guild_id)
        for guild_id in list(self._prefetch_tasks):
            self._cancel_prefetch(guild_id)
        for guild_id in list(self._playlist_import_tasks):
            self._cancel_playlist_import(guild_id)
        for guild_id, task in list(self._search_prewarm_tasks.items()):
            if not task.done():
                task.cancel()
            self._search_prewarm_tasks.pop(guild_id, None)
        for guild_id in list(self.nowplaying.tasks):
            self._cancel_nowplaying_updater(guild_id)
        for guild_id, task in list(self._control_room_status_tasks.items()):
            if not task.done():
                task.cancel()
            self._control_room_status_tasks.pop(guild_id, None)
        for guild_id, task in list(self._playback_watchdog_tasks.items()):
            if not task.done():
                task.cancel()
            self._playback_watchdog_tasks.pop(guild_id, None)
        if self._control_room_restore_task and not self._control_room_restore_task.done():
            self._control_room_restore_task.cancel()
            self._control_room_restore_task = None
        if self._startup_warmup_task and not self._startup_warmup_task.done():
            self._startup_warmup_task.cancel()
            self._startup_warmup_task = None
        if self._query_usage_flush_task and not self._query_usage_flush_task.done():
            self._query_usage_flush_task.cancel()
            self._query_usage_flush_task = None
        if self._queue_event_flush_task and not self._queue_event_flush_task.done():
            self._queue_event_flush_task.cancel()
            self._queue_event_flush_task = None
        if self._pending_query_usage:
            self.bot.loop.create_task(self._flush_query_usage_batch())
        if self._pending_queue_events:
            self.bot.loop.create_task(self._flush_queue_events_batch())
        for task in list(self._search_cache_write_tasks):
            if not task.done():
                task.cancel()
        self._search_cache_write_tasks.clear()
        for task in list(self._query_usage_write_tasks):
            if not task.done():
                task.cancel()
        self._query_usage_write_tasks.clear()
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
        if self._retention_task and not self._retention_task.done():
            self._retention_task.cancel()
            self._retention_task = None
        if self._http_session and not self._http_session.closed:
            self.bot.loop.create_task(self._http_session.close())
            self._http_session = None
        self.bot.loop.create_task(self.resolver.close())
        if self._web_runner:
            self.bot.loop.create_task(self._stop_web_panel())
        if self._health_runner_http:
            self.bot.loop.create_task(self._stop_healthcheck_endpoint())

    def _get_lock(self, guild_id: int) -> asyncio.Lock:
        lock = self._play_locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._play_locks[guild_id] = lock
        return lock

    def _get_domain_lock(self, guild_id: int, domain: str) -> asyncio.Lock:
        key = (guild_id, (domain or "general").strip().casefold())
        lock = self._domain_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._domain_locks[key] = lock
        return lock

    def _button_action_debounced(self, guild_id: int, action: str, *, window_seconds: float = 0.45) -> float:
        now = time.monotonic()
        key = (guild_id, action)
        until = self._button_debounce_until.get(key, 0.0)
        if now < until:
            return max(until - now, 0.0)
        self._button_debounce_until[key] = now + max(window_seconds, 0.05)
        return 0.0

    def _control_room_lock(self, guild_id: int) -> asyncio.Lock:
        lock = self._control_room_action_locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._control_room_action_locks[guild_id] = lock
        return lock

    def _control_room_push_history(self, guild_id: int, entry: str) -> None:
        text = (entry or "").strip()
        if not text:
            return
        self._control_room_history[guild_id].appendleft(text[:160])

    def _control_room_recent_history(self, guild_id: int, *, limit: int = 5) -> list[str]:
        entries = list(self._control_room_history.get(guild_id, deque()))
        return entries[: max(limit, 1)]

    def _control_room_channel_id(self, guild_id: int) -> int:
        state = self._control_room_state_cache.get(guild_id)
        if state is None:
            return 0
        return int(state[0])

    def _is_control_room_restricted(self, guild_id: int) -> bool:
        if not self.control_room_restrict_music_commands:
            return False
        return self._control_room_channel_id(guild_id) > 0

    def _effective_search_limit(self) -> int:
        base = max(self.search_results_limit, 1)
        if not self.adaptive_search_enabled:
            return base
        avg_5m = self._command_metrics_window.avg_ms("search", window_seconds=300)
        if avg_5m >= self.adaptive_search_latency_ms:
            return max(self.adaptive_search_min_limit, 1)
        return base

    def _build_help_embed(self, category: str) -> discord.Embed:
        return self.embeds.build_help_embed(category)

    def _prune_expired_caches(self) -> None:
        """Remove expired entries from unbounded in-memory dicts to prevent memory leaks."""
        now = time.monotonic()

        # Prune cooldowns (user command cooldowns).
        expired_cooldowns = [k for k, expires_at in self._cooldowns.items() if expires_at <= now]
        for k in expired_cooldowns:
            del self._cooldowns[k]

        # Prune button cooldowns.
        expired_btn = [k for k, expires_at in self._interaction_button_cooldowns.items() if expires_at <= now]
        for k in expired_btn:
            del self._interaction_button_cooldowns[k]

        # Prune button debounce.
        expired_debounce = [k for k, until in self._button_debounce_until.items() if until <= now]
        for k in expired_debounce:
            del self._button_debounce_until[k]

        # Prune autocomplete rank cache.
        expired_ac = [k for k, (expires_at, _) in self._autocomplete_rank_cache.items() if expires_at <= now]
        for k in expired_ac:
            del self._autocomplete_rank_cache[k]

        # Prune rate limit buckets that have been idle (all entries expired from window).
        for store in (self._rate_user, self._rate_guild, self._rate_channel):
            empty_keys = [k for k, bucket in store.items() if not bucket or (now - bucket[-1]) > 120]
            for k in empty_keys:
                del store[k]

        # Prune per-guild dicts for guilds the bot is no longer in.
        active_guild_ids = {g.id for g in self.bot.guilds}
        for guild_dict in (
            self._play_locks,
            self._idle_tasks,
            self._last_text_channel_id,
            self._control_room_operator,
            self._control_room_action_locks,
            self._control_room_preset_cursor,
            self._guild_policy,
            self._last_health_alert_at,
        ):
            stale = [gid for gid in guild_dict if isinstance(gid, int) and gid not in active_guild_ids]
            for gid in stale:
                guild_dict.pop(gid, None)

        # Prune domain locks for gone guilds.
        stale_domain = [k for k in self._domain_locks if isinstance(k, tuple) and k[0] not in active_guild_ids]
        for k in stale_domain:
            del self._domain_locks[k]

    @staticmethod
    def _ok(message: str) -> str:
        return f"✅ {message}"

    @staticmethod
    def _warn(message: str) -> str:
        return f"⚠️ {message}"

    @staticmethod
    def _error(message: str) -> str:
        return f"❌ {message}"

    @staticmethod
    def _note(message: str) -> str:
        return f"🎵 {message}"

    @staticmethod
    def _theme_color(name: str) -> discord.Color:
        return MusicEmbeds.theme_color(name)

    @staticmethod
    def _separator() -> str:
        return MusicEmbeds.separator()

    def _embed(self, title: str, description: str, *, color: discord.Color) -> discord.Embed:
        return self.embeds.embed(title, description, color=color)

    def _ok_embed(self, title: str, description: str) -> discord.Embed:
        return self.embeds.ok_embed(title, description)

    def _warn_embed(self, title: str, description: str) -> discord.Embed:
        return self.embeds.warn_embed(title, description)

    def _error_embed(self, title: str, description: str) -> discord.Embed:
        return self.embeds.error_embed(title, description)

    def _search_cache_titles(self, guild_id: int, current: str) -> list[str]:
        current_lower = current.casefold().strip()
        candidates: list[str] = []
        for key, payload in reversed(self._search_cache.items()):
            cache_guild_id, _user_id, _normalized_query, _limit = key
            if cache_guild_id != guild_id:
                continue
            _expires_at, _cached_at, tracks = payload
            for track in tracks:
                title = track.title.strip()
                if not title:
                    continue
                if current_lower and current_lower not in title.casefold():
                    continue
                candidates.append(title)
        return candidates

    async def _play_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        guild = interaction.guild
        if guild is None:
            return []
        try:
            history = list(self._query_history.get(guild.id, []))
            cache_titles = self._search_cache_titles(guild.id, current)
            # Autocomplete precisa responder em poucos ms para evitar conflitos de ACK.
            # Se ranking do banco atrasar, segue apenas com dados em memoria.
            try:
                ranked = await asyncio.wait_for(
                    self._popular_queries_cached(guild.id, current, max(self.search_autocomplete_limit, 1)),
                    timeout=0.12,
                )
            except Exception:
                ranked = []
            merged = merge_suggestions(
                query=current,
                history_values=ranked + list(reversed(history)),
                cache_values=cache_titles,
                limit=max(self.search_autocomplete_limit, 1),
            )
            return [app_commands.Choice(name=item[:100], value=item) for item in merged[:25]]
        except Exception:
            LOGGER.debug("Falha no autocomplete de /play", exc_info=True)
            return []

    async def _search_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await self._play_autocomplete(interaction, current)

    async def _filter_autocomplete(
        self,
        _interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        current_lower = current.casefold().strip()
        values = [name for name in FILTERS if not current_lower or current_lower in name.casefold()]
        return [app_commands.Choice(name=name, value=name) for name in values[:20]]

    async def _loop_autocomplete(
        self,
        _interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        modes = ["off", "track", "queue"]
        current_lower = current.casefold().strip()
        filtered = [mode for mode in modes if not current_lower or current_lower in mode.casefold()]
        return [app_commands.Choice(name=mode, value=mode) for mode in filtered]

    def _metrics_snapshot(self) -> MetricSnapshot:
        avg = (self._latency_total_ms / self._latency_count) if self._latency_count else 0.0
        return MetricSnapshot(
            command_calls=self._metrics.get("command_calls", 0),
            command_errors=self._metrics.get("command_errors", 0),
            extraction_failures=self._metrics.get("extraction_failures", 0),
            playback_failures=self._metrics.get("playback_failures", 0),
            average_latency_ms=avg,
        )

    def _avg_stage_latency_ms(self, stage: str) -> float:
        key = f"search_stage_{stage}"
        total = self._command_latency_ms.get(key, 0.0)
        count = self._command_latency_count.get(key, 0)
        if count <= 0:
            return 0.0
        return total / count

    def _record_command_stage_latency(self, command: str, stage: str, elapsed_ms: float) -> None:
        key = f"{command}_stage_{stage}"
        safe_ms = max(elapsed_ms, 0.0)
        self._command_latency_ms[key] += safe_ms
        self._command_latency_count[key] += 1
        self._command_metrics_window.add(key, safe_ms)

    def _play_backpressure_wait_seconds(self, *, query: str, to_front: bool) -> float:
        if to_front or not self._looks_like_playlist_query(query):
            return 0.0
        backlog, maxsize = self.music.extract_backlog_stats()
        ratio = (backlog / max(maxsize, 1)) if maxsize > 0 else 0.0
        active_imports = sum(1 for task in self._playlist_import_tasks.values() if not task.done())
        if ratio < self.play_backpressure_threshold_ratio and active_imports < self.play_backpressure_active_imports:
            return 0.0
        queue_over = max(ratio - self.play_backpressure_threshold_ratio, 0.0)
        imports_over = max(active_imports - self.play_backpressure_active_imports + 1, 0)
        return min(2.0 + (queue_over * 8.0) + (imports_over * 1.25), 20.0)

    def _cache_hit_rate(self, hits: int, misses: int) -> float:
        total = hits + misses
        if total <= 0:
            return 0.0
        return (hits / total) * 100.0

    def _cache_stats_summary(self) -> str:
        search_hits = int(self._metrics.get("search_cache_hit", 0))
        search_stale_hits = int(self._metrics.get("search_cache_stale_hit", 0))
        search_miss = int(self._metrics.get("search_cache_miss", 0))
        autocomplete_hits = int(self._metrics.get("autocomplete_cache_hit", 0))
        autocomplete_miss = int(self._metrics.get("autocomplete_cache_miss", 0))
        search_hit_rate = self._cache_hit_rate(search_hits + search_stale_hits, search_miss)
        autocomplete_hit_rate = self._cache_hit_rate(autocomplete_hits, autocomplete_miss)
        return (
            f"Search cache mem: `{len(self._search_cache)}` entradas\n"
            f"Autocomplete cache: `{len(self._autocomplete_rank_cache)}` entradas\n"
            f"Search hit/miss/stale: `{search_hits}/{search_miss}/{search_stale_hits}` "
            f"(`{search_hit_rate:.1f}%` hit)\n"
            f"Autocomplete hit/miss: `{autocomplete_hits}/{autocomplete_miss}` "
            f"(`{autocomplete_hit_rate:.1f}%` hit)"
        )

    @staticmethod
    def _extract_domain(value: str) -> str | None:
        raw = value.strip()
        if not raw or "://" not in raw:
            return None
        try:
            host = urlparse(raw).hostname
        except ValueError:
            return None
        if not host:
            return None
        return host.casefold()

    @staticmethod
    def _is_domain_allowed(domain: str | None, *, whitelist: set[str], blacklist: set[str]) -> bool:
        if domain is None:
            return not whitelist
        if blacklist and any(domain == blocked or domain.endswith(f".{blocked}") for blocked in blacklist):
            return False
        if not whitelist:
            return True
        return any(domain == allowed or domain.endswith(f".{allowed}") for allowed in whitelist)

    def _track_policy_error(self, guild_id: int, track: Track) -> str | None:
        policy = self._policy_for_guild(guild_id)
        domain = self._extract_domain(track.webpage_url) or self._extract_domain(track.source_query)
        if not self._is_domain_allowed(domain, whitelist=policy.domain_whitelist, blacklist=policy.domain_blacklist):
            allowed = ", ".join(sorted(policy.domain_whitelist)) if policy.domain_whitelist else "nao definido"
            blocked = ", ".join(sorted(policy.domain_blacklist)) if policy.domain_blacklist else "nenhum"
            return (
                f"Dominio bloqueado para reproducao: `{domain or 'desconhecido'}`\n"
                f"Whitelist: `{allowed}` | Blacklist: `{blocked}`"
            )
        if (
            policy.max_track_duration_seconds > 0
            and track.duration_seconds
            and track.duration_seconds > policy.max_track_duration_seconds
        ):
            return (
                f"Faixa excede o limite de duracao: "
                f"`{self._format_duration(track.duration_seconds)}` > "
                f"`{self._format_duration(policy.max_track_duration_seconds)}`"
            )
        return None

    def _cancel_prefetch(self, guild_id: int) -> None:
        task = self._prefetch_tasks.pop(guild_id, None)
        if task and not task.done():
            task.cancel()

    def _cancel_playlist_import(self, guild_id: int) -> None:
        task = self._playlist_import_tasks.pop(guild_id, None)
        if task and not task.done():
            task.cancel()

    @staticmethod
    def _looks_like_playlist_query(value: str) -> bool:
        raw = value.strip()
        if "://" not in raw:
            return False
        lowered = raw.casefold()
        return "list=" in lowered or "/playlist" in lowered

    @staticmethod
    def _playlist_has_pending_items(*, batch_total_items: int, extracted_count: int) -> bool:
        return batch_total_items > extracted_count

    async def _enqueue_tracks_incrementally(
        self,
        guild: discord.Guild,
        tracks: list[Track],
        text_channel: discord.abc.Messageable | None,
        *,
        job_id: str | None = None,
    ) -> tuple[int, int, int]:
        player = await self._get_player(guild.id)
        total_added = 0
        skipped_policy = 0
        skipped_capacity = 0
        skipped_chunk_failures = 0
        start = 0
        LOGGER.info(
            "playlist_incremental_begin guild=%s tracks=%s job_id=%s pending_before=%s",
            guild.id,
            len(tracks),
            job_id,
            len(player.snapshot_queue()),
        )
        while start < len(tracks):
            chunk_size = self._effective_playlist_chunk_size(player)
            chunk = tracks[start : start + chunk_size]
            added_chunk = 0
            chunk_done = False
            for attempt in range(max(self.playlist_chunk_retry_attempts, 1)):
                try:
                    lock = self._get_domain_lock(guild.id, "queue")
                    async with lock:
                        approved_tracks: list[Track] = []
                        chunk_user_counts: dict[str, int] = {}
                        for track in chunk:
                            if not self._has_queue_capacity(player):
                                skipped_capacity += 1
                                continue
                            if self.max_user_queue_items > 0:
                                requester_key = track.requested_by.strip().casefold()
                                pending = self._count_user_pending(player, track.requested_by)
                                pending += chunk_user_counts.get(requester_key, 0)
                                if (pending + 1) > self.max_user_queue_items:
                                    skipped_capacity += 1
                                    continue
                            if self._track_policy_error(guild.id, track):
                                skipped_policy += 1
                                continue
                            approved_tracks.append(track)
                            requester_key = track.requested_by.strip().casefold()
                            if requester_key:
                                chunk_user_counts[requester_key] = chunk_user_counts.get(requester_key, 0) + 1
                        if approved_tracks:
                            added_chunk = await self.queue_service.enqueue_many(player, approved_tracks)
                        if added_chunk > 0:
                            await self._persist_queue_state(guild.id, player)
                    chunk_done = True
                    break
                except Exception:
                    if attempt + 1 >= max(self.playlist_chunk_retry_attempts, 1):
                        skipped_chunk_failures += len(chunk)
                        LOGGER.debug(
                            "Chunk incremental falhou em definitivo (guild=%s start=%s size=%s)",
                            guild.id,
                            start,
                            len(chunk),
                            exc_info=True,
                        )
                        break
                    delay = min(self.playlist_chunk_retry_base_delay_seconds * (2 ** attempt), 3.0)
                    await asyncio.sleep(delay)
            if not chunk_done:
                continue
            total_added += added_chunk
            if job_id:
                self.playlist_jobs.update_progress(guild.id, job_id, added=added_chunk)
                job = self.playlist_jobs.get(guild.id, job_id)
                if job is not None:
                    LOGGER.info(
                        "playlist_incremental_chunk guild=%s job_id=%s start=%s chunk=%s added_chunk=%s total_added=%s job_added=%s pending_after=%s",
                        guild.id,
                        job.job_id,
                        start,
                        len(chunk),
                        added_chunk,
                        total_added,
                        job.added,
                        len(player.snapshot_queue()),
                    )
                    self._log_event(
                        "playlist_job_progress",
                        guild=guild.id,
                        job_id=job.job_id,
                        added=job.added,
                        skipped=job.skipped,
                        total=job.total,
                        status=job.status,
                    )
            start += chunk_size
            self._schedule_prefetch_next(guild.id, player)
            if self.playlist_incremental_chunk_delay_seconds > 0:
                await asyncio.sleep(self.playlist_incremental_chunk_delay_seconds)

        if text_channel:
            await self._send_channel(
                text_channel,
                self._note(
                    "Importacao incremental concluida: "
                    f"`{total_added}` adicionadas, `{skipped_policy}` por moderacao, "
                    f"`{skipped_capacity}` por limite, `{skipped_chunk_failures}` por falha de chunk."
                ),
            )
        if job_id:
            self.playlist_jobs.finish(guild.id, job_id, "completed")
            job = self.playlist_jobs.get(guild.id, job_id)
            LOGGER.info(
                "playlist_incremental_completed guild=%s job_id=%s total_added=%s job_added=%s skipped_policy=%s skipped_capacity=%s skipped_chunk_failures=%s",
                guild.id,
                job_id,
                total_added,
                job.added if job is not None else total_added,
                skipped_policy,
                skipped_capacity,
                skipped_chunk_failures,
            )
            self._log_event("playlist_job_completed", guild=guild.id, job_id=job_id, added=total_added)
        return total_added, skipped_policy, skipped_capacity + skipped_chunk_failures

    def _effective_playlist_chunk_size(self, player: GuildPlayer) -> int:
        base = max(self.playlist_incremental_chunk_size, 1)
        jobs_queue = getattr(self.music, "_extract_jobs", None)
        backlog = jobs_queue.qsize() if jobs_queue is not None else 0
        pending = len(player.snapshot_queue())
        if backlog >= 50 or pending >= 180:
            return max(base // 4, 1)
        if backlog >= 25 or pending >= 100:
            return max(base // 2, 1)
        return base

    def _schedule_incremental_enqueue(
        self,
        guild: discord.Guild,
        tracks: list[Track],
        text_channel: discord.abc.Messageable | None,
        *,
        job_id: str | None = None,
    ) -> None:
        self._cancel_playlist_import(guild.id)
        if not tracks:
            return
        if job_id:
            self.playlist_jobs.activate(guild.id, job_id)
            self._log_event("playlist_job_started", guild=guild.id, job_id=job_id, kind="incremental")

        async def worker() -> None:
            try:
                await self._enqueue_tracks_incrementally(guild, tracks, text_channel, job_id=job_id)
            except asyncio.CancelledError:
                if job_id:
                    self.playlist_jobs.finish(guild.id, job_id, "cancelled")
                return
            except Exception:
                LOGGER.exception("Falha em importacao incremental no guild %s", guild.id)
                if job_id:
                    self.playlist_jobs.finish(guild.id, job_id, "failed", error="incremental_worker_failed")
                    self._log_event("playlist_job_failed", guild=guild.id, job_id=job_id, error="incremental_worker_failed")
                if text_channel:
                    await self._send_channel(text_channel, self._error("A importacao incremental da playlist falhou."))
            finally:
                self._playlist_import_tasks.pop(guild.id, None)

        self._playlist_import_tasks[guild.id] = self.bot.loop.create_task(worker())

    def _schedule_lazy_playlist_resolve(
        self,
        guild: discord.Guild,
        query: str,
        requester: str,
        initial_tracks: list[Track],
        text_channel: discord.abc.Messageable | None,
        *,
        job_id: str | None = None,
    ) -> None:
        self._cancel_playlist_import(guild.id)
        initial_keys = {self._track_key(track) for track in initial_tracks}
        if job_id:
            self.playlist_jobs.activate(guild.id, job_id)
            self._log_event("playlist_job_started", guild=guild.id, job_id=job_id, kind="lazy_resolve")

        async def worker() -> None:
            try:
                if self.playlist_lazy_resolve_start_delay_seconds > 0:
                    await asyncio.sleep(self.playlist_lazy_resolve_start_delay_seconds)
                batch, _ = await self._extract_batch_with_spotify_fallback(
                    link=query,
                    requester=requester,
                    max_items=self.max_playlist_import,
                )
                candidates = batch.tracks[: self.max_playlist_import]
                remaining_tracks: list[Track] = []
                for track in candidates:
                    track.requested_by = requester
                    key = self._track_key(track)
                    if key in initial_keys:
                        continue
                    initial_keys.add(key)
                    remaining_tracks.append(track)
                if not remaining_tracks:
                    return
                await self._enqueue_tracks_incrementally(guild, remaining_tracks, text_channel, job_id=job_id)
            except asyncio.CancelledError:
                if job_id:
                    self.playlist_jobs.finish(guild.id, job_id, "cancelled")
                return
            except Exception:
                LOGGER.exception("Falha em resolucao lazy de playlist no guild %s", guild.id)
                if job_id:
                    self.playlist_jobs.finish(guild.id, job_id, "failed", error="lazy_resolve_failed")
                    self._log_event("playlist_job_failed", guild=guild.id, job_id=job_id, error="lazy_resolve_failed")
                if text_channel:
                    await self._send_channel(text_channel, self._error("Falha ao finalizar importacao lazy da playlist."))
            finally:
                self._playlist_import_tasks.pop(guild.id, None)

        self._playlist_import_tasks[guild.id] = self.bot.loop.create_task(worker())

    def _should_batch_ack_playlist(self, query: str, *, to_front: bool) -> bool:
        if to_front:
            return False
        if self.playlist_incremental_enabled:
            return False
        if not self.feature_flags.playlist_jobs_enabled:
            return False
        if not self._looks_like_playlist_query(query):
            return False
        return self.playlist_batch_ack_threshold > 0

    def _schedule_playlist_batch_ack_worker(
        self,
        *,
        guild: discord.Guild,
        query: str,
        requester: str,
        text_channel: discord.abc.Messageable | None,
        job_id: str,
    ) -> None:
        self._cancel_playlist_import(guild.id)

        async def worker() -> None:
            self.playlist_jobs.activate(guild.id, job_id)
            try:
                batch, _resolved_spotify = await self._extract_batch_with_spotify_fallback(
                    link=query,
                    requester=requester,
                    max_items=self.max_playlist_import,
                )
                self.playlist_jobs.update_progress(guild.id, job_id, total=batch.total_items)
                tracks = batch.tracks[: self.max_playlist_import]
                LOGGER.info(
                    "playlist_batch_ack_resolved guild=%s job_id=%s detected_total=%s extracted_tracks=%s capped_tracks=%s max_import=%s",
                    guild.id,
                    job_id,
                    batch.total_items,
                    len(batch.tracks),
                    len(tracks),
                    self.max_playlist_import,
                )
                for track in tracks:
                    track.requested_by = requester
                await self._enqueue_tracks_incrementally(guild, tracks, text_channel, job_id=job_id)
                await self._start_next_if_needed(guild, text_channel)
            except asyncio.CancelledError:
                self.playlist_jobs.finish(guild.id, job_id, "cancelled")
                return
            except Exception:
                self.playlist_jobs.finish(guild.id, job_id, "failed", error="batch_ack_worker_failed")
                LOGGER.exception("Falha no batch-ack worker guild=%s", guild.id)
                if text_channel:
                    await self._send_channel(text_channel, self._error("Falha ao processar playlist em background."))
            finally:
                self._playlist_import_tasks.pop(guild.id, None)

        self._playlist_import_tasks[guild.id] = self.bot.loop.create_task(worker())

    def _schedule_prefetch_next(self, guild_id: int, player: GuildPlayer) -> None:
        self._cancel_prefetch(guild_id)
        if player.restored_queue_pending_activation:
            return
        candidates = pick_prefetch_candidates(player, max_items=self.smart_prefetch_count)
        if not candidates:
            return
        jobs_queue = getattr(self.music, "_extract_jobs", None)
        backlog = jobs_queue.qsize() if jobs_queue is not None else 0
        if backlog >= 40:
            candidates = candidates[:1]

        async def worker() -> None:
            try:
                for track in candidates:
                    await self.music.prefetch_stream_url(track)
            except asyncio.CancelledError:
                return
            except Exception:
                LOGGER.debug("Prefetch falhou no guild %s", guild_id, exc_info=True)

        self._prefetch_tasks[guild_id] = self.bot.loop.create_task(worker())

    def _is_control_admin(self, interaction: discord.Interaction) -> bool:
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if member is None:
            return False
        return self._has_control_permissions(
            is_admin=member.guild_permissions.administrator,
            can_manage_channels=member.guild_permissions.manage_channels,
        )

    async def _voice_vote_required(self, interaction: discord.Interaction) -> tuple[discord.VoiceChannel | None, int]:
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if member is None or not member.voice or not isinstance(member.voice.channel, discord.VoiceChannel):
            return None, 0
        channel = member.voice.channel
        humans = [m for m in channel.members if not m.bot]
        required = max(1, (len(humans) // 2) + 1)
        return channel, required

    async def _try_vote_action(self, interaction: discord.Interaction, action: str) -> bool:
        guild = interaction.guild
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if guild is None or member is None:
            return False
        channel, required = await self._voice_vote_required(interaction)
        if channel is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Canal de voz", "Entre em um canal de voz para votar."),
                ephemeral=True,
            )
            return False

        key = (guild.id, action)
        state = self._votes.get(key)
        now = time.time()
        if state is None:
            saved = await self.store.get_vote_state(guild.id, action)
            if saved and (now - saved.created_at_unix) <= 120:
                state = VoteState(
                    channel_id=saved.channel_id,
                    required=saved.required_votes,
                    voters=SettingsStore.voters_from_csv(saved.voters_csv),
                    action=saved.action,
                    created_at=float(saved.created_at_unix),
                )
                self._votes[key] = state

        if state is None or state.channel_id != channel.id or (now - state.created_at) > 120:
            state = VoteState(channel_id=channel.id, required=required, voters=set(), action=action, created_at=now)
            self._votes[key] = state
            await self.store.upsert_vote_state(
                VoteStateRecord(
                    guild_id=guild.id,
                    action=action,
                    channel_id=channel.id,
                    required_votes=required,
                    voters_csv="",
                    created_at_unix=int(now),
                )
            )
        state.required = required
        if member.id in state.voters:
            await self._send_response(interaction, 
                embed=self._warn_embed("Voto ja registrado", "Voce ja votou nessa acao."),
                ephemeral=True,
            )
            return False

        state.voters.add(member.id)
        await self.store.upsert_vote_state(
            VoteStateRecord(
                guild_id=guild.id,
                action=action,
                channel_id=state.channel_id,
                required_votes=state.required,
                voters_csv=SettingsStore.voters_to_csv(state.voters),
                created_at_unix=int(state.created_at),
            )
        )
        votes = len(state.voters)
        if votes < state.required:
            await self._send_response(interaction, 
                embed=self._warn_embed(
                    "Votacao em andamento",
                    f"Acao: **{action}**\nVotos: `{votes}/{state.required}`\nPeca para outras pessoas usarem `/{action}`.",
                )
            )
            return False

        self._votes.pop(key, None)
        await self.store.delete_vote_state(guild.id, action)
        return True

    async def _start_healthcheck_endpoint(self) -> None:
        async def health(_request: web.Request) -> web.Response:
            payload = {
                "ok": True,
                "ready": self.bot.is_ready(),
                "guilds": len(self.bot.guilds),
                "audio_backend": self.audio_backend,
                "slo_5m": {
                    "play_p50_ms": self._command_metrics_window.percentile_ms("play", 50, window_seconds=300),
                    "play_p95_ms": self._command_metrics_window.percentile_ms("play", 95, window_seconds=300),
                    "play_p99_ms": self._command_metrics_window.percentile_ms("play", 99, window_seconds=300),
                    "search_p50_ms": self._command_metrics_window.percentile_ms("search", 50, window_seconds=300),
                    "search_p95_ms": self._command_metrics_window.percentile_ms("search", 95, window_seconds=300),
                    "search_p99_ms": self._command_metrics_window.percentile_ms("search", 99, window_seconds=300),
                },
            }
            return web.json_response(payload)

        app = web.Application()
        app.router.add_get("/health", health)
        self._health_runner_http = web.AppRunner(app)
        await self._health_runner_http.setup()
        self._health_site_http = web.TCPSite(self._health_runner_http, self.bot_healthcheck_host, self.bot_healthcheck_port)
        await self._health_site_http.start()
        LOGGER.info("Healthcheck HTTP ativo em http://%s:%s/health", self.bot_healthcheck_host, self.bot_healthcheck_port)

    async def _stop_healthcheck_endpoint(self) -> None:
        if self._health_site_http:
            await self._health_site_http.stop()
            self._health_site_http = None
        if self._health_runner_http:
            await self._health_runner_http.cleanup()
            self._health_runner_http = None

    async def _clear_votes_for_guild(self, guild_id: int) -> None:
        for action in ("skip", "stop"):
            self._votes.pop((guild_id, action), None)
            await self.store.delete_vote_state(guild_id, action)

    async def _enqueue_selected_track(self, interaction: discord.Interaction, track: Track) -> None:
        guild = interaction.guild
        if guild is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        voice_client = await self._ensure_voice(interaction)
        if voice_client is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Canal de voz", "Entre em um canal de voz para usar `/search`."),
                ephemeral=True,
            )
            return

        player = await self._get_player(guild.id)
        lock = self._get_domain_lock(guild.id, "playback")
        async with lock:
            await self._drop_restored_queue_if_idle(guild.id, player, reason="search_enqueue")
            if not self._has_queue_capacity(player):
                await self._send_response(interaction, 
                    embed=self._warn_embed(
                        "Fila lotada",
                        f"A fila atingiu o limite de `{self.max_queue_size}` musicas pendentes.",
                    ),
                    ephemeral=True,
                )
                return
            requester_name = interaction.user.display_name if interaction.user else track.requested_by
            if not self._is_user_queue_within_limit(player, requester_name, incoming_items=1):
                await self._send_response(
                    interaction,
                    embed=self._warn_embed(
                        "Limite por usuario",
                        f"Voce atingiu o limite de `{self.max_user_queue_items}` musica(s) pendentes na fila.",
                    ),
                    ephemeral=True,
                )
                return

            reason = self._track_policy_error(guild.id, track)
            if reason:
                await self._send_response(interaction, 
                    embed=self._warn_embed("Bloqueado pela moderacao", reason),
                    ephemeral=True,
                )
                return

            track.requested_by = requester_name
            await self.queue_service.enqueue(player, track)
            await self._persist_queue_state(guild.id, player)
        await self._record_queue_event(guild.id, "search_enqueue", title=track.title, requested_by=track.requested_by)
        self._schedule_prefetch_next(guild.id, player)
        self._record_query(guild.id, track.webpage_url)
        await self._send_response(interaction, 
            embed=self._ok_embed(
                "Resultado adicionado",
                f"**{track.title}** (`{self._format_duration(track.duration_seconds)}`)",
            ),
            ephemeral=True,
        )
        await self._start_next_if_needed(guild, interaction.channel)

    def _friendly_extraction_error(self, exc: Exception) -> tuple[str, str]:
        mapped = map_extraction_exception(exc)
        return mapped.title, f"{mapped.description}\n\n`codigo: {mapped.code}`"

    def _provider_available(self, operation: str) -> bool:
        breaker = self._provider_breakers.get(operation)
        if breaker is None:
            return True
        return breaker.allow_request()

    def _provider_success(self, operation: str) -> None:
        breaker = self._provider_breakers.get(operation)
        if breaker is not None:
            breaker.record_success()

    def _provider_failure(self, operation: str) -> None:
        breaker = self._provider_breakers.get(operation)
        if breaker is not None:
            breaker.record_failure()

    def _set_player_state(self, guild_id: int, state: PlayerState, *, reason: str = "") -> None:
        self.player_state.transition(guild_id, state, reason=reason)
        self.bot.loop.create_task(self.store.upsert_player_runtime_state(guild_id, state.value, int(time.time())))

    def _player_state_label(self, guild_id: int) -> str:
        return self.player_state.get(guild_id).state.value

    async def _toggle_nowplaying_compact(self, guild_id: int) -> bool:
        if guild_id in self._nowplaying_compact_mode_guilds:
            self._nowplaying_compact_mode_guilds.discard(guild_id)
            return False
        self._nowplaying_compact_mode_guilds.add(guild_id)
        return True

    async def _extract_batch_with_spotify_fallback(
        self,
        *,
        link: str,
        requester: str,
        max_items: int | None = None,
    ) -> tuple[TrackBatch, bool]:
        if not self._provider_available("extract"):
            raise RuntimeError("Extrator temporariamente indisponivel. Aguarde alguns segundos e tente novamente.")
        try:
            result = await self.resolver.extract_batch_with_spotify_fallback(
                link=link,
                requester=requester,
                max_items=max_items,
            )
        except Exception as exc:
            if should_count_provider_failure(exc):
                self._provider_failure("extract")
            raise
        self._provider_success("extract")
        return result

    async def _extract_track_with_spotify_fallback(self, *, link: str, requester: str) -> tuple[Track, bool]:
        if not self._provider_available("extract"):
            raise RuntimeError("Extrator temporariamente indisponivel. Aguarde alguns segundos e tente novamente.")
        try:
            result = await self.resolver.extract_track_with_spotify_fallback(link=link, requester=requester)
        except Exception as exc:
            if should_count_provider_failure(exc):
                self._provider_failure("extract")
            raise
        self._provider_success("extract")
        return result

    async def _search_tracks_guarded(
        self,
        query: str,
        *,
        requester: str,
        limit: int,
        guild_id: int = 0,
        user_id: int = 0,
    ) -> list[Track]:
        if not self._provider_available("search"):
            raise RuntimeError("Busca temporariamente indisponivel. Aguarde alguns segundos e tente novamente.")

        request = SearchPipelineRequest(
            query=query,
            requester=requester,
            limit=max(limit, 1),
            guild_id=max(guild_id, 0),
            user_id=max(user_id, 0),
        )

        async def cache_lookup(req: SearchPipelineRequest) -> tuple[list[Track] | None, bool]:
            if req.guild_id <= 0:
                return None, False
            normalized_query = self._normalize_search_query(req.query)
            user_key = (req.guild_id, req.user_id, normalized_query, req.limit)
            guild_key = (req.guild_id, 0, normalized_query, req.limit)
            tracks, stale = self._cache_get_search(user_key, allow_stale=True)
            if tracks is not None:
                return tracks, stale
            return self._cache_get_search(guild_key, allow_stale=True)

        async def resolver_lookup(req: SearchPipelineRequest) -> list[Track]:
            return await self.resolver.search_tracks(req.query, requester=req.requester, limit=req.limit)

        async def cache_store(req: SearchPipelineRequest, tracks: list[Track]) -> None:
            if req.guild_id <= 0:
                return
            normalized_query = self._normalize_search_query(req.query)
            self._cache_put_search((req.guild_id, req.user_id, normalized_query, req.limit), tracks)
            self._cache_put_search((req.guild_id, 0, normalized_query, req.limit), tracks)

        try:
            result = await self.search_pipeline.run(
                request,
                cache_lookup=cache_lookup if guild_id > 0 else None,
                resolver_lookup=resolver_lookup,
                cache_store=cache_store if guild_id > 0 else None,
            )
        except asyncio.TimeoutError:
            self._provider_failure("search")
            raise RuntimeError("Busca excedeu o tempo limite. Tente uma consulta mais curta.") from None
        except Exception:
            self._provider_failure("search")
            raise
        self._provider_success("search")
        self._metrics[f"search_source_{result.source}"] += 1
        self._record_command_stage_latency("search", "total", sum(result.stage_latency_ms.values()))
        for stage, elapsed_ms in result.stage_latency_ms.items():
            self._metrics[f"search_stage_{stage}_count"] += 1
            self._command_latency_ms[f"search_stage_{stage}"] += elapsed_ms
            self._command_latency_count[f"search_stage_{stage}"] += 1
            self._record_command_stage_latency("search", stage, elapsed_ms)
        self._maybe_profile(
            "search_pipeline",
            source=result.source,
            cache_ms=f"{result.stage_latency_ms.get('cache', 0.0):.1f}",
            resolver_ms=f"{result.stage_latency_ms.get('resolver', 0.0):.1f}",
            limit=request.limit,
            guild=request.guild_id or "n/a",
        )
        return result.tracks

    async def _require_control_permissions(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            await self._send_response(interaction, 
                embed=self._error_embed("Permissao", "Nao consegui validar suas permissoes."),
                ephemeral=True,
            )
            return False

        if self._has_control_permissions(
            is_admin=interaction.user.guild_permissions.administrator,
            can_manage_channels=interaction.user.guild_permissions.manage_channels,
        ):
            return True

        await self._send_response(interaction, 
            embed=self._warn_embed("Permissao necessaria", "Voce precisa de `Administrator` ou `Manage Channels`."),
            ephemeral=True,
        )
        return False

    async def _enforce_control_room_channel(self, interaction: discord.Interaction, *, command_name: str) -> bool:
        guild = interaction.guild
        if guild is None:
            return True
        if not self._is_control_room_restricted(guild.id):
            return True
        control_channel_id = self._control_room_channel_id(guild.id)
        if control_channel_id <= 0:
            return True
        channel_id = getattr(getattr(interaction, "channel", None), "id", 0)
        if int(channel_id) == int(control_channel_id):
            return True
        mention = f"<#{control_channel_id}>"
        await self._send_response(
            interaction,
            embed=self._warn_embed(
                "Canal restrito",
                f"O comando `/{command_name}` esta restrito ao canal de controle: {mention}.",
            ),
            ephemeral=True,
        )
        return False

    async def _require_same_voice_channel(self, interaction: discord.Interaction) -> bool:
        guild = interaction.guild
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if guild is None or member is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return False

        voice_client = guild.voice_client
        if not self._is_voice_connected(voice_client):
            await self._send_response(interaction, 
                embed=self._warn_embed("Sem conexao", "O bot nao esta conectado em canal de voz."),
                ephemeral=True,
            )
            return False

        if not member.voice or member.voice.channel is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Canal de voz", "Entre em um canal de voz para controlar o player."),
                ephemeral=True,
            )
            return False

        if member.voice.channel != voice_client.channel:
            await self._send_response(interaction, 
                embed=self._warn_embed(
                    "Canal diferente",
                    f"Voce precisa estar no canal **{voice_client.channel}** para controlar o player.",
                ),
                ephemeral=True,
            )
            return False

        return True



async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MusicCog(bot))
