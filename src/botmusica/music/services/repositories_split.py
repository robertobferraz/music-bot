from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from botmusica.music.storage import FavoriteTrack, GuildSettings, PlaylistTrack, QueueTrack


@dataclass(slots=True)
class GuildSettingsRepository:
    store: Any

    async def get(self, guild_id: int) -> GuildSettings | None:
        return await self.store.get(guild_id)

    async def upsert(self, guild_id: int, settings: GuildSettings) -> None:
        await self.store.upsert(guild_id, settings)


@dataclass(slots=True)
class QueueRepository:
    store: Any

    async def save(self, guild_id: int, tracks: list[QueueTrack]) -> None:
        await self.store.save_queue_state(guild_id, tracks)

    async def load(self, guild_id: int) -> list[QueueTrack]:
        return await self.store.load_queue_state(guild_id)

    async def append_event(self, guild_id: int, action: str, details_json: str) -> None:
        await self.store.append_queue_event(guild_id, action, details_json)

    async def list_events(self, guild_id: int, *, limit: int) -> list[Any]:
        return await self.store.list_queue_events(guild_id, limit=limit)


@dataclass(slots=True)
class PlaylistRepository:
    store: Any

    async def save(self, guild_id: int, user_id: int, name: str, items: list[PlaylistTrack]) -> None:
        await self.store.save_playlist(guild_id, user_id, name, items)

    async def list_names(self, guild_id: int, user_id: int) -> list[str]:
        return await self.store.list_playlists(guild_id, user_id)

    async def load(self, guild_id: int, user_id: int, name: str) -> list[PlaylistTrack]:
        return await self.store.load_playlist(guild_id, user_id, name)

    async def delete(self, guild_id: int, user_id: int, name: str) -> int:
        return await self.store.delete_playlist(guild_id, user_id, name)


@dataclass(slots=True)
class FavoritesRepository:
    store: Any

    async def add(self, guild_id: int, user_id: int, track: FavoriteTrack) -> None:
        await self.store.add_favorite(guild_id, user_id, track)

    async def list(self, guild_id: int, user_id: int) -> list[FavoriteTrack]:
        return await self.store.list_favorites(guild_id, user_id)

    async def remove(self, guild_id: int, user_id: int, source_query: str) -> int:
        return await self.store.remove_favorite(guild_id, user_id, source_query)
