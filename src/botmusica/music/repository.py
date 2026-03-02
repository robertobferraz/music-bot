from __future__ import annotations

from typing import Literal, Protocol

from botmusica.music.postgres_storage import PostgresSettingsStore
from botmusica.music.storage import SettingsStore

RepositoryBackend = Literal["sqlite", "postgres"]

class MusicRepository(Protocol):
    async def initialize(self) -> None: ...


class SqliteMusicRepository(SettingsStore):
    """Repositorio SQLite atual. Mantem API do SettingsStore para o cog."""


class PostgresMusicRepository(PostgresSettingsStore):
    """Repositorio Postgres com a mesma API assíncrona usada pelo cog."""


def create_repository(*, db_path: str, backend: str = "sqlite", postgres_dsn: str = "") -> MusicRepository:
    normalized = (backend or "sqlite").strip().casefold()
    if normalized == "sqlite":
        return SqliteMusicRepository(db_path)
    if normalized == "postgres":
        dsn = (postgres_dsn or "").strip()
        if not dsn:
            raise RuntimeError("BOT_REPOSITORY_BACKEND=postgres requer POSTGRES_DSN.")
        return PostgresMusicRepository(dsn)
    raise RuntimeError(f"Backend de repositorio invalido: {backend}")
