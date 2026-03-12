#!/usr/bin/env bash
set -euo pipefail

# Apply baseline de producao no Kubernetes e aguarda rollout.
# Requisitos:
# - kubectl configurado para o cluster alvo

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
  # Normaliza valores do .env: remove espacos laterais e aspas simples/duplas envolventes.
  raw="$(printf '%s' "$raw" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')"
  if [[ "$raw" =~ ^\".*\"$ || "$raw" =~ ^\'.*\'$ ]]; then
    raw="${raw:1:${#raw}-2}"
  fi
  printf '%s' "$raw"
}

DISCORD_TOKEN="$(extract_env_value "DISCORD_TOKEN")"
WEB_PANEL_ADMIN_TOKEN="$(extract_env_value "WEB_PANEL_ADMIN_TOKEN")"
WEB_PANEL_DISCORD_CLIENT_ID="$(extract_env_value "WEB_PANEL_DISCORD_CLIENT_ID")"
WEB_PANEL_DISCORD_CLIENT_SECRET="$(extract_env_value "WEB_PANEL_DISCORD_CLIENT_SECRET")"
WEB_PANEL_DISCORD_REDIRECT_URI="$(extract_env_value "WEB_PANEL_DISCORD_REDIRECT_URI")"
WEB_PANEL_SESSION_SECRET="$(extract_env_value "WEB_PANEL_SESSION_SECRET")"
POSTGRES_DSN="$(extract_env_value "POSTGRES_DSN")"
POSTGRES_PASSWORD="$(extract_env_value "POSTGRES_PASSWORD")"
SPOTIFY_CLIENT_ID="$(extract_env_value "SPOTIFY_CLIENT_ID")"
SPOTIFY_CLIENT_SECRET="$(extract_env_value "SPOTIFY_CLIENT_SECRET")"
SPOTIFY_SP_DC="$(extract_env_value "SPOTIFY_SP_DC")"
BOT_REPOSITORY_BACKEND="$(extract_env_value "BOT_REPOSITORY_BACKEND")"
BOT_IMAGE_RAW="$(extract_env_value "BOT_IMAGE")"
BOT_IMAGE="${BOT_IMAGE_RAW:-botmusica:latest}"
ALLOW_LATEST_IMAGE="${ALLOW_LATEST_IMAGE:-false}"

if [[ "${DISCORD_TOKEN}" == "seu_token_aqui" || "${DISCORD_TOKEN}" == "COLOQUE_SEU_TOKEN_AQUI" || ${#DISCORD_TOKEN} -lt 30 ]]; then
  echo "ERRO: DISCORD_TOKEN invalido/placeholder no .env."
  exit 1
fi
if [[ -z "${POSTGRES_PASSWORD}" || "${POSTGRES_PASSWORD}" == "botmusica" || ${#POSTGRES_PASSWORD} -lt 16 ]]; then
  echo "ERRO: POSTGRES_PASSWORD obrigatoria e deve ter >= 16 caracteres."
  exit 1
fi
oauth_ready=false
if [[ -n "${WEB_PANEL_DISCORD_CLIENT_ID}" && -n "${WEB_PANEL_DISCORD_CLIENT_SECRET}" && -n "${WEB_PANEL_DISCORD_REDIRECT_URI}" && -n "${WEB_PANEL_SESSION_SECRET}" ]]; then
  if [[ ${#WEB_PANEL_SESSION_SECRET} -lt 32 ]]; then
    echo "ERRO: WEB_PANEL_SESSION_SECRET deve ter >= 32 caracteres quando OAuth estiver ativo."
    exit 1
  fi
  oauth_ready=true
fi

token_ready=false
if [[ -n "${WEB_PANEL_ADMIN_TOKEN}" && "${WEB_PANEL_ADMIN_TOKEN}" != "troque_este_token_longo_e_aleatorio" && ${#WEB_PANEL_ADMIN_TOKEN} -ge 32 ]]; then
  token_ready=true
fi

if [[ "${oauth_ready}" != "true" && "${token_ready}" != "true" ]]; then
  echo "ERRO: Configure WEB_PANEL_ADMIN_TOKEN (>=32) ou OAuth completo (WEB_PANEL_DISCORD_CLIENT_ID + WEB_PANEL_DISCORD_CLIENT_SECRET + WEB_PANEL_DISCORD_REDIRECT_URI + WEB_PANEL_SESSION_SECRET>=32)."
  exit 1
fi
if [[ "${BOT_REPOSITORY_BACKEND}" == "postgres" ]]; then
  if [[ -z "${POSTGRES_DSN}" ]]; then
    echo "ERRO: POSTGRES_DSN obrigatorio quando BOT_REPOSITORY_BACKEND=postgres."
    exit 1
  fi
  if [[ "${POSTGRES_DSN}" == "postgresql://botmusica:botmusica@postgres:5432/botmusica" ]]; then
    echo "ERRO: POSTGRES_DSN esta no valor padrao de exemplo. Troque para credenciais reais."
    exit 1
  fi
fi
if [[ "${BOT_IMAGE}" == *":latest" || "${BOT_IMAGE}" == "botmusica" ]]; then
  if [[ "${ALLOW_LATEST_IMAGE}" != "true" ]]; then
    echo "ERRO: BOT_IMAGE nao pode usar :latest em producao. Defina BOT_IMAGE com tag imutavel (ex: botmusica:2026-02-28)."
    echo "Se quiser forcar latest neste ambiente, rode com ALLOW_LATEST_IMAGE=true."
    exit 1
  fi
fi

kubectl apply -f deploy/k8s/namespace.yaml
kubectl apply -f deploy/k8s/configmap.yaml
kubectl apply -f deploy/k8s/pvc.yaml
kubectl apply -f deploy/k8s/postgres-pvc.yaml
kubectl apply -f deploy/k8s/postgres-backup-pvc.yaml
kubectl apply -f deploy/k8s/pdb.yaml

kubectl -n botmusica delete secret botmusica-secret --ignore-not-found=true
secret_args=(
  --from-literal=DISCORD_TOKEN="${DISCORD_TOKEN}"
  --from-literal=POSTGRES_DSN="${POSTGRES_DSN}"
  --from-literal=POSTGRES_PASSWORD="${POSTGRES_PASSWORD}"
)
if [[ -n "${WEB_PANEL_ADMIN_TOKEN}" ]]; then
  secret_args+=(--from-literal=WEB_PANEL_ADMIN_TOKEN="${WEB_PANEL_ADMIN_TOKEN}")
fi
if [[ -n "${WEB_PANEL_DISCORD_CLIENT_SECRET}" ]]; then
  secret_args+=(--from-literal=WEB_PANEL_DISCORD_CLIENT_SECRET="${WEB_PANEL_DISCORD_CLIENT_SECRET}")
fi
if [[ -n "${WEB_PANEL_DISCORD_CLIENT_ID}" ]]; then
  secret_args+=(--from-literal=WEB_PANEL_DISCORD_CLIENT_ID="${WEB_PANEL_DISCORD_CLIENT_ID}")
fi
if [[ -n "${WEB_PANEL_DISCORD_REDIRECT_URI}" ]]; then
  secret_args+=(--from-literal=WEB_PANEL_DISCORD_REDIRECT_URI="${WEB_PANEL_DISCORD_REDIRECT_URI}")
fi
if [[ -n "${WEB_PANEL_SESSION_SECRET}" ]]; then
  secret_args+=(--from-literal=WEB_PANEL_SESSION_SECRET="${WEB_PANEL_SESSION_SECRET}")
fi
if [[ -n "${SPOTIFY_CLIENT_ID}" ]]; then
  secret_args+=(--from-literal=SPOTIFY_CLIENT_ID="${SPOTIFY_CLIENT_ID}")
fi
if [[ -n "${SPOTIFY_CLIENT_SECRET}" ]]; then
  secret_args+=(--from-literal=SPOTIFY_CLIENT_SECRET="${SPOTIFY_CLIENT_SECRET}")
fi
if [[ -n "${SPOTIFY_SP_DC}" ]]; then
  secret_args+=(--from-literal=SPOTIFY_SP_DC="${SPOTIFY_SP_DC}")
fi
kubectl -n botmusica create secret generic botmusica-secret "${secret_args[@]}"

kubectl apply -f deploy/k8s/deployment.yaml
kubectl -n botmusica set image deployment/botmusica botmusica="${BOT_IMAGE}"
kubectl apply -f deploy/k8s/service.yaml
kubectl apply -f deploy/k8s/postgres-deployment.yaml
kubectl apply -f deploy/k8s/postgres-service.yaml
kubectl apply -f deploy/k8s/postgres-backup-cronjob.yaml
kubectl apply -f deploy/k8s/spotify-tokener-deployment.yaml
kubectl apply -f deploy/k8s/spotify-tokener-service.yaml
if kubectl get crd prometheusrules.monitoring.coreos.com >/dev/null 2>&1; then
  kubectl apply -f deploy/k8s/prometheus-rules.yaml
else
  echo "AVISO: CRD PrometheusRule nao encontrado. Pulando deploy/k8s/prometheus-rules.yaml."
fi

# Garante restart real mesmo quando BOT_IMAGE usa a mesma tag.
kubectl -n botmusica rollout restart deployment/botmusica
kubectl -n botmusica rollout restart deployment/spotify-tokener

kubectl -n botmusica rollout status deploy/postgres
kubectl -n botmusica rollout status deploy/botmusica
kubectl -n botmusica rollout status deploy/spotify-tokener
kubectl -n botmusica get pods -o wide
