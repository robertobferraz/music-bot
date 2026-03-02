from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from botmusica.music.player import Track
else:
    Track = Any


class QueuePriority(StrEnum):
    NORMAL = "normal"
    HIGH = "high"
    AUTOPLAY = "autoplay"
    RECOVERY = "recovery"


@dataclass(slots=True)
class EnqueuePlan:
    immediate: list[Track]
    background: list[Track]
    to_front: bool
    incremental: bool
    priority: QueuePriority


class PlaybackScheduler:
    def plan_playlist_enqueue(
        self,
        *,
        tracks: list[Track],
        to_front: bool,
        priority: QueuePriority,
        incremental_enabled: bool,
        initial_enqueue: int,
    ) -> EnqueuePlan:
        if not tracks:
            return EnqueuePlan(immediate=[], background=[], to_front=to_front, incremental=False, priority=priority)

        # Requisicoes de alta prioridade tocam de forma deterministica: tudo entra no front.
        if to_front or priority in {QueuePriority.HIGH, QueuePriority.RECOVERY}:
            return EnqueuePlan(
                immediate=list(tracks),
                background=[],
                to_front=True,
                incremental=False,
                priority=priority,
            )

        if not incremental_enabled or len(tracks) <= max(initial_enqueue, 1):
            return EnqueuePlan(
                immediate=list(tracks),
                background=[],
                to_front=False,
                incremental=False,
                priority=priority,
            )

        split_idx = max(initial_enqueue, 1)
        return EnqueuePlan(
            immediate=list(tracks[:split_idx]),
            background=list(tracks[split_idx:]),
            to_front=False,
            incremental=True,
            priority=priority,
        )
