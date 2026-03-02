#!/usr/bin/env bash
set -euo pipefail

# Smoke test de integracao: bot + Lavalink + Postgres
# Requisitos:
# - variaveis sensiveis no ambiente (sem placeholders/defaults fracos)
# - docker compose v2

if [[ -z "${DISCORD_TOKEN:-}" ]]; then
  echo "DISCORD_TOKEN nao definido. Exporte antes de rodar."
  exit 1
fi
if [[ "${DISCORD_TOKEN}" == "seu_token_aqui" || "${DISCORD_TOKEN}" == "COLOQUE_SEU_TOKEN_AQUI" || ${#DISCORD_TOKEN} -lt 30 ]]; then
  echo "DISCORD_TOKEN invalido/placeholder."
  exit 1
fi

if [[ -z "${POSTGRES_DSN:-}" ]]; then
  echo "POSTGRES_DSN nao definido. Exporte antes de rodar."
  exit 1
fi
if [[ "${POSTGRES_DSN}" == "postgresql://botmusica:botmusica@postgres:5432/botmusica" ]]; then
  echo "POSTGRES_DSN nao pode usar valor padrao de exemplo."
  exit 1
fi

if [[ -z "${LAVALINK_PASSWORD:-}" ]]; then
  echo "LAVALINK_PASSWORD nao definido. Exporte antes de rodar."
  exit 1
fi
if [[ "${LAVALINK_PASSWORD}" == "youshallnotpass" || ${#LAVALINK_PASSWORD} -lt 12 ]]; then
  echo "LAVALINK_PASSWORD insegura. Use senha forte (>=12) e nao use default."
  exit 1
fi

export BOT_REPOSITORY_BACKEND=postgres
export POSTGRES_DSN="${POSTGRES_DSN}"
export LAVALINK_ENABLED=true
export LAVALINK_HOST=lavalink
export LAVALINK_PORT=2333
export LAVALINK_PASSWORD="${LAVALINK_PASSWORD}"

docker compose up -d postgres lavalink botmusica

echo "Aguardando healthcheck do bot..."
for _ in {1..40}; do
  if curl -fsS "http://127.0.0.1:8090/health" >/dev/null 2>&1; then
    echo "OK: bot respondeu /health"
    exit 0
  fi
  sleep 2
done

echo "Falha: healthcheck nao respondeu dentro do tempo esperado."
docker compose logs --tail=120 botmusica lavalink postgres || true
exit 1
