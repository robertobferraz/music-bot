#!/usr/bin/env bash
set -euo pipefail

# Deploy local estilo producao usando compose + override.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

./scripts/prod_preflight.sh

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

echo "Aguardando healthcheck do bot..."
for _ in {1..45}; do
  if curl -fsS "http://127.0.0.1:8090/health" >/dev/null 2>&1; then
    echo "OK: /health respondeu."
    docker compose ps
    exit 0
  fi
  sleep 2
done

echo "Falha: /health nao respondeu no tempo esperado."
docker compose logs --tail=120 botmusica lavalink postgres || true
exit 1
