from __future__ import annotations

import asyncio
from types import SimpleNamespace

from botmusica.music.services.repositories_split import (
    FavoritesRepository,
    GuildSettingsRepository,
    PlaylistRepository,
    QueueRepository,
)
from botmusica.music.storage import FavoriteTrack, GuildSettings, PlaylistTrack, QueueTrack


def test_split_repositories_delegate_to_store() -> None:
    calls: list[str] = []

    class FakeStore:
        async def get(self, guild_id: int) -> GuildSettings | None:
            calls.append(f"get:{guild_id}")
            return None

        async def upsert(self, guild_id: int, settings: GuildSettings) -> None:
            calls.append(f"upsert:{guild_id}:{settings.loop_mode}")

        async def save_queue_state(self, guild_id: int, tracks: list[QueueTrack]) -> None:
            calls.append(f"save_queue:{guild_id}:{len(tracks)}")

        async def load_queue_state(self, guild_id: int) -> list[QueueTrack]:
            calls.append(f"load_queue:{guild_id}")
            return []

        async def append_queue_event(self, guild_id: int, action: str, details_json: str) -> None:
            calls.append(f"append_event:{guild_id}:{action}:{details_json}")

        async def list_queue_events(self, guild_id: int, *, limit: int) -> list[SimpleNamespace]:
            calls.append(f"list_events:{guild_id}:{limit}")
            return []

        async def save_playlist(self, guild_id: int, user_id: int, name: str, items: list[PlaylistTrack]) -> None:
            calls.append(f"save_playlist:{guild_id}:{user_id}:{name}:{len(items)}")

        async def list_playlists(self, guild_id: int, user_id: int) -> list[str]:
            calls.append(f"list_playlists:{guild_id}:{user_id}")
            return []

        async def load_playlist(self, guild_id: int, user_id: int, name: str) -> list[PlaylistTrack]:
            calls.append(f"load_playlist:{guild_id}:{user_id}:{name}")
            return []

        async def delete_playlist(self, guild_id: int, user_id: int, name: str) -> int:
            calls.append(f"delete_playlist:{guild_id}:{user_id}:{name}")
            return 1

        async def add_favorite(self, guild_id: int, user_id: int, track: FavoriteTrack) -> None:
            calls.append(f"add_favorite:{guild_id}:{user_id}:{track.title}")

        async def list_favorites(self, guild_id: int, user_id: int) -> list[FavoriteTrack]:
            calls.append(f"list_favorites:{guild_id}:{user_id}")
            return []

        async def remove_favorite(self, guild_id: int, user_id: int, source_query: str) -> int:
            calls.append(f"remove_favorite:{guild_id}:{user_id}:{source_query}")
            return 1

    async def _run() -> None:
        store = FakeStore()
        settings_repo = GuildSettingsRepository(store)
        queue_repo = QueueRepository(store)
        playlist_repo = PlaylistRepository(store)
        favorites_repo = FavoritesRepository(store)

        await settings_repo.get(1)
        await settings_repo.upsert(1, GuildSettings(1.0, "off", False, False, "off"))
        await queue_repo.save(1, [])
        await queue_repo.load(1)
        await queue_repo.append_event(1, "enqueue", "{}")
        await queue_repo.list_events(1, limit=5)
        await playlist_repo.save(1, 2, "mix", [])
        await playlist_repo.list_names(1, 2)
        await playlist_repo.load(1, 2, "mix")
        await playlist_repo.delete(1, 2, "mix")
        await favorites_repo.add(1, 2, FavoriteTrack("Song", "src", "url", 10))
        await favorites_repo.list(1, 2)
        await favorites_repo.remove(1, 2, "src")

    asyncio.run(_run())
    assert any(item.startswith("save_playlist:1:2:mix") for item in calls)
    assert any(item.startswith("add_favorite:1:2:Song") for item in calls)
