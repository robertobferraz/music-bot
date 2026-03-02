from __future__ import annotations

from botmusica.music.player import FILTERS, MusicService


def test_filter_dictionary_has_expected_modes() -> None:
    assert {"off", "bassboost", "nightcore", "vaporwave", "karaoke"}.issubset(set(FILTERS))


def test_ffmpeg_options_include_seek_and_filter() -> None:
    opts = MusicService._build_ffmpeg_options(audio_filter="nightcore", start_seconds=42)
    assert "-ss 42" in opts["before_options"]
    assert "-af" in opts["options"]
    assert "asetrate" in opts["options"]
    assert "-ac " not in opts["options"]
    assert "-ar " not in opts["options"]
