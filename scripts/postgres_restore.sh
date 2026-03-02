#!/usr/bin/env bash
set -euo pipefail

# Restore do Postgres via docker compose.
# Uso:
#   ./scripts/postgres_restore.sh ./backups/postgres/backup_YYYYMMDD_HHMMSS.sql
#
# Requisitos:
# - Container postgres rodando
# - Arquivo de backup .sql existente

if [[ $# -lt 1 ]]; then
  echo "Uso: $0 <arquivo.sql>"
  exit 1
fi

in_file="$1"
if [[ ! -f "$in_file" ]]; then
  echo "Arquivo nao encontrado: $in_file"
  exit 1
fi

cat "$in_file" | docker compose exec -T postgres sh -lc '
  export PGPASSWORD="$POSTGRES_PASSWORD"
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"
'

echo "Restore concluido: $in_file"
