#!/usr/bin/env bash
set -euo pipefail

# Preflight de producao (Docker Compose).
# Nao aplica deploy: apenas valida configuracao e saude de prerequisitos.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f ".env" ]]; then
  echo "ERRO: arquivo .env nao encontrado."
  exit 1
fi

extract_env_value() {
  local key="$1"
  local raw
  raw="$(grep -E "^${key}=" .env | tail -n 1 | sed -E "s/^${key}=//" || true)"
  raw="$(printf '%s' "$raw" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')"
  if [[ "$raw" =~ ^\".*\"$ || "$raw" =~ ^\'.*\'$ ]]; then
    raw="${raw:1:${#raw}-2}"
  fi
  printf '%s' "$raw"
}

required_vars=(
  "DISCORD_TOKEN"
  "BOT_REPOSITORY_BACKEND"
  "LAVALINK_PASSWORD"
  "POSTGRES_PASSWORD"
)

missing=0
for key in "${required_vars[@]}"; do
  value="$(extract_env_value "${key}")"
  if [[ -z "${value}" ]]; then
    echo "ERRO: variavel obrigatoria ausente em .env: ${key}"
    missing=1
  fi
done
if [[ "$missing" -ne 0 ]]; then
  exit 1
fi

discord_token="$(extract_env_value 'DISCORD_TOKEN')"
if [[ "$discord_token" == "seu_token_aqui" || "$discord_token" == "COLOQUE_SEU_TOKEN_AQUI" ]]; then
  echo "ERRO: DISCORD_TOKEN parece placeholder."
  exit 1
fi
if [[ ${#discord_token} -lt 30 ]]; then
  echo "ERRO: DISCORD_TOKEN parece invalido (muito curto)."
  exit 1
fi

lavalink_password="$(extract_env_value 'LAVALINK_PASSWORD')"
if [[ "${lavalink_password}" == "youshallnotpass" || ${#lavalink_password} -lt 12 ]]; then
  echo "ERRO: LAVALINK_PASSWORD insegura. Use senha forte (>=12) e nao use default."
  exit 1
fi

postgres_password="$(extract_env_value 'POSTGRES_PASSWORD')"
if [[ "${postgres_password}" == "botmusica" || ${#postgres_password} -lt 16 ]]; then
  echo "ERRO: POSTGRES_PASSWORD insegura. Use senha forte (>=16) e nao use default."
  exit 1
fi

backend="$(extract_env_value 'BOT_REPOSITORY_BACKEND')"
if [[ "${backend}" != "sqlite" && "${backend}" != "postgres" ]]; then
  echo "ERRO: BOT_REPOSITORY_BACKEND deve ser 'sqlite' ou 'postgres'."
  exit 1
fi

if [[ "${backend}" == "postgres" ]]; then
  postgres_dsn="$(extract_env_value 'POSTGRES_DSN')"
  if [[ -z "${postgres_dsn}" ]]; then
    echo "ERRO: POSTGRES_DSN obrigatorio quando BOT_REPOSITORY_BACKEND=postgres."
    exit 1
  fi
  if [[ "${postgres_dsn}" == "postgresql://botmusica:botmusica@postgres:5432/botmusica" ]]; then
    echo "ERRO: POSTGRES_DSN esta no valor padrao de exemplo. Troque para credenciais reais."
    exit 1
  fi
fi

web_panel_enabled="$(extract_env_value 'WEB_PANEL_ENABLED')"
web_panel_admin_token="$(extract_env_value 'WEB_PANEL_ADMIN_TOKEN')"
web_panel_oauth_client_id="$(extract_env_value 'WEB_PANEL_DISCORD_CLIENT_ID')"
web_panel_oauth_client_secret="$(extract_env_value 'WEB_PANEL_DISCORD_CLIENT_SECRET')"
web_panel_oauth_redirect_uri="$(extract_env_value 'WEB_PANEL_DISCORD_REDIRECT_URI')"
web_panel_session_secret="$(extract_env_value 'WEB_PANEL_SESSION_SECRET')"
web_panel_enabled_norm="$(printf '%s' "${web_panel_enabled}" | tr '[:upper:]' '[:lower:]')"
if [[ "${web_panel_enabled_norm}" == "true" || "${web_panel_enabled}" == "1" ]]; then
  token_ok=true
  if [[ "${web_panel_admin_token}" == "troque_este_token_longo_e_aleatorio" || ${#web_panel_admin_token} -lt 32 ]]; then
    token_ok=false
  fi
  oauth_ok=true
  if [[ -z "${web_panel_oauth_client_id}" || -z "${web_panel_oauth_client_secret}" || -z "${web_panel_oauth_redirect_uri}" || ${#web_panel_session_secret} -lt 32 ]]; then
    oauth_ok=false
  fi
  if [[ "${token_ok}" != "true" && "${oauth_ok}" != "true" ]]; then
    echo "ERRO: WEB_PANEL_ENABLED=true exige WEB_PANEL_ADMIN_TOKEN >=32 OU OAuth completo (WEB_PANEL_DISCORD_CLIENT_ID + WEB_PANEL_DISCORD_CLIENT_SECRET + WEB_PANEL_DISCORD_REDIRECT_URI + WEB_PANEL_SESSION_SECRET>=32)."
    exit 1
  fi
fi

echo "Validando compose base..."
docker compose -f docker-compose.yml config >/dev/null
echo "Validando compose producao..."
docker compose -f docker-compose.yml -f docker-compose.prod.yml config >/dev/null

echo "Validando scripts shell..."
bash -n scripts/integration_docker.sh scripts/postgres_backup.sh scripts/postgres_restore.sh

echo "Validando sintaxe Python..."
python3 -m compileall -q src tests

echo "Preflight OK."
