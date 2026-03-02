from __future__ import annotations

from types import SimpleNamespace

from botmusica.music.services.command_metrics import CommandMetricsWindow
from botmusica.music.services.web_auth import validate_admin_token


def test_command_metrics_window_avg() -> None:
    window = CommandMetricsWindow()
    window.add("play", 100)
    window.add("play", 300)
    avg = window.avg_ms("play", window_seconds=60)
    assert 199 <= avg <= 201
    p50 = window.percentile_ms("play", 50, window_seconds=60)
    p95 = window.percentile_ms("play", 95, window_seconds=60)
    assert p50 >= 100
    assert p95 >= p50


def test_validate_admin_token() -> None:
    req = SimpleNamespace(
        headers={"X-Admin-Token": "secret"},
        query={},
    )
    assert validate_admin_token(req, "secret") is True
    req2 = SimpleNamespace(headers={}, query={"token": "secret"})
    assert validate_admin_token(req2, "secret") is True
    req3 = SimpleNamespace(headers={}, query={})
    assert validate_admin_token(req3, "secret") is False
