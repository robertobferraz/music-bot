from __future__ import annotations

from botmusica.music.services.player_state import PlayerState, PlayerStateMachine


def test_player_state_machine_default_idle() -> None:
    sm = PlayerStateMachine()
    entry = sm.get(10)
    assert entry.state == PlayerState.IDLE


def test_player_state_machine_transition_and_clear() -> None:
    sm = PlayerStateMachine()
    sm.transition(99, PlayerState.CONNECTING, reason="join")
    sm.transition(99, PlayerState.PLAYING, reason="play")
    entry = sm.get(99)
    assert entry.state == PlayerState.PLAYING
    assert entry.reason == "play"
    sm.clear(99)
    assert sm.get(99).state == PlayerState.IDLE
