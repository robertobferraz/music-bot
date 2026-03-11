# Bot de Música para Discord

Bot de música para Discord com comandos slash (`/`), reprodução via `yt-dlp` e suporte a Lavalink.

## O que o projeto cobre
- Fila por servidor com persistência
- Busca (`/search`) com cache e autocomplete
- Reprodução com fallback (`yt-dlp` e/ou Lavalink)
- Favoritos e playlists pessoais
- Painel web opcional com status e ações
- Painel web com login Discord OAuth2 + RBAC (`admin`/`dj`/`viewer`)
- Deploy local (Docker Compose) e Kubernetes

## Stack
- Python 3.11+
- `discord.py`
- `yt-dlp`
- `wavelink`
- `ffmpeg`
- SQLite (padrão) ou PostgreSQL

## Estrutura resumida
```text
src/botmusica/
  main.py
  config.py
  music/
    cog.py
    cog_modules/
    services/
```

## Setup rápido (local)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
python -m botmusica
```

No Discord Developer Portal, habilite o intent privilegiado `Message Content Intent` para evitar comandos limitados.

Se for usar PostgreSQL:
```bash
pip install -e .[postgres]
```

## Variáveis essenciais (`.env`)
Mínimo para subir:

```env
DISCORD_TOKEN=seu_token
BOT_REPOSITORY_BACKEND=sqlite
BOT_DB_PATH=botmusica.db
```

Para produção com Postgres:

```env
BOT_REPOSITORY_BACKEND=postgres
POSTGRES_DSN=postgresql://usuario:senha@host:5432/botmusica
```

Para reprodução com Lavalink:

```env
LAVALINK_ENABLED=false
LAVALINK_HOST=lavalink
LAVALINK_PORT=2333
LAVALINK_PASSWORD=sua_senha
```

Observação: o arquivo [.env.example](./.env.example) tem opções detalhadas de tuning.

## Comandos principais
- `/play`, `/playnext`, `/search`
- `/pause`, `/resume`, `/skip`, `/stop`
- `/queue`, `/nowplaying`, `/lyrics`
- `/fav_add`, `/fav_list`, `/fav_play`
- `/playlist_save`, `/playlist_list`, `/playlist_load`
- `/settings` (admin no painel web)

## Painel Admin (OAuth2 + RBAC)
Use o painel para operações administrativas (`moderation`, `cache`, `diagnostics`, `control_room`).

Variáveis de autenticação:
```env
WEB_PANEL_ENABLED=true
WEB_PANEL_HOST=0.0.0.0
WEB_PANEL_PORT=8080
WEB_PANEL_DISCORD_CLIENT_ID=...
WEB_PANEL_DISCORD_CLIENT_SECRET=...
WEB_PANEL_DISCORD_REDIRECT_URI=http://127.0.0.1:8080/auth/callback
WEB_PANEL_SESSION_SECRET=um_segredo_longo
WEB_PANEL_ADMIN_USER_IDS=123...,456...
WEB_PANEL_DJ_USER_IDS=789...,321...
```

Fallback opcional (token administrativo):
```env
WEB_PANEL_ADMIN_TOKEN=token_longo
```

Fase de migração de slash admin:
```env
ADMIN_SLASH_ENABLED=true
```
Mantenha `true` por uma release (deprecated) e depois `false` para remover slash administrativos.

## Testes
```bash
pip install -e .[dev]
pytest
```

## Docker-Compose
Subida local com bot + lavalink + postgres:

```bash
docker-compose up -d --build
```

Healthcheck:
```bash
curl -fsS http://127.0.0.1:8090/health
```

Logs:
```bash
docker-compose logs -f botmusica lavalink postgres
```

Parar:
```bash
docker-compose down
```

## Produção (local)
Checklist e fluxo em [PRODUCTION.md](./PRODUCTION.md).

Script de preflight:
```bash
./scripts/prod_preflight.sh
```

Deploy:
```bash
./scripts/prod_deploy_local.sh
```

## Kubernetes (local)
Manifestos em `deploy/k8s`.

Aplicar stack:
```bash
./scripts/k8s_apply_prod.sh
```

O script de apply em modo prod exige:
- `WEB_PANEL_ADMIN_TOKEN` forte (>=32 chars)
- `POSTGRES_PASSWORD` forte (>=16 chars)
- `BOT_IMAGE` com tag imutavel (nao `:latest`, a menos que use `ALLOW_LATEST_IMAGE=true`)

Reset + apply:
```bash
./scripts/k8s_reset_and_apply_prod.sh
```

Acompanhar:
```bash
kubectl -n botmusica get pods
kubectl -n botmusica logs -f deploy/botmusica
```

Backups automáticos do Postgres:
```bash
kubectl -n botmusica get cronjob postgres-backup
kubectl -n botmusica get pvc botmusica-postgres-backups
```

Painel web (port-forward):
```bash
kubectl -n botmusica port-forward svc/botmusica-web 8080:8080
```

## Troubleshooting rápido
- `OpusNotLoaded`: instalar `opus` no host e/ou configurar `OPUS_LIBRARY`
- `Backend postgres requer psycopg[binary]`: `pip install -e .[postgres]`
- Falha de busca YouTube: revisar `YTDLP_JS_RUNTIME` e `YTDLP_REMOTE_COMPONENTS`


## License
Este projeto está licenciado sob **MIT** (`MIT`).
Veja o arquivo [LICENSE](./LICENSE).
