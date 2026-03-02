from __future__ import annotations

from botmusica.music.command_domains import command_domain


def test_command_domain_mapping() -> None:
    assert command_domain("play") == "playback"
    assert command_domain("playlist_load") == "library"
    assert command_domain("playlist_job") == "library"
    assert command_domain("remove") == "queue"
    assert command_domain("disconnect") == "admin"
    assert command_domain("cache") == "admin"
    assert command_domain("diagnostico") == "admin"
    assert command_domain("unknown_cmd") == "general"
