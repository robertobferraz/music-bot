from botmusica.music.player import MusicService, Track


def test_audio_source_queries_prioritize_source_query_for_spotify_fallback() -> None:
    track = Track(
        source_query="ytsearch5:Musica A Artista A audio",
        title="Musica A",
        webpage_url="https://open.spotify.com/track/abc123",
        requested_by="tester",
        artist="Artista A",
    )

    queries = MusicService._candidate_source_queries(track)

    assert queries[0].startswith("ytsearch5:")
    assert any(query == "ytsearch5:Artista A Musica A audio" for query in queries[1:])
    assert "https://open.spotify.com/track/abc123" not in queries


def test_provider_key_treats_ytmsearch_as_youtube() -> None:
    assert MusicService._provider_key_from_query("ytmsearch:musica teste") == "other"
