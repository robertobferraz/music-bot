#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker nao encontrado"
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose nao encontrado"
  exit 1
fi

echo "[smoke] subindo stack bot..."
docker compose up -d --build

echo "[smoke] aguardando bot conectar..."
for _ in {1..45}; do
  if docker compose logs botmusica 2>/dev/null | grep -q "Bot conectado como"; then
    echo "[smoke] ok: bot conectado"
    exit 0
  fi
  sleep 2
done

echo "[smoke] falhou: bot nao conectou no tempo esperado"
docker compose ps
docker compose logs --tail=120 botmusica || true
exit 1
