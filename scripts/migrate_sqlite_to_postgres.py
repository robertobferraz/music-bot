#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from typing import Any


TABLES = [
    "guild_settings",
    "user_favorites",
    "playlists",
    "playlist_items",
    "guild_queue_state",
    "guild_vote_state",
    "guild_nowplaying_state",
    "guild_queue_events",
    "guild_search_cache",
    "guild_query_stats",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migra dados SQLite do bot para PostgreSQL.")
    parser.add_argument("--sqlite", required=True, help="Caminho do arquivo SQLite.")
    parser.add_argument("--postgres-dsn", required=True, help="DSN do PostgreSQL.")
    return parser.parse_args()


def fetch_rows(conn: sqlite3.Connection, table: str) -> tuple[list[str], list[tuple[Any, ...]]]:
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if not cols:
        return [], []
    col_names = [str(row[1]) for row in cols]
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    return col_names, rows


def main() -> int:
    args = parse_args()
    try:
        import psycopg  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"psycopg nao instalado: {exc}")

    sqlite_conn = sqlite3.connect(args.sqlite)
    migrated_tables = 0
    total_rows = 0
    with psycopg.connect(args.postgres_dsn) as pg_conn:
        with pg_conn.cursor() as cur:
            for table in TABLES:
                cols, rows = fetch_rows(sqlite_conn, table)
                if not cols:
                    continue
                if not rows:
                    continue
                col_list = ", ".join(cols)
                placeholders = ", ".join(["%s"] * len(cols))
                insert_sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
                cur.executemany(insert_sql, rows)
                migrated_tables += 1
                total_rows += len(rows)
        pg_conn.commit()
    sqlite_conn.close()
    print(f"migrated_tables={migrated_tables} migrated_rows={total_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
