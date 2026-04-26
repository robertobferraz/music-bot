from __future__ import annotations

from botmusica.music.player import FILTERS, MusicService


def test_filter_dictionary_has_expected_modes() -> None:
    assert {"off", "bassboost", "nightcore", "vaporwave", "karaoke"}.issubset(set(FILTERS))


def test_youtube_player_clients_default_uses_supported_cookie_compatible_clients(monkeypatch) -> None:
    monkeypatch.delenv("YTDLP_YOUTUBE_CLIENTS", raising=False)

    clients = MusicService._youtube_player_clients_from_env()

    assert clients[:3] == ["tv_downgraded", "web_safari", "mweb"]
    assert "tv_embedded" not in clients
    assert "android_vr" not in clients


def test_youtube_player_clients_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("YTDLP_YOUTUBE_CLIENTS", "web_safari,web")

    assert MusicService._youtube_player_clients_from_env() == ["web_safari", "web"]


def test_ffmpeg_options_include_seek_and_filter() -> None:
    opts = MusicService._build_ffmpeg_options(audio_filter="nightcore", start_seconds=42)
    assert "-ss 42" in opts["before_options"]
    assert "-af" in opts["options"]
    assert "asetrate" in opts["options"]
    assert "-ac " not in opts["options"]
    assert "-ar " not in opts["options"]


def test_stream_from_payload_prefers_audio_only_over_web_muxed_format() -> None:
    stream_url, _headers = MusicService._stream_from_payload(
        {
            "formats": [
                {
                    "format_id": "18",
                    "url": "https://rr.googlevideo.com/videoplayback?c=WEB&mime=video%2Fmp4",
                    "acodec": "mp4a.40.2",
                    "vcodec": "avc1.42001E",
                    "ext": "mp4",
                    "abr": 96,
                    "asr": 44100,
                },
                {
                    "format_id": "251",
                    "url": "https://rr.googlevideo.com/videoplayback?c=ANDROID_VR&mime=audio%2Fwebm",
                    "acodec": "opus",
                    "vcodec": "none",
                    "ext": "webm",
                    "abr": 160,
                    "asr": 48000,
                },
            ]
        }
    )

    assert "mime=audio%2Fwebm" in stream_url


def test_stream_from_payload_rejects_muxed_direct_url() -> None:
    stream_url, _headers = MusicService._stream_from_payload(
        {
            "format_id": "18",
            "url": "https://rr.googlevideo.com/videoplayback?c=WEB&mime=video%2Fmp4",
            "acodec": "mp4a.40.2",
            "vcodec": "avc1.42001E",
            "ext": "mp4",
        }
    )

    assert stream_url is None


def test_stream_from_payload_rejects_formats_when_only_muxed_available() -> None:
    stream_url, _headers = MusicService._stream_from_payload(
        {
            "extractor": "youtube",
            "formats": [
                {
                    "format_id": "18",
                    "url": "https://rr.googlevideo.com/videoplayback?c=WEB&mime=video%2Fmp4",
                    "acodec": "mp4a.40.2",
                    "vcodec": "avc1.42001E",
                    "ext": "mp4",
                    "abr": 96,
                    "asr": 44100,
                }
            ],
        }
    )

    assert stream_url is None


def test_drop_stream_cache_also_drops_extract_cache() -> None:
    service = MusicService()
    query = "https://www.youtube.com/watch?v=abc"
    service._stream_url_cache[query] = (999999999.0, "https://example.com/stream", {})  # noqa: SLF001
    service._extract_cache[f"stream:{query}"] = (999999999.0, {"url": "https://example.com/stream"})  # noqa: SLF001

    service.drop_stream_cache(query)

    assert query not in service._stream_url_cache  # noqa: SLF001
    assert f"stream:{query}" not in service._extract_cache  # noqa: SLF001
