from botmusica.music.player import MusicService, Track


def test_audio_source_queries_prioritize_source_query_for_spotify_fallback() -> None:
    track = Track(
        source_query="ytsearch1:Musica A Artista A audio",
        title="Musica A",
        webpage_url="https://open.spotify.com/track/abc123",
        requested_by="tester",
        artist="Artista A",
    )

    queries = MusicService._audio_source_queries(track)

    assert queries[0].startswith("ytsearch1:")
    assert queries[1] == "https://open.spotify.com/track/abc123"


def test_provider_key_treats_ytmsearch_as_youtube() -> None:
    assert MusicService._provider_key_from_query("ytmsearch:musica teste") == "youtube"
