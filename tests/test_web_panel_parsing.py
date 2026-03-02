from __future__ import annotations

import asyncio
from types import SimpleNamespace

from botmusica.music.cog import MusicCog


def _build_cog(loop: asyncio.AbstractEventLoop) -> MusicCog:
    bot = SimpleNamespace(loop=loop, user=None, guilds=[])
    return MusicCog(bot)


def test_panel_payload_int() -> None:
    loop = asyncio.new_event_loop()
    try:
        cog = _build_cog(loop)
        payload = {
            "ok": 12,
            "str_ok": "42",
            "negative": "-9",
            "bad": "x9",
            "boolv": True,
        }
        assert cog._panel_payload_int(payload, "ok") == 12
        assert cog._panel_payload_int(payload, "str_ok") == 42
        assert cog._panel_payload_int(payload, "negative") == -9
        assert cog._panel_payload_int(payload, "bad") is None
        assert cog._panel_payload_int(payload, "boolv", default=7) == 7
        assert cog._panel_payload_int(payload, "missing", default=3) == 3
    finally:
        loop.close()


def test_panel_payload_bool() -> None:
    loop = asyncio.new_event_loop()
    try:
        cog = _build_cog(loop)
        payload = {
            "true_bool": True,
            "false_bool": False,
            "true_str": "yes",
            "false_str": "off",
            "one": "1",
            "zero": "0",
        }
        assert cog._panel_payload_bool(payload, "true_bool") is True
        assert cog._panel_payload_bool(payload, "false_bool") is False
        assert cog._panel_payload_bool(payload, "true_str") is True
        assert cog._panel_payload_bool(payload, "false_str") is False
        assert cog._panel_payload_bool(payload, "one") is True
        assert cog._panel_payload_bool(payload, "zero") is False
        assert cog._panel_payload_bool(payload, "missing", default=True) is True
    finally:
        loop.close()
