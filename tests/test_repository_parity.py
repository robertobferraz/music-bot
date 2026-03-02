from __future__ import annotations

import inspect

from botmusica.music.postgres_storage import PostgresSettingsStore
from botmusica.music.storage import SettingsStore


def _public_async_methods(cls: type) -> set[str]:
    names: set[str] = set()
    for name, member in inspect.getmembers(cls):
        if name.startswith("_"):
            continue
        if inspect.iscoroutinefunction(member):
            names.add(name)
    return names


def test_sqlite_postgres_public_async_api_parity() -> None:
    sqlite_api = _public_async_methods(SettingsStore)
    postgres_api = _public_async_methods(PostgresSettingsStore)
    missing = sqlite_api - postgres_api
    assert not missing, f"Postgres store sem métodos async do SQLite: {sorted(missing)}"
