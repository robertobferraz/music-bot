from __future__ import annotations

from botmusica.music.player import GuildPlayer, Track


def pick_prefetch_candidates(player: GuildPlayer, *, max_items: int = 1) -> list[Track]:
    queued = player.snapshot_queue()
    if not queued or max_items <= 0:
        return []
    return queued[:max_items]
