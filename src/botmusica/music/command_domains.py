from __future__ import annotations

PLAYBACK_COMMANDS = {
    "play",
    "playnext",
    "search",
    "join",
    "skip",
    "pause",
    "resume",
    "stop",
    "clear",
    "queue",
    "nowplaying",
    "replay",
    "seek",
    "shuffle",
    "volume",
    "filter",
    "loop",
    "autoplay",
}

LIBRARY_COMMANDS = {
    "fav_add",
    "fav_list",
    "fav_play",
    "fav_remove",
    "playlist_save",
    "playlist_list",
    "playlist_load",
    "playlist_delete",
    "playlist_job",
    "playlist_job_cancel",
    "lyrics",
    "history",
}

QUEUE_COMMANDS = {"remove", "move", "jump", "queue_events"}

ADMIN_COMMANDS = {"metrics", "cache", "moderation", "diagnostics", "diagnostico", "help", "disconnect", "247", "settings"}


def command_domain(name: str) -> str:
    value = (name or "").strip().casefold()
    if value in PLAYBACK_COMMANDS:
        return "playback"
    if value in LIBRARY_COMMANDS:
        return "library"
    if value in QUEUE_COMMANDS:
        return "queue"
    if value in ADMIN_COMMANDS:
        return "admin"
    return "general"
