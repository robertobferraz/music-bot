from __future__ import annotations

import asyncio

from botmusica.music.player import GuildPlayer, Track


def _track(name: str) -> Track:
    return Track(source_query=name, title=name, webpage_url=f"https://example.com/{name}", requested_by="tester")


def test_queue_operations() -> None:
    player = GuildPlayer(guild_id=1)
    asyncio.run(player.enqueue(_track("a")))
    asyncio.run(player.enqueue(_track("b")))
    asyncio.run(player.enqueue(_track("c")))

    moved = player.move_in_queue(3, 1)
    assert moved.title == "c"
    assert [item.title for item in player.snapshot_queue()] == ["c", "a", "b"]

    jumped = player.jump_to_front(3)
    assert jumped.title == "b"
    assert [item.title for item in player.snapshot_queue()] == ["b", "c", "a"]

    removed = player.remove_from_queue(2)
    assert removed.title == "c"
    assert [item.title for item in player.snapshot_queue()] == ["b", "a"]

    cleared = player.clear_queue()
    assert [item.title for item in cleared] == ["b", "a"]
    assert player.snapshot_queue() == []


def test_loop_autoplay_and_seek_flags_default() -> None:
    player = GuildPlayer(guild_id=2)
    assert player.loop_mode == "off"
    assert player.autoplay is False
    assert player.pending_seek_seconds == 0
    assert player.audio_filter == "off"
