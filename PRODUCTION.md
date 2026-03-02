# Producao - Checklist Operacional

## 1. Segredos

- Definir tokens em secret manager ou `.env` local seguro.
- Rotacionar:
  - `DISCORD_TOKEN`
  - `WEB_PANEL_ADMIN_TOKEN`
  - `WEB_PANEL_SESSION_SECRET`
  - `WEB_PANEL_DISCORD_CLIENT_SECRET`
  - `POSTGRES_PASSWORD`
  - `LAVALINK_PASSWORD`
- Nao usar placeholders/defaults fracos em producao:
  - `DISCORD_TOKEN` real (nao `seu_token_aqui`)
  - `LAVALINK_PASSWORD` forte (nao `youshallnotpass`)
  - `POSTGRES_DSN` real (nao DSN de exemplo)
  - `POSTGRES_PASSWORD` forte (>=16)
  - `WEB_PANEL_ADMIN_TOKEN` forte (>=32)
  - `WEB_PANEL_SESSION_SECRET` forte (>=32)

## 1.2 Painel OAuth2 + RBAC

- Configurar OAuth2 da aplicação Discord:
  - Redirect URI: `https://seu-dominio/auth/callback` (ou equivalente local)
  - Scope mínimo: `identify`
- Definir:
  - `WEB_PANEL_DISCORD_CLIENT_ID`
  - `WEB_PANEL_DISCORD_CLIENT_SECRET`
  - `WEB_PANEL_DISCORD_REDIRECT_URI`
  - `WEB_PANEL_SESSION_SECRET`
  - `WEB_PANEL_ADMIN_USER_IDS`
  - `WEB_PANEL_DJ_USER_IDS`
- Durante migração:
  - `ADMIN_SLASH_ENABLED=true` (deprecated)
  - Próxima release: `ADMIN_SLASH_ENABLED=false`

## 1.1 Discord Portal

- Em `Bot > Privileged Gateway Intents`, habilitar `Message Content Intent`.

## 2. Preflight

```bash
./scripts/prod_preflight.sh
```

## 3. Deploy

```bash
./scripts/prod_deploy_local.sh
```

## 4. Health

```bash
docker compose ps
curl -fsS http://127.0.0.1:8090/health
docker compose logs --tail=120 botmusica lavalink postgres
```

## 5. Observabilidade

- Scrape de `/metrics`.
- Alertas recomendados:
  - `botmusica_command_errors` alto
  - `botmusica_playback_failures` alto
  - `botmusica_search_p95_ms` e `botmusica_play_p95_ms` acima do SLO
  - falha em `/health`

## 6. Backup/restore Postgres

Backup:

```bash
./scripts/postgres_backup.sh
```

Restore:

```bash
./scripts/postgres_restore.sh ./backups/postgres/backup_YYYYMMDD_HHMMSS.sql
```

## 7. Rollback

```bash
docker compose down
# voltar imagem/tag anterior
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## 8. Kubernetes (opcional)

Aplicar base:

```bash
./scripts/k8s_apply_prod.sh
```

Requisitos adicionais de k8s apply:
- Definir `BOT_IMAGE` com tag imutavel (ex.: `botmusica:2026-02-28`).
- O script bloqueia `:latest` por padrao.
- Backups diarios sao aplicados via `CronJob/postgres-backup`.
- Se existir Prometheus Operator, regras basicas de alerta sao aplicadas automaticamente.

## 9. Smoke de integracao

Script opcional para validar `botmusica + lavalink + postgres`:

```bash
DISCORD_TOKEN=... \
POSTGRES_DSN=postgresql://... \
LAVALINK_PASSWORD=... \
./scripts/integration_docker.sh
```
