from __future__ import annotations

from botmusica.music.services.reconnection import ReconnectPolicy


def test_reconnect_policy_schedule_len_and_bounds() -> None:
    p = ReconnectPolicy(attempts=4, base_delay_seconds=0.2, max_delay_seconds=1.0, jitter_ratio=0.0)
    delays = p.backoff_schedule()
    assert len(delays) == 4
    assert delays[0] == 0.2
    assert delays[-1] <= 1.0
