from __future__ import annotations

import os
from dataclasses import dataclass


def _truthy(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class FeatureFlags:
    playlist_jobs_enabled: bool
    play_progress_updates: bool
    extraction_backpressure_enabled: bool
    reconnect_strategy_enabled: bool
    command_service_enabled: bool
    nowplaying_compact_enabled: bool

    @classmethod
    def from_env(cls) -> "FeatureFlags":
        return cls(
            playlist_jobs_enabled=_truthy(os.getenv("FEATURE_PLAYLIST_JOBS_ENABLED", "true")),
            play_progress_updates=_truthy(os.getenv("FEATURE_PLAY_PROGRESS_UPDATES", "true")),
            extraction_backpressure_enabled=_truthy(os.getenv("FEATURE_EXTRACTION_BACKPRESSURE_ENABLED", "true")),
            reconnect_strategy_enabled=_truthy(os.getenv("FEATURE_RECONNECT_STRATEGY_ENABLED", "true")),
            command_service_enabled=_truthy(os.getenv("FEATURE_COMMAND_SERVICE_ENABLED", "true")),
            nowplaying_compact_enabled=_truthy(os.getenv("FEATURE_NOWPLAYING_COMPACT_ENABLED", "true")),
        )
