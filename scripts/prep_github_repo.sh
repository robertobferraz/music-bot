#!/usr/bin/env bash
set -euo pipefail

# Prepare repository for GitHub publication.
# Default mode is dry-run. Use --apply to perform changes.

APPLY=false
if [[ "${1:-}" == "--apply" ]]; then
  APPLY=true
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "ERRO: diretorio atual nao e um repositorio git."
  echo "Dica: execute 'git init' (ou clone o repo) e rode novamente."
  exit 1
fi

echo "[1/4] Verificando arquivos sensiveis/artefatos rastreados..."
PATTERN='(__pycache__/|\.pyc$|\.pyo$|\.pyd$|\.db$|^data/|^backups/|^\.env$|^\.env\..*|\.egg-info/)'
TRACKED_BAD="$(git ls-files | rg -n "$PATTERN" || true)"
if [[ -n "$TRACKED_BAD" ]]; then
  echo "Arquivos rastreados que nao deveriam estar no git:"
  echo "$TRACKED_BAD"
  if [[ "$APPLY" == true ]]; then
    echo "Removendo do indice (mantendo no disco)..."
    git ls-files | rg "$PATTERN" | xargs -I{} git rm --cached "{}"
  fi
else
  echo "OK: nenhum artefato rastreado encontrado."
fi

echo

echo "[2/4] Verificando placeholders e segredos em docs/exemplos..."
rg -n "DISCORD_TOKEN=|WEB_PANEL_ADMIN_TOKEN=|POSTGRES_DSN=.*@" .env.example README.md deploy || true

echo

echo "[3/4] Validando sintaxe Python..."
python -m compileall -q src tests

echo

echo "[4/4] Status final..."
git status --short

echo
if [[ "$APPLY" == true ]]; then
  echo "Concluido (modo apply)."
  echo "Proximo passo sugerido:"
  echo "  git add -A && git commit -m 'chore: prepare repository for github publish'"
else
  echo "Concluido (dry-run). Para aplicar limpeza no indice:"
  echo "  ./scripts/prep_github_repo.sh --apply"
fi
