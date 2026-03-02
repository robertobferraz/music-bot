from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("discord")

from botmusica.music.services.nowplaying_controller import NowPlayingController


def test_nowplaying_controller_cancel_and_forget() -> None:
    async def _run() -> None:
        loop = asyncio.get_running_loop()
        controller = NowPlayingController(loop=loop)

        async def sleeper() -> None:
            await asyncio.sleep(5)

        task = loop.create_task(sleeper())
        controller.tasks[1] = task
        controller.messages[1] = object()  # type: ignore[assignment]
        controller.track_keys[1] = "abc"

        controller.forget(1)
        await asyncio.sleep(0)
        assert 1 not in controller.tasks
        assert 1 not in controller.messages
        assert 1 not in controller.track_keys
        assert task.cancelled() or task.done()

    asyncio.run(_run())
