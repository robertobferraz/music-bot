#!/usr/bin/env bash
set -euo pipefail

# Reseta o ambiente no namespace botmusica e reaplica manifests de producao.
# Uso:
#   ./scripts/k8s_reset_and_apply_prod.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Apagando namespace botmusica (se existir)..."
kubectl delete namespace botmusica --ignore-not-found=true

echo "Aguardando namespace terminar..."
for _ in {1..90}; do
  if ! kubectl get namespace botmusica >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if kubectl get namespace botmusica >/dev/null 2>&1; then
  echo "ERRO: namespace botmusica ainda existe. Verifique finalizers."
  exit 1
fi

echo "Reaplicando stack..."
./scripts/k8s_apply_prod.sh

echo "Reset + apply concluido."
