from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum


class PlayerState(StrEnum):
    IDLE = "idle"
    CONNECTING = "connecting"
    BUFFERING = "buffering"
    PLAYING = "playing"
    PAUSED = "paused"
    RECOVERING = "recovering"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class PlayerStateEntry:
    state: PlayerState
    updated_at: float
    reason: str = ""


class PlayerStateMachine:
    def __init__(self) -> None:
        self._states: dict[int, PlayerStateEntry] = {}

    def get(self, guild_id: int) -> PlayerStateEntry:
        return self._states.get(guild_id) or PlayerStateEntry(state=PlayerState.IDLE, updated_at=time.monotonic())

    def transition(self, guild_id: int, new_state: PlayerState, *, reason: str = "") -> PlayerStateEntry:
        entry = PlayerStateEntry(state=new_state, updated_at=time.monotonic(), reason=reason[:180])
        self._states[guild_id] = entry
        return entry

    def clear(self, guild_id: int) -> None:
        self._states.pop(guild_id, None)

    def snapshot(self) -> dict[int, PlayerStateEntry]:
        return dict(self._states)
