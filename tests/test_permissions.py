from __future__ import annotations

from botmusica.music.cog import MusicCog


def test_control_permission_logic() -> None:
    assert MusicCog._has_control_permissions(is_admin=True, can_manage_channels=False) is True
    assert MusicCog._has_control_permissions(is_admin=False, can_manage_channels=True) is True
    assert MusicCog._has_control_permissions(is_admin=False, can_manage_channels=False) is False
