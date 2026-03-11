from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    repository_backend: str
    postgres_dsn: str
    discord_token: str
    test_guild_id: int | None
    idle_disconnect_seconds: int
    db_path: str
    max_queue_size: int
    max_user_queue_items: int
    max_playlist_import: int
    play_cooldown_seconds: float
    max_track_duration_seconds: int
    domain_whitelist: tuple[str, ...]
    domain_blacklist: tuple[str, ...]
    web_panel_enabled: bool
    web_panel_host: str
    web_panel_port: int
    admin_slash_enabled: bool
    web_panel_oauth_client_id: str
    web_panel_oauth_client_secret: str
    web_panel_oauth_redirect_uri: str
    web_panel_session_secret: str
    web_panel_admin_user_ids: tuple[int, ...]
    web_panel_dj_user_ids: tuple[int, ...]
    play_user_window_seconds: float
    play_user_max_requests: int
    play_guild_window_seconds: float
    play_guild_max_requests: int
    spotify_strict_match: bool
    spotify_match_threshold: float
    search_results_limit: int
    spotify_candidate_limit: int
    music_fast_mode: bool
    search_cache_ttl_seconds: float
    search_cache_max_entries: int
    search_cache_stale_ttl_seconds: float
    search_timeout_seconds: float
    search_prewarm_enabled: bool
    search_prewarm_query_count: int
    search_autocomplete_limit: int
    public_message_delete_after_seconds: float
    autoplay_history_size: int
    autoplay_search_limit: int
    autoplay_max_queries: int
    spotify_meta_cache_ttl_seconds: float
    spotify_meta_cache_max_entries: int
    playlist_incremental_enabled: bool
    playlist_initial_enqueue: int
    playlist_incremental_chunk_size: int
    playlist_incremental_chunk_delay_seconds: float
    provider_failure_threshold: int
    provider_recovery_seconds: float
    provider_half_open_max_calls: int
    search_user_window_seconds: float
    search_user_max_requests: int
    search_guild_window_seconds: float
    search_guild_max_requests: int
    playlist_load_user_window_seconds: float
    playlist_load_user_max_requests: int
    playlist_load_guild_window_seconds: float
    playlist_load_guild_max_requests: int
    lavalink_connect_attempts: int
    lavalink_connect_base_delay_seconds: float
    lavalink_voice_timeout_cooldown_seconds: float
    bot_healthcheck_enabled: bool
    bot_healthcheck_host: str
    bot_healthcheck_port: int
    batch_write_interval_seconds: float
    batch_write_max_items: int
    play_backpressure_threshold_ratio: float
    play_backpressure_active_imports: int


def load_settings() -> Settings:
    load_dotenv()

    repository_backend = os.getenv("BOT_REPOSITORY_BACKEND", "sqlite").strip().casefold() or "sqlite"
    postgres_dsn = os.getenv("POSTGRES_DSN", "").strip()

    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Defina DISCORD_TOKEN no ambiente ou no arquivo .env.")

    raw_guild = os.getenv("TEST_GUILD_ID", "").strip()
    test_guild_id = int(raw_guild) if raw_guild else None

    idle_raw = os.getenv("IDLE_DISCONNECT_SECONDS", "300").strip()
    idle_disconnect_seconds = int(idle_raw) if idle_raw else 300
    if idle_disconnect_seconds < 30:
        idle_disconnect_seconds = 30

    db_path = os.getenv("BOT_DB_PATH", "botmusica.db").strip() or "botmusica.db"
    max_queue_raw = os.getenv("MAX_QUEUE_SIZE", "50").strip()
    max_queue_size = int(max_queue_raw) if max_queue_raw else 50
    if max_queue_size < 1:
        max_queue_size = 1

    max_user_queue_raw = os.getenv("MAX_USER_QUEUE_ITEMS", "0").strip()
    max_user_queue_items = int(max_user_queue_raw) if max_user_queue_raw else 0
    if max_user_queue_items < 0:
        max_user_queue_items = 0

    max_playlist_import_raw = os.getenv("MAX_PLAYLIST_IMPORT", "100").strip()
    max_playlist_import = int(max_playlist_import_raw) if max_playlist_import_raw else 100
    if max_playlist_import < 1:
        max_playlist_import = 1

    cooldown_raw = os.getenv("PLAY_COOLDOWN_SECONDS", "3").strip()
    play_cooldown_seconds = float(cooldown_raw) if cooldown_raw else 3.0
    if play_cooldown_seconds < 0:
        play_cooldown_seconds = 0.0

    max_duration_raw = os.getenv("MAX_TRACK_DURATION_SECONDS", "0").strip()
    max_track_duration_seconds = int(max_duration_raw) if max_duration_raw else 0
    if max_track_duration_seconds < 0:
        max_track_duration_seconds = 0

    whitelist_raw = os.getenv("DOMAIN_WHITELIST", "").strip()
    domain_whitelist = tuple(
        item.strip().casefold()
        for item in whitelist_raw.split(",")
        if item.strip()
    )
    blacklist_raw = os.getenv("DOMAIN_BLACKLIST", "").strip()
    domain_blacklist = tuple(
        item.strip().casefold()
        for item in blacklist_raw.split(",")
        if item.strip()
    )

    web_panel_enabled = os.getenv("WEB_PANEL_ENABLED", "false").strip().casefold() in {"1", "true", "yes", "on"}
    web_panel_host = os.getenv("WEB_PANEL_HOST", "127.0.0.1").strip() or "127.0.0.1"
    web_panel_port_raw = os.getenv("WEB_PANEL_PORT", "8080").strip()
    web_panel_port = int(web_panel_port_raw) if web_panel_port_raw else 8080
    if web_panel_port < 1 or web_panel_port > 65535:
        web_panel_port = 8080
    admin_slash_enabled = os.getenv("ADMIN_SLASH_ENABLED", "true").strip().casefold() in {"1", "true", "yes", "on"}

    web_panel_oauth_client_id = os.getenv("WEB_PANEL_DISCORD_CLIENT_ID", "").strip()
    web_panel_oauth_client_secret = os.getenv("WEB_PANEL_DISCORD_CLIENT_SECRET", "").strip()
    web_panel_oauth_redirect_uri = os.getenv("WEB_PANEL_DISCORD_REDIRECT_URI", "").strip()
    web_panel_session_secret = os.getenv("WEB_PANEL_SESSION_SECRET", "").strip()

    def _parse_id_csv(name: str) -> tuple[int, ...]:
        raw = os.getenv(name, "").strip()
        if not raw:
            return tuple()
        parsed: list[int] = []
        for part in raw.split(","):
            cleaned = part.strip()
            if not cleaned:
                continue
            if cleaned.isdigit():
                parsed.append(int(cleaned))
        return tuple(sorted(set(parsed)))

    web_panel_admin_user_ids = _parse_id_csv("WEB_PANEL_ADMIN_USER_IDS")
    web_panel_dj_user_ids = _parse_id_csv("WEB_PANEL_DJ_USER_IDS")

    user_window_raw = os.getenv("PLAY_USER_WINDOW_SECONDS", "10").strip()
    play_user_window_seconds = float(user_window_raw) if user_window_raw else 10.0
    if play_user_window_seconds < 0:
        play_user_window_seconds = 0.0

    user_max_raw = os.getenv("PLAY_USER_MAX_REQUESTS", "4").strip()
    play_user_max_requests = int(user_max_raw) if user_max_raw else 4
    if play_user_max_requests < 1:
        play_user_max_requests = 1

    guild_window_raw = os.getenv("PLAY_GUILD_WINDOW_SECONDS", "10").strip()
    play_guild_window_seconds = float(guild_window_raw) if guild_window_raw else 10.0
    if play_guild_window_seconds < 0:
        play_guild_window_seconds = 0.0

    guild_max_raw = os.getenv("PLAY_GUILD_MAX_REQUESTS", "10").strip()
    play_guild_max_requests = int(guild_max_raw) if guild_max_raw else 10
    if play_guild_max_requests < 1:
        play_guild_max_requests = 1

    spotify_strict_match = os.getenv("SPOTIFY_STRICT_MATCH", "true").strip().casefold() in {"1", "true", "yes", "on"}
    spotify_match_threshold_raw = os.getenv("SPOTIFY_MATCH_THRESHOLD", "0.55").strip()
    spotify_match_threshold = float(spotify_match_threshold_raw) if spotify_match_threshold_raw else 0.55
    if spotify_match_threshold < 0:
        spotify_match_threshold = 0.0
    if spotify_match_threshold > 1:
        spotify_match_threshold = 1.0

    search_limit_raw = os.getenv("SEARCH_RESULTS_LIMIT", "3").strip()
    search_results_limit = int(search_limit_raw) if search_limit_raw else 3
    if search_results_limit < 1:
        search_results_limit = 1
    if search_results_limit > 10:
        search_results_limit = 10

    spotify_candidate_limit_raw = os.getenv("SPOTIFY_CANDIDATE_LIMIT", "3").strip()
    spotify_candidate_limit = int(spotify_candidate_limit_raw) if spotify_candidate_limit_raw else 3
    if spotify_candidate_limit < 1:
        spotify_candidate_limit = 1
    if spotify_candidate_limit > 10:
        spotify_candidate_limit = 10

    music_fast_mode = os.getenv("MUSIC_FAST_MODE", "true").strip().casefold() in {"1", "true", "yes", "on"}

    search_cache_ttl_raw = os.getenv("SEARCH_CACHE_TTL_SECONDS", "30").strip()
    search_cache_ttl_seconds = float(search_cache_ttl_raw) if search_cache_ttl_raw else 30.0
    if search_cache_ttl_seconds < 0:
        search_cache_ttl_seconds = 0.0

    search_cache_max_raw = os.getenv("SEARCH_CACHE_MAX_ENTRIES", "256").strip()
    search_cache_max_entries = int(search_cache_max_raw) if search_cache_max_raw else 256
    if search_cache_max_entries < 1:
        search_cache_max_entries = 1

    search_cache_stale_ttl_raw = os.getenv("SEARCH_CACHE_STALE_TTL_SECONDS", "300").strip()
    search_cache_stale_ttl_seconds = float(search_cache_stale_ttl_raw) if search_cache_stale_ttl_raw else 300.0
    if search_cache_stale_ttl_seconds < 0:
        search_cache_stale_ttl_seconds = 0.0
    if search_cache_stale_ttl_seconds > 3600:
        search_cache_stale_ttl_seconds = 3600.0

    search_timeout_raw = os.getenv("SEARCH_TIMEOUT_SECONDS", "4").strip()
    search_timeout_seconds = float(search_timeout_raw) if search_timeout_raw else 4.0
    if search_timeout_seconds < 1:
        search_timeout_seconds = 1.0
    if search_timeout_seconds > 30:
        search_timeout_seconds = 30.0

    search_prewarm_enabled = os.getenv("SEARCH_PREWARM_ENABLED", "true").strip().casefold() in {"1", "true", "yes", "on"}
    search_prewarm_count_raw = os.getenv("SEARCH_PREWARM_QUERY_COUNT", "2").strip()
    search_prewarm_query_count = int(search_prewarm_count_raw) if search_prewarm_count_raw else 2
    if search_prewarm_query_count < 1:
        search_prewarm_query_count = 1
    if search_prewarm_query_count > 5:
        search_prewarm_query_count = 5

    search_autocomplete_limit_raw = os.getenv("SEARCH_AUTOCOMPLETE_LIMIT", "8").strip()
    search_autocomplete_limit = int(search_autocomplete_limit_raw) if search_autocomplete_limit_raw else 8
    if search_autocomplete_limit < 1:
        search_autocomplete_limit = 1
    if search_autocomplete_limit > 25:
        search_autocomplete_limit = 25

    delete_after_raw = os.getenv("PUBLIC_MESSAGE_DELETE_AFTER_SECONDS", "60").strip()
    public_message_delete_after_seconds = float(delete_after_raw) if delete_after_raw else 60.0
    if public_message_delete_after_seconds < 0:
        public_message_delete_after_seconds = 0.0

    autoplay_history_raw = os.getenv("AUTOPLAY_HISTORY_SIZE", "25").strip()
    autoplay_history_size = int(autoplay_history_raw) if autoplay_history_raw else 25
    if autoplay_history_size < 5:
        autoplay_history_size = 5
    if autoplay_history_size > 200:
        autoplay_history_size = 200

    autoplay_search_limit_raw = os.getenv("AUTOPLAY_SEARCH_LIMIT", "6").strip()
    autoplay_search_limit = int(autoplay_search_limit_raw) if autoplay_search_limit_raw else 6
    if autoplay_search_limit < 1:
        autoplay_search_limit = 1
    if autoplay_search_limit > 15:
        autoplay_search_limit = 15

    autoplay_max_queries_raw = os.getenv("AUTOPLAY_MAX_QUERIES", "4").strip()
    autoplay_max_queries = int(autoplay_max_queries_raw) if autoplay_max_queries_raw else 4
    if autoplay_max_queries < 1:
        autoplay_max_queries = 1
    if autoplay_max_queries > 10:
        autoplay_max_queries = 10

    spotify_meta_ttl_raw = os.getenv("SPOTIFY_META_CACHE_TTL_SECONDS", "900").strip()
    spotify_meta_cache_ttl_seconds = float(spotify_meta_ttl_raw) if spotify_meta_ttl_raw else 900.0
    if spotify_meta_cache_ttl_seconds < 0:
        spotify_meta_cache_ttl_seconds = 0.0

    spotify_meta_max_raw = os.getenv("SPOTIFY_META_CACHE_MAX_ENTRIES", "256").strip()
    spotify_meta_cache_max_entries = int(spotify_meta_max_raw) if spotify_meta_max_raw else 256
    if spotify_meta_cache_max_entries < 1:
        spotify_meta_cache_max_entries = 1

    playlist_incremental_enabled = os.getenv("PLAYLIST_INCREMENTAL_ENABLED", "true").strip().casefold() in {"1", "true", "yes", "on"}
    playlist_initial_enqueue_raw = os.getenv("PLAYLIST_INITIAL_ENQUEUE", "10").strip()
    playlist_initial_enqueue = int(playlist_initial_enqueue_raw) if playlist_initial_enqueue_raw else 10
    if playlist_initial_enqueue < 1:
        playlist_initial_enqueue = 1
    if playlist_initial_enqueue > 100:
        playlist_initial_enqueue = 100

    playlist_chunk_size_raw = os.getenv("PLAYLIST_INCREMENTAL_CHUNK_SIZE", "20").strip()
    playlist_incremental_chunk_size = int(playlist_chunk_size_raw) if playlist_chunk_size_raw else 20
    if playlist_incremental_chunk_size < 1:
        playlist_incremental_chunk_size = 1
    if playlist_incremental_chunk_size > 200:
        playlist_incremental_chunk_size = 200

    playlist_chunk_delay_raw = os.getenv("PLAYLIST_INCREMENTAL_CHUNK_DELAY_SECONDS", "0.15").strip()
    playlist_incremental_chunk_delay_seconds = float(playlist_chunk_delay_raw) if playlist_chunk_delay_raw else 0.15
    if playlist_incremental_chunk_delay_seconds < 0:
        playlist_incremental_chunk_delay_seconds = 0.0
    if playlist_incremental_chunk_delay_seconds > 5:
        playlist_incremental_chunk_delay_seconds = 5.0

    provider_failure_threshold_raw = os.getenv("PROVIDER_FAILURE_THRESHOLD", "5").strip()
    provider_failure_threshold = int(provider_failure_threshold_raw) if provider_failure_threshold_raw else 5
    if provider_failure_threshold < 1:
        provider_failure_threshold = 1
    if provider_failure_threshold > 100:
        provider_failure_threshold = 100

    provider_recovery_seconds_raw = os.getenv("PROVIDER_RECOVERY_SECONDS", "20").strip()
    provider_recovery_seconds = float(provider_recovery_seconds_raw) if provider_recovery_seconds_raw else 20.0
    if provider_recovery_seconds < 1:
        provider_recovery_seconds = 1.0
    if provider_recovery_seconds > 600:
        provider_recovery_seconds = 600.0

    provider_half_open_max_calls_raw = os.getenv("PROVIDER_HALF_OPEN_MAX_CALLS", "1").strip()
    provider_half_open_max_calls = int(provider_half_open_max_calls_raw) if provider_half_open_max_calls_raw else 1
    if provider_half_open_max_calls < 1:
        provider_half_open_max_calls = 1
    if provider_half_open_max_calls > 20:
        provider_half_open_max_calls = 20

    search_user_window_raw = os.getenv("SEARCH_USER_WINDOW_SECONDS", str(play_user_window_seconds)).strip()
    search_user_window_seconds = float(search_user_window_raw) if search_user_window_raw else play_user_window_seconds
    if search_user_window_seconds < 0:
        search_user_window_seconds = 0.0

    search_user_max_raw = os.getenv("SEARCH_USER_MAX_REQUESTS", str(play_user_max_requests)).strip()
    search_user_max_requests = int(search_user_max_raw) if search_user_max_raw else play_user_max_requests
    if search_user_max_requests < 1:
        search_user_max_requests = 1

    search_guild_window_raw = os.getenv("SEARCH_GUILD_WINDOW_SECONDS", str(play_guild_window_seconds)).strip()
    search_guild_window_seconds = float(search_guild_window_raw) if search_guild_window_raw else play_guild_window_seconds
    if search_guild_window_seconds < 0:
        search_guild_window_seconds = 0.0

    search_guild_max_raw = os.getenv("SEARCH_GUILD_MAX_REQUESTS", str(play_guild_max_requests)).strip()
    search_guild_max_requests = int(search_guild_max_raw) if search_guild_max_raw else play_guild_max_requests
    if search_guild_max_requests < 1:
        search_guild_max_requests = 1

    playlist_load_user_window_raw = os.getenv("PLAYLIST_LOAD_USER_WINDOW_SECONDS", str(play_user_window_seconds)).strip()
    playlist_load_user_window_seconds = (
        float(playlist_load_user_window_raw) if playlist_load_user_window_raw else play_user_window_seconds
    )
    if playlist_load_user_window_seconds < 0:
        playlist_load_user_window_seconds = 0.0

    playlist_load_user_max_raw = os.getenv("PLAYLIST_LOAD_USER_MAX_REQUESTS", str(play_user_max_requests)).strip()
    playlist_load_user_max_requests = int(playlist_load_user_max_raw) if playlist_load_user_max_raw else play_user_max_requests
    if playlist_load_user_max_requests < 1:
        playlist_load_user_max_requests = 1

    playlist_load_guild_window_raw = os.getenv("PLAYLIST_LOAD_GUILD_WINDOW_SECONDS", str(play_guild_window_seconds)).strip()
    playlist_load_guild_window_seconds = (
        float(playlist_load_guild_window_raw) if playlist_load_guild_window_raw else play_guild_window_seconds
    )
    if playlist_load_guild_window_seconds < 0:
        playlist_load_guild_window_seconds = 0.0

    playlist_load_guild_max_raw = os.getenv("PLAYLIST_LOAD_GUILD_MAX_REQUESTS", str(play_guild_max_requests)).strip()
    playlist_load_guild_max_requests = (
        int(playlist_load_guild_max_raw) if playlist_load_guild_max_raw else play_guild_max_requests
    )
    if playlist_load_guild_max_requests < 1:
        playlist_load_guild_max_requests = 1

    lavalink_attempts_raw = os.getenv("LAVALINK_CONNECT_ATTEMPTS", "8").strip()
    lavalink_connect_attempts = int(lavalink_attempts_raw) if lavalink_attempts_raw else 8
    if lavalink_connect_attempts < 1:
        lavalink_connect_attempts = 1
    if lavalink_connect_attempts > 60:
        lavalink_connect_attempts = 60

    lavalink_base_delay_raw = os.getenv("LAVALINK_CONNECT_BASE_DELAY_SECONDS", "1.5").strip()
    lavalink_connect_base_delay_seconds = float(lavalink_base_delay_raw) if lavalink_base_delay_raw else 1.5
    if lavalink_connect_base_delay_seconds < 0.2:
        lavalink_connect_base_delay_seconds = 0.2
    if lavalink_connect_base_delay_seconds > 30:
        lavalink_connect_base_delay_seconds = 30.0

    lavalink_voice_timeout_cooldown_raw = os.getenv("LAVALINK_VOICE_TIMEOUT_COOLDOWN_SECONDS", "300").strip()
    lavalink_voice_timeout_cooldown_seconds = (
        float(lavalink_voice_timeout_cooldown_raw) if lavalink_voice_timeout_cooldown_raw else 300.0
    )
    if lavalink_voice_timeout_cooldown_seconds < 10:
        lavalink_voice_timeout_cooldown_seconds = 10.0
    if lavalink_voice_timeout_cooldown_seconds > 3600:
        lavalink_voice_timeout_cooldown_seconds = 3600.0

    bot_healthcheck_enabled = os.getenv("BOT_HEALTHCHECK_ENABLED", "true").strip().casefold() in {"1", "true", "yes", "on"}
    bot_healthcheck_host = os.getenv("BOT_HEALTHCHECK_HOST", "0.0.0.0").strip() or "0.0.0.0"
    bot_healthcheck_port_raw = os.getenv("BOT_HEALTHCHECK_PORT", "8090").strip()
    bot_healthcheck_port = int(bot_healthcheck_port_raw) if bot_healthcheck_port_raw else 8090
    if bot_healthcheck_port < 1 or bot_healthcheck_port > 65535:
        bot_healthcheck_port = 8090

    batch_write_interval_raw = os.getenv("BATCH_WRITE_INTERVAL_SECONDS", "0.35").strip()
    batch_write_interval_seconds = float(batch_write_interval_raw) if batch_write_interval_raw else 0.35
    if batch_write_interval_seconds < 0.05:
        batch_write_interval_seconds = 0.05
    if batch_write_interval_seconds > 3:
        batch_write_interval_seconds = 3.0

    batch_write_max_items_raw = os.getenv("BATCH_WRITE_MAX_ITEMS", "40").strip()
    batch_write_max_items = int(batch_write_max_items_raw) if batch_write_max_items_raw else 40
    if batch_write_max_items < 5:
        batch_write_max_items = 5
    if batch_write_max_items > 500:
        batch_write_max_items = 500

    play_backpressure_ratio_raw = os.getenv("PLAY_BACKPRESSURE_THRESHOLD_RATIO", "0.75").strip()
    play_backpressure_threshold_ratio = (
        float(play_backpressure_ratio_raw) if play_backpressure_ratio_raw else 0.75
    )
    if play_backpressure_threshold_ratio < 0.1:
        play_backpressure_threshold_ratio = 0.1
    if play_backpressure_threshold_ratio > 0.99:
        play_backpressure_threshold_ratio = 0.99

    play_backpressure_imports_raw = os.getenv("PLAY_BACKPRESSURE_ACTIVE_IMPORTS", "4").strip()
    play_backpressure_active_imports = int(play_backpressure_imports_raw) if play_backpressure_imports_raw else 4
    if play_backpressure_active_imports < 1:
        play_backpressure_active_imports = 1
    if play_backpressure_active_imports > 50:
        play_backpressure_active_imports = 50

    return Settings(
        repository_backend=repository_backend,
        postgres_dsn=postgres_dsn,
        discord_token=token,
        test_guild_id=test_guild_id,
        idle_disconnect_seconds=idle_disconnect_seconds,
        db_path=db_path,
        max_queue_size=max_queue_size,
        max_user_queue_items=max_user_queue_items,
        max_playlist_import=max_playlist_import,
        play_cooldown_seconds=play_cooldown_seconds,
        max_track_duration_seconds=max_track_duration_seconds,
        domain_whitelist=domain_whitelist,
        domain_blacklist=domain_blacklist,
        web_panel_enabled=web_panel_enabled,
        web_panel_host=web_panel_host,
        web_panel_port=web_panel_port,
        admin_slash_enabled=admin_slash_enabled,
        web_panel_oauth_client_id=web_panel_oauth_client_id,
        web_panel_oauth_client_secret=web_panel_oauth_client_secret,
        web_panel_oauth_redirect_uri=web_panel_oauth_redirect_uri,
        web_panel_session_secret=web_panel_session_secret,
        web_panel_admin_user_ids=web_panel_admin_user_ids,
        web_panel_dj_user_ids=web_panel_dj_user_ids,
        play_user_window_seconds=play_user_window_seconds,
        play_user_max_requests=play_user_max_requests,
        play_guild_window_seconds=play_guild_window_seconds,
        play_guild_max_requests=play_guild_max_requests,
        spotify_strict_match=spotify_strict_match,
        spotify_match_threshold=spotify_match_threshold,
        search_results_limit=search_results_limit,
        spotify_candidate_limit=spotify_candidate_limit,
        music_fast_mode=music_fast_mode,
        search_cache_ttl_seconds=search_cache_ttl_seconds,
        search_cache_max_entries=search_cache_max_entries,
        search_cache_stale_ttl_seconds=search_cache_stale_ttl_seconds,
        search_timeout_seconds=search_timeout_seconds,
        search_prewarm_enabled=search_prewarm_enabled,
        search_prewarm_query_count=search_prewarm_query_count,
        search_autocomplete_limit=search_autocomplete_limit,
        public_message_delete_after_seconds=public_message_delete_after_seconds,
        autoplay_history_size=autoplay_history_size,
        autoplay_search_limit=autoplay_search_limit,
        autoplay_max_queries=autoplay_max_queries,
        spotify_meta_cache_ttl_seconds=spotify_meta_cache_ttl_seconds,
        spotify_meta_cache_max_entries=spotify_meta_cache_max_entries,
        playlist_incremental_enabled=playlist_incremental_enabled,
        playlist_initial_enqueue=playlist_initial_enqueue,
        playlist_incremental_chunk_size=playlist_incremental_chunk_size,
        playlist_incremental_chunk_delay_seconds=playlist_incremental_chunk_delay_seconds,
        provider_failure_threshold=provider_failure_threshold,
        provider_recovery_seconds=provider_recovery_seconds,
        provider_half_open_max_calls=provider_half_open_max_calls,
        search_user_window_seconds=search_user_window_seconds,
        search_user_max_requests=search_user_max_requests,
        search_guild_window_seconds=search_guild_window_seconds,
        search_guild_max_requests=search_guild_max_requests,
        playlist_load_user_window_seconds=playlist_load_user_window_seconds,
        playlist_load_user_max_requests=playlist_load_user_max_requests,
        playlist_load_guild_window_seconds=playlist_load_guild_window_seconds,
        playlist_load_guild_max_requests=playlist_load_guild_max_requests,
        lavalink_connect_attempts=lavalink_connect_attempts,
        lavalink_connect_base_delay_seconds=lavalink_connect_base_delay_seconds,
        lavalink_voice_timeout_cooldown_seconds=lavalink_voice_timeout_cooldown_seconds,
        bot_healthcheck_enabled=bot_healthcheck_enabled,
        bot_healthcheck_host=bot_healthcheck_host,
        bot_healthcheck_port=bot_healthcheck_port,
        batch_write_interval_seconds=batch_write_interval_seconds,
        batch_write_max_items=batch_write_max_items,
        play_backpressure_threshold_ratio=play_backpressure_threshold_ratio,
        play_backpressure_active_imports=play_backpressure_active_imports,
    )
