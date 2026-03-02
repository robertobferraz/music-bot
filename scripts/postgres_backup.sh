#!/usr/bin/env bash
set -euo pipefail

# Backup do Postgres via docker compose.
# Uso:
#   ./scripts/postgres_backup.sh
#   ./scripts/postgres_backup.sh ./backups/postgres/manual.sql

out_file="${1:-./backups/postgres/backup_$(date +%Y%m%d_%H%M%S).sql}"
mkdir -p "$(dirname "$out_file")"

docker compose exec -T postgres sh -lc '
  export PGPASSWORD="$POSTGRES_PASSWORD"
  pg_dump --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"
' >"$out_file"

echo "Backup concluido: $out_file"
