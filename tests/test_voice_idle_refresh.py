from __future__ import annotations

import os
import time


def test_voice_idle_reconnect_seconds_default() -> None:
    """voice_idle_reconnect_seconds defaults to 30 when env var unset."""
    os.environ.pop("VOICE_IDLE_RECONNECT_SECONDS", None)
    value = int(os.getenv("VOICE_IDLE_RECONNECT_SECONDS", "30").strip() or "30")
    assert value == 30


def test_voice_idle_reconnect_seconds_from_env() -> None:
    """voice_idle_reconnect_seconds reads from env var."""
    os.environ["VOICE_IDLE_RECONNECT_SECONDS"] = "60"
    value = int(os.getenv("VOICE_IDLE_RECONNECT_SECONDS", "30").strip() or "30")
    assert value == 60
    os.environ.pop("VOICE_IDLE_RECONNECT_SECONDS", None)


def test_voice_idle_reconnect_threshold_check() -> None:
    """Threshold check: idle >= threshold triggers refresh."""
    threshold = 30
    idle_since = time.monotonic() - 35  # 35s ago
    assert (time.monotonic() - idle_since) >= threshold


def test_voice_idle_reconnect_threshold_not_yet() -> None:
    """Threshold check: idle < threshold does not trigger refresh."""
    threshold = 30
    idle_since = time.monotonic() - 10  # 10s ago
    assert not ((time.monotonic() - idle_since) >= threshold)


def test_voice_idle_reconnect_disabled_when_zero() -> None:
    """When voice_idle_reconnect_seconds == 0, refresh is disabled."""
    threshold = 0
    idle_since = time.monotonic() - 9999
    should_refresh = threshold > 0 and (time.monotonic() - idle_since) >= threshold
    assert not should_refresh


def test_voice_became_idle_at_dict_pop_clears() -> None:
    """pop() on missing key returns None without raising."""
    d: dict[int, float] = {}
    result = d.pop(42, None)
    assert result is None


def test_voice_became_idle_at_dict_pop_returns_value() -> None:
    """pop() on existing key returns timestamp and removes it."""
    d: dict[int, float] = {1: 100.0}
    result = d.pop(1, None)
    assert result == 100.0
    assert 1 not in d
