from __future__ import annotations

from botmusica.music.services.feature_flags import FeatureFlags


def test_feature_flags_from_env_defaults(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    for key in (
        "FEATURE_PLAYLIST_JOBS_ENABLED",
        "FEATURE_PLAY_PROGRESS_UPDATES",
        "FEATURE_EXTRACTION_BACKPRESSURE_ENABLED",
        "FEATURE_RECONNECT_STRATEGY_ENABLED",
        "FEATURE_COMMAND_SERVICE_ENABLED",
        "FEATURE_NOWPLAYING_COMPACT_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    flags = FeatureFlags.from_env()
    assert flags.playlist_jobs_enabled is True
    assert flags.nowplaying_compact_enabled is True
