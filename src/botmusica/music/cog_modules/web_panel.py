from __future__ import annotations

import logging
import shutil
import time
from typing import Any, Mapping

import discord
from aiohttp import web
from discord.errors import DiscordException, Forbidden, HTTPException, NotFound

from botmusica.music.player import FILTERS
from botmusica.music.services.web_auth import (
    build_discord_oauth_authorize_url,
    create_oauth_state,
    create_signed_session_cookie,
    parse_signed_session_cookie,
    validate_admin_token,
    verify_oauth_state,
)
from botmusica.music.services.web_panel_template import build_web_panel_html

LOGGER = logging.getLogger("botmusica.music")


class WebPanelMixin:
    @staticmethod
    def _panel_payload_int(payload: Mapping[str, Any], name: str, default: int | None = None) -> int | None:
        value = payload.get(name)
        if value is None:
            return default
        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped and stripped.lstrip("-").isdigit():
                try:
                    return int(stripped)
                except ValueError:
                    return default
        return default

    @staticmethod
    def _panel_payload_bool(payload: Mapping[str, Any], name: str, default: bool = False) -> bool:
        value = payload.get(name)
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        return str(value).strip().casefold() in {"1", "true", "yes", "on"}

    async def _start_web_panel(self) -> None:
        oauth_enabled = bool(
            self.web_panel_oauth_client_id
            and self.web_panel_oauth_client_secret
            and self.web_panel_oauth_redirect_uri
            and self.web_panel_session_secret
        )
        session_cookie_name = "bm_panel_session"
        role_cache_ttl_seconds = 120.0
        role_cache: dict[int, tuple[str, float]] = {}

        async def role_for_user(user_id: int) -> str:
            admin_match = user_id in self.web_panel_admin_user_ids
            dj_match = user_id in self.web_panel_dj_user_ids
            if admin_match:
                LOGGER.info(
                    "Painel web role resolve uid=%s role=admin source=config admin_match=%s dj_match=%s",
                    user_id,
                    admin_match,
                    dj_match,
                )
                return "admin"
            if dj_match:
                LOGGER.info(
                    "Painel web role resolve uid=%s role=dj source=config admin_match=%s dj_match=%s",
                    user_id,
                    admin_match,
                    dj_match,
                )
                return "dj"
            cached = role_cache.get(user_id)
            now = time.monotonic()
            if cached and cached[1] > now:
                LOGGER.info(
                    "Painel web role resolve uid=%s role=%s source=cache admin_match=%s dj_match=%s",
                    user_id,
                    cached[0],
                    admin_match,
                    dj_match,
                )
                return cached[0]
            resolved = "viewer"
            permission_source = "none"
            for guild in self.bot.guilds:
                member = guild.get_member(user_id)
                if member is None:
                    try:
                        member = await guild.fetch_member(user_id)
                    except (NotFound, Forbidden):
                        continue
                    except (HTTPException, DiscordException):
                        LOGGER.debug(
                            "Falha ao resolver membro %s no guild %s para auth do painel.",
                            user_id,
                            guild.id,
                            exc_info=True,
                        )
                        continue
                permissions = member.guild_permissions
                if permissions.administrator:
                    resolved = "admin"
                    permission_source = f"guild:{guild.id}:administrator"
                    break
                if permissions.manage_channels:
                    resolved = "dj"
                    permission_source = f"guild:{guild.id}:manage_channels"
            role_cache[user_id] = (resolved, now + role_cache_ttl_seconds)
            LOGGER.info(
                "Painel web role resolve uid=%s role=%s source=%s admin_match=%s dj_match=%s",
                user_id,
                resolved,
                permission_source,
                admin_match,
                dj_match,
            )
            return resolved

        async def resolve_identity(request: web.Request) -> tuple[str, int | None, str]:
            if validate_admin_token(request, self.web_panel_admin_token):
                LOGGER.info("Painel web identity source=token role=admin")
                return "admin", None, "token"
            if not oauth_enabled:
                LOGGER.info("Painel web identity source=none role=viewer oauth_enabled=false")
                return "viewer", None, "none"
            raw_cookie = request.cookies.get(session_cookie_name, "")
            if not raw_cookie:
                LOGGER.info("Painel web identity source=oauth_missing role=viewer")
                return "viewer", None, "oauth_missing"
            session_data = parse_signed_session_cookie(self.web_panel_session_secret, raw_cookie)
            if not session_data:
                LOGGER.info("Painel web identity source=oauth_invalid role=viewer reason=session_invalid")
                return "viewer", None, "oauth_invalid"
            uid = int(session_data.get("uid", 0) or 0)
            if uid <= 0:
                LOGGER.info("Painel web identity source=oauth_invalid role=viewer reason=uid_invalid")
                return "viewer", None, "oauth_invalid"
            role = await role_for_user(uid)
            LOGGER.info("Painel web identity source=oauth uid=%s role=%s", uid, role)
            return role, uid, "oauth"

        def allowed_for_role(role: str, action: str) -> bool:
            admin_only = {
                "moderation_show",
                "moderation_set_duration",
                "moderation_add_whitelist",
                "moderation_remove_whitelist",
                "moderation_clear_whitelist",
                "moderation_add_blacklist",
                "moderation_remove_blacklist",
                "moderation_clear_blacklist",
                "cache_stats",
                "cache_clear_search",
                "cache_clear_autocomplete",
                "cache_clear_all",
                "diagnostics",
                "control_room_create",
            }
            dj_or_admin = {
                "skip",
                "pause",
                "resume",
                "stop",
                "disconnect",
                "clear_queue",
                "shuffle",
                "remove",
                "jump",
                "move",
                "replay",
                "set_volume",
                "set_filter",
                "set_loop",
                "set_autoplay",
                "set_stay_connected",
            }
            if action in admin_only:
                return role == "admin"
            if action in dj_or_admin:
                return role in {"admin", "dj"}
            return False

        async def health(_request: web.Request) -> web.Response:
            return web.json_response({"ok": True})

        async def auth_me(request: web.Request) -> web.Response:
            role, user_id, source = await resolve_identity(request)
            authed = role in {"admin", "dj"} if oauth_enabled else bool(self.web_panel_admin_token)
            LOGGER.info(
                "Painel web /auth/me uid=%s role=%s source=%s authenticated=%s oauth_enabled=%s",
                user_id,
                role,
                source,
                authed,
                oauth_enabled,
            )
            return web.json_response(
                {
                    "ok": True,
                    "oauth_enabled": oauth_enabled,
                    "role": role,
                    "user_id": user_id,
                    "source": source,
                    "authenticated": authed,
                    "login_url": "/auth/login" if oauth_enabled else None,
                    "logout_url": "/auth/logout" if oauth_enabled else None,
                }
            )

        async def auth_login(_request: web.Request) -> web.Response:
            if not oauth_enabled:
                return web.HTTPFound("/")
            state = create_oauth_state(self.web_panel_session_secret)
            url = build_discord_oauth_authorize_url(
                client_id=self.web_panel_oauth_client_id,
                redirect_uri=self.web_panel_oauth_redirect_uri,
                state=state,
                scope="identify",
            )
            raise web.HTTPFound(url)

        async def auth_callback(request: web.Request) -> web.Response:
            if not oauth_enabled:
                raise web.HTTPFound("/")
            state = str(request.query.get("state") or "").strip()
            code = str(request.query.get("code") or "").strip()
            if not state or not code or not verify_oauth_state(self.web_panel_session_secret, state):
                return web.Response(text="OAuth state invalido.", status=400)

            session = self._http_session
            if session is None or session.closed:
                return web.Response(text="HTTP session indisponivel.", status=500)

            token_resp = await session.post(
                "https://discord.com/api/oauth2/token",
                data={
                    "client_id": self.web_panel_oauth_client_id,
                    "client_secret": self.web_panel_oauth_client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.web_panel_oauth_redirect_uri,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if token_resp.status >= 400:
                text = await token_resp.text()
                LOGGER.warning("OAuth token exchange falhou: %s %s", token_resp.status, text)
                return web.Response(text="Falha ao autenticar no Discord.", status=401)

            token_payload = await token_resp.json()
            access_token = str(token_payload.get("access_token") or "").strip()
            if not access_token:
                return web.Response(text="Access token ausente.", status=401)

            me_resp = await session.get(
                "https://discord.com/api/users/@me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if me_resp.status >= 400:
                text = await me_resp.text()
                LOGGER.warning("OAuth users/@me falhou: %s %s", me_resp.status, text)
                return web.Response(text="Falha ao obter perfil do Discord.", status=401)
            me_payload = await me_resp.json()
            uid = int(str(me_payload.get("id") or "0"))
            if uid <= 0:
                return web.Response(text="Usuario invalido.", status=401)
            resolved_role = await role_for_user(uid)
            LOGGER.info(
                "Painel web OAuth callback uid=%s username=%s role=%s admin_ids=%s dj_ids=%s",
                uid,
                str(me_payload.get("username") or "discord-user"),
                resolved_role,
                sorted(self.web_panel_admin_user_ids),
                sorted(self.web_panel_dj_user_ids),
            )

            cookie = create_signed_session_cookie(
                secret=self.web_panel_session_secret,
                payload={
                    "uid": uid,
                    "username": str(me_payload.get("username") or "discord-user"),
                    "avatar": str(me_payload.get("avatar") or ""),
                },
                ttl_seconds=12 * 3600,
            )
            response = web.HTTPFound("/")
            response.set_cookie(
                session_cookie_name,
                cookie,
                max_age=12 * 3600,
                httponly=True,
                secure=False,
                samesite="Lax",
                path="/",
            )
            raise response

        async def auth_logout(_request: web.Request) -> web.Response:
            response = web.json_response({"ok": True})
            response.del_cookie(session_cookie_name, path="/")
            return response

        async def prometheus_metrics(_request: web.Request) -> web.Response:
            snapshot = self._metrics_snapshot()
            guild_count = len(self.bot.guilds)
            queue_total = 0
            playing_guilds = 0
            paused_guilds = 0
            for guild in self.bot.guilds:
                player = await self._get_player(guild.id)
                queue_total += len(player.snapshot_queue())
                vc = guild.voice_client
                if self._is_voice_playing(vc):
                    playing_guilds += 1
                if self._is_voice_paused(vc):
                    paused_guilds += 1

            lines = [
                "# HELP botmusica_command_calls Total de comandos concluídos",
                "# TYPE botmusica_command_calls counter",
                f"botmusica_command_calls {snapshot.command_calls}",
                "# HELP botmusica_command_errors Total de erros de comandos",
                "# TYPE botmusica_command_errors counter",
                f"botmusica_command_errors {snapshot.command_errors}",
                "# HELP botmusica_extraction_failures Total de falhas de extração",
                "# TYPE botmusica_extraction_failures counter",
                f"botmusica_extraction_failures {snapshot.extraction_failures}",
                "# HELP botmusica_playback_failures Total de falhas de playback",
                "# TYPE botmusica_playback_failures counter",
                f"botmusica_playback_failures {snapshot.playback_failures}",
                "# HELP botmusica_avg_latency_ms Latência média dos comandos em ms",
                "# TYPE botmusica_avg_latency_ms gauge",
                f"botmusica_avg_latency_ms {snapshot.average_latency_ms:.2f}",
                "# HELP botmusica_guilds_total Total de servidores conectados",
                "# TYPE botmusica_guilds_total gauge",
                f"botmusica_guilds_total {guild_count}",
                "# HELP botmusica_queue_items_total Total de itens pendentes em todas as filas",
                "# TYPE botmusica_queue_items_total gauge",
                f"botmusica_queue_items_total {queue_total}",
                "# HELP botmusica_guilds_playing Total de guilds reproduzindo agora",
                "# TYPE botmusica_guilds_playing gauge",
                f"botmusica_guilds_playing {playing_guilds}",
                "# HELP botmusica_guilds_paused Total de guilds pausados",
                "# TYPE botmusica_guilds_paused gauge",
                f"botmusica_guilds_paused {paused_guilds}",
            ]
            return web.Response(text="\n".join(lines) + "\n", content_type="text/plain")

        async def api_status(request: web.Request) -> web.Response:
            role, user_id, source = await resolve_identity(request)
            guilds: list[dict[str, Any]] = []
            for guild in self.bot.guilds:
                player = await self._get_player(guild.id)
                vc = guild.voice_client
                policy = self._policy_for_guild(guild.id)
                queue_snapshot = player.snapshot_queue()
                queue_preview = [track.title for track in queue_snapshot[:7]]
                control_state = await self.store.get_control_room_state(guild.id)
                current_duration = (
                    int(player.current.duration_seconds)
                    if player.current and isinstance(player.current.duration_seconds, int)
                    else 0
                )
                elapsed_seconds = 0
                if player.current and player.current_started_at is not None:
                    elapsed = time.monotonic() - player.current_started_at - player.paused_accumulated_seconds
                    if player.pause_started_at is not None:
                        elapsed -= max(time.monotonic() - player.pause_started_at, 0.0)
                    elapsed_seconds = max(int(elapsed), 0)
                if current_duration > 0:
                    elapsed_seconds = min(elapsed_seconds, current_duration)
                guilds.append(
                    {
                        "guild_id": str(guild.id),
                        "guild_name": guild.name,
                        "guild_icon_url": str(guild.icon.url) if guild.icon else None,
                        "connected": self._is_voice_connected(vc),
                        "playing": self._is_voice_playing(vc),
                        "paused": self._is_voice_paused(vc),
                        "player_state": self._player_state_label(guild.id),
                        "current": player.current.title if player.current else None,
                        "current_artist": player.current.artist if player.current else None,
                        "current_duration_seconds": current_duration,
                        "current_elapsed_seconds": elapsed_seconds,
                        "queue_size": len(queue_snapshot),
                        "queue_preview": queue_preview,
                        "voice_channel": getattr(getattr(vc, "channel", None), "name", None),
                        "settings": {
                            "volume_percent": int(round(player.volume * 100)),
                            "filter": player.audio_filter,
                            "loop_mode": player.loop_mode,
                            "autoplay": bool(player.autoplay),
                            "stay_connected": bool(player.stay_connected),
                        },
                        "moderation": {
                            "max_track_duration_seconds": policy.max_track_duration_seconds,
                            "whitelist_count": len(policy.domain_whitelist),
                            "blacklist_count": len(policy.domain_blacklist),
                            "whitelist": sorted(policy.domain_whitelist),
                            "blacklist": sorted(policy.domain_blacklist),
                        },
                        "control_room": {
                            "configured": bool(control_state),
                            "channel_id": str(control_state.channel_id) if control_state else "0",
                            "message_id": str(control_state.message_id) if control_state else "0",
                        },
                    }
                )
            snapshot = self._metrics_snapshot()
            return web.json_response(
                {
                    "bot_user": str(self.bot.user) if self.bot.user else None,
                    "auth": {
                        "oauth_enabled": oauth_enabled,
                        "role": role,
                        "user_id": user_id,
                        "source": source,
                    },
                    "runtime": {
                        "uptime_seconds": int(max(time.monotonic() - self._boot_started_mono, 0.0)),
                        "repository_backend": str(getattr(self.bot, "repository_backend", "sqlite")),
                        "lavalink_enabled": bool(self.lavalink_enabled),
                        "admin_slash_enabled": bool(self.admin_slash_enabled),
                    },
                    "guilds": guilds,
                    "actions_enabled": role in {"admin", "dj"} or bool(self.web_panel_admin_token),
                    "metrics": {
                        "command_calls": snapshot.command_calls,
                        "command_errors": snapshot.command_errors,
                        "extraction_failures": snapshot.extraction_failures,
                        "playback_failures": snapshot.playback_failures,
                        "average_latency_ms": snapshot.average_latency_ms,
                        "window_5m": self._command_metrics_window.snapshot(window_seconds=300),
                        "slo_5m": {
                            "play_p50_ms": self._command_metrics_window.percentile_ms("play", 50, window_seconds=300),
                            "play_p95_ms": self._command_metrics_window.percentile_ms("play", 95, window_seconds=300),
                            "play_p99_ms": self._command_metrics_window.percentile_ms("play", 99, window_seconds=300),
                            "search_p50_ms": self._command_metrics_window.percentile_ms("search", 50, window_seconds=300),
                            "search_p95_ms": self._command_metrics_window.percentile_ms("search", 95, window_seconds=300),
                            "search_p99_ms": self._command_metrics_window.percentile_ms("search", 99, window_seconds=300),
                        },
                    },
                }
            )

        async def api_action(request: web.Request) -> web.Response:
            try:
                payload = await request.json()
            except Exception:
                return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
            if not isinstance(payload, dict):
                return web.json_response({"ok": False, "error": "invalid_payload"}, status=400)

            action = str(payload.get("action") or "").strip().casefold()
            role, _user_id, _source = await resolve_identity(request)
            if not allowed_for_role(role, action):
                return web.json_response({"ok": False, "error": "forbidden"}, status=403)

            guild_id_raw = payload.get("guild_id")
            guild_id: int | None = None
            if isinstance(guild_id_raw, int):
                guild_id = guild_id_raw
            elif isinstance(guild_id_raw, str):
                stripped = guild_id_raw.strip()
                if stripped.isdigit():
                    guild_id = int(stripped)
            if guild_id is None or guild_id <= 0:
                return web.json_response({"ok": False, "error": "invalid_guild_id"}, status=400)
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                return web.json_response({"ok": False, "error": "guild_not_found"}, status=404)
            player = await self._get_player(guild.id)
            voice_client = guild.voice_client

            if action == "moderation_show":
                policy = self._policy_for_guild(guild.id)
                return web.json_response(
                    {
                        "ok": True,
                        "action": action,
                        "moderation": {
                            "max_track_duration_seconds": policy.max_track_duration_seconds,
                            "whitelist": sorted(policy.domain_whitelist),
                            "blacklist": sorted(policy.domain_blacklist),
                        },
                    }
                )

            if action == "moderation_set_duration":
                seconds = self._panel_payload_int(payload, "seconds")
                if seconds is None or seconds < 0:
                    return web.json_response({"ok": False, "error": "invalid_seconds"}, status=400)
                policy = self._policy_for_guild(guild.id)
                policy.max_track_duration_seconds = int(seconds)
                self._guild_policy[guild.id] = policy
                await self._save_player_settings(guild.id, player)
                return web.json_response({"ok": True, "action": action, "seconds": int(seconds)})

            if action in {
                "moderation_add_whitelist",
                "moderation_remove_whitelist",
                "moderation_add_blacklist",
                "moderation_remove_blacklist",
            }:
                domain = str(payload.get("domain") or "").strip().casefold()
                if not domain:
                    return web.json_response({"ok": False, "error": "invalid_domain"}, status=400)
                policy = self._policy_for_guild(guild.id)
                if action == "moderation_add_whitelist":
                    policy.domain_whitelist.add(domain)
                elif action == "moderation_remove_whitelist":
                    policy.domain_whitelist.discard(domain)
                elif action == "moderation_add_blacklist":
                    policy.domain_blacklist.add(domain)
                else:
                    policy.domain_blacklist.discard(domain)
                self._guild_policy[guild.id] = policy
                await self._save_player_settings(guild.id, player)
                return web.json_response({"ok": True, "action": action, "domain": domain})

            if action in {"moderation_clear_whitelist", "moderation_clear_blacklist"}:
                policy = self._policy_for_guild(guild.id)
                if action == "moderation_clear_whitelist":
                    policy.domain_whitelist.clear()
                else:
                    policy.domain_blacklist.clear()
                self._guild_policy[guild.id] = policy
                await self._save_player_settings(guild.id, player)
                return web.json_response({"ok": True, "action": action})

            if action == "cache_stats":
                return web.json_response(
                    {
                        "ok": True,
                        "action": action,
                        "summary": self._cache_stats_summary(),
                        "search_cache_entries": len(self._search_cache),
                        "autocomplete_cache_entries": len(self._autocomplete_rank_cache),
                    }
                )

            if action in {"cache_clear_search", "cache_clear_autocomplete", "cache_clear_all"}:
                if action in {"cache_clear_search", "cache_clear_all"}:
                    self._search_cache.clear()
                if action in {"cache_clear_autocomplete", "cache_clear_all"}:
                    self._autocomplete_rank_cache.clear()
                return web.json_response({"ok": True, "action": action, "summary": self._cache_stats_summary()})

            if action == "diagnostics":
                ffmpeg = "ok" if shutil.which("ffmpeg") else "missing"
                return web.json_response(
                    {
                        "ok": True,
                        "action": action,
                        "diagnostics": {
                            "ffmpeg": ffmpeg,
                            "opus_loaded": bool(discord.opus.is_loaded()),
                            "lavalink_enabled": bool(self.lavalink_enabled),
                            "avg_play_ms_5m": self._command_metrics_window.avg_ms("play", window_seconds=300),
                            "avg_search_ms_5m": self._command_metrics_window.avg_ms("search", window_seconds=300),
                            "queue_size": len(player.snapshot_queue()),
                            "player_state": self._player_state_label(guild.id),
                        },
                    }
                )

            if action == "control_room_create":
                channel_name = str(payload.get("name") or "bot-controle").strip().lower().replace(" ", "-")
                if not channel_name:
                    channel_name = "bot-controle"
                result = await self._provision_control_room(
                    guild,
                    channel_name=channel_name,
                    operator_id=0,
                    actor_label="web-panel",
                )
                return web.json_response({"ok": True, "action": action, **result})

            if action == "skip":
                if not self._is_voice_connected(voice_client):
                    return web.json_response({"ok": False, "error": "not_connected"}, status=409)
                player.suppress_after_playback = True
                await self._stop_voice(voice_client)
                return web.json_response({"ok": True, "action": action})
            if action == "pause":
                if voice_client is None or not self._is_voice_playing(voice_client):
                    return web.json_response({"ok": False, "error": "not_playing"}, status=409)
                await self._pause_voice(voice_client)
                if player.pause_started_at is None:
                    player.pause_started_at = time.monotonic()
                return web.json_response({"ok": True, "action": action})
            if action == "resume":
                if voice_client is None or not self._is_voice_paused(voice_client):
                    return web.json_response({"ok": False, "error": "not_paused"}, status=409)
                if player.pause_started_at is not None:
                    player.paused_accumulated_seconds += max(time.monotonic() - player.pause_started_at, 0.0)
                    player.pause_started_at = None
                await self._resume_voice(voice_client)
                return web.json_response({"ok": True, "action": action})
            if action == "stop":
                removed_total = 0
                lock = self._get_lock(guild.id)
                async with lock:
                    removed = self.queue_service.clear(player)
                    removed_total = len(removed)
                    player.current = None
                    player.current_started_at = None
                    player.pause_started_at = None
                    player.paused_accumulated_seconds = 0.0
                    player.suppress_after_playback = True
                    await self._persist_queue_state(guild.id, player)
                if self._is_voice_connected(voice_client):
                    await self._stop_voice(voice_client)
                return web.json_response({"ok": True, "action": action, "removed": removed_total})
            if action == "disconnect":
                if not self._is_voice_connected(voice_client):
                    return web.json_response({"ok": False, "error": "not_connected"}, status=409)
                lock = self._get_lock(guild.id)
                async with lock:
                    self.queue_service.clear(player)
                    player.current = None
                    player.current_started_at = None
                    player.pause_started_at = None
                    player.paused_accumulated_seconds = 0.0
                    player.suppress_after_playback = True
                    await self._persist_queue_state(guild.id, player)
                self._cancel_nowplaying_updater(guild.id)
                await self._stop_voice(voice_client)
                self._cancel_idle_timer(guild.id)
                self._cancel_prefetch(guild.id)
                self._mark_voice_reconnect_required(guild.id)
                await voice_client.disconnect(force=True)
                await self._clear_nowplaying_message(guild.id)
                await self._clear_voice_mini_panel(guild.id)
                await self._clear_votes_for_guild(guild.id)
                self.music.remove_player(guild.id)
                self._loaded_settings.discard(guild.id)
                return web.json_response({"ok": True, "action": action})
            if action == "clear_queue":
                lock = self._get_lock(guild.id)
                async with lock:
                    removed = self.queue_service.clear(player)
                    await self._persist_queue_state(guild.id, player)
                return web.json_response({"ok": True, "action": action, "removed": len(removed)})
            if action == "shuffle":
                lock = self._get_lock(guild.id)
                async with lock:
                    total = self.queue_service.shuffle(player)
                    if total > 1:
                        await self._persist_queue_state(guild.id, player)
                return web.json_response({"ok": True, "action": action, "total": total})
            if action == "remove":
                position = self._panel_payload_int(payload, "position")
                if position is None or position < 1:
                    return web.json_response({"ok": False, "error": "invalid_position"}, status=400)
                lock = self._get_lock(guild.id)
                async with lock:
                    try:
                        removed_track = self.queue_service.remove(player, position)
                    except Exception:
                        return web.json_response({"ok": False, "error": "position_out_of_range"}, status=409)
                    await self._persist_queue_state(guild.id, player)
                return web.json_response({"ok": True, "action": action, "title": removed_track.title})
            if action == "jump":
                position = self._panel_payload_int(payload, "position")
                if position is None or position < 1:
                    return web.json_response({"ok": False, "error": "invalid_position"}, status=400)
                lock = self._get_lock(guild.id)
                async with lock:
                    try:
                        picked_track = self.queue_service.jump(player, position)
                    except Exception:
                        return web.json_response({"ok": False, "error": "position_out_of_range"}, status=409)
                    await self._persist_queue_state(guild.id, player)
                return web.json_response({"ok": True, "action": action, "title": picked_track.title})
            if action == "move":
                source_pos = self._panel_payload_int(payload, "source_pos")
                target_pos = self._panel_payload_int(payload, "target_pos")
                if source_pos is None or target_pos is None or source_pos < 1 or target_pos < 1:
                    return web.json_response({"ok": False, "error": "invalid_move_positions"}, status=400)
                lock = self._get_lock(guild.id)
                async with lock:
                    try:
                        moved_track = self.queue_service.move(player, source_pos, target_pos)
                    except Exception:
                        return web.json_response({"ok": False, "error": "position_out_of_range"}, status=409)
                    await self._persist_queue_state(guild.id, player)
                return web.json_response({"ok": True, "action": action, "title": moved_track.title})
            if action == "replay":
                if not self._is_voice_connected(voice_client):
                    return web.json_response({"ok": False, "error": "not_connected"}, status=409)
                if player.current is None:
                    return web.json_response({"ok": False, "error": "no_current_track"}, status=409)
                lock = self._get_lock(guild.id)
                current_title = player.current.title
                async with lock:
                    self.queue_service.enqueue_front(player, player.current)
                    player.suppress_after_playback = True
                    player.current_started_at = None
                    player.pause_started_at = None
                    player.paused_accumulated_seconds = 0.0
                    await self._persist_queue_state(guild.id, player)
                await self._stop_voice(voice_client)
                return web.json_response({"ok": True, "action": action, "title": current_title})
            if action == "set_volume":
                percent = self._panel_payload_int(payload, "volume_percent")
                if percent is None:
                    return web.json_response({"ok": False, "error": "invalid_volume"}, status=400)
                normalized = max(min(percent, 200), 1) / 100.0
                player.volume = normalized
                await self._save_player_settings(guild.id, player)
                if self._is_voice_connected(voice_client):
                    await self._set_voice_volume(voice_client, normalized)
                return web.json_response({"ok": True, "action": action, "volume_percent": int(round(normalized * 100))})
            if action == "set_filter":
                mode = str(payload.get("filter") or "").strip().casefold()
                if mode not in FILTERS:
                    return web.json_response({"ok": False, "error": "invalid_filter"}, status=400)
                player.audio_filter = mode
                await self._save_player_settings(guild.id, player)
                if voice_client and player.current:
                    lock = self._get_lock(guild.id)
                    async with lock:
                        self.queue_service.enqueue_front(player, player.current)
                        player.suppress_after_playback = True
                        await self._persist_queue_state(guild.id, player)
                    await self._stop_voice(voice_client)
                return web.json_response({"ok": True, "action": action, "filter": mode})
            if action == "set_loop":
                mode = str(payload.get("loop_mode") or "").strip().casefold()
                if mode not in {"off", "track", "queue"}:
                    return web.json_response({"ok": False, "error": "invalid_loop_mode"}, status=400)
                player.loop_mode = mode
                await self._save_player_settings(guild.id, player)
                return web.json_response({"ok": True, "action": action, "loop_mode": mode})
            if action == "set_autoplay":
                enabled = self._panel_payload_bool(payload, "enabled", default=player.autoplay)
                player.autoplay = enabled
                await self._save_player_settings(guild.id, player)
                return web.json_response({"ok": True, "action": action, "enabled": enabled})
            if action == "set_stay_connected":
                enabled = self._panel_payload_bool(payload, "enabled", default=player.stay_connected)
                player.stay_connected = enabled
                await self._save_player_settings(guild.id, player)
                return web.json_response({"ok": True, "action": action, "enabled": enabled})
            return web.json_response({"ok": False, "error": "unsupported_action"}, status=400)

        async def index(_request: web.Request) -> web.Response:
            html = build_web_panel_html()
            return web.Response(text=html, content_type="text/html")

        app = web.Application()
        app.router.add_get("/", index)
        app.router.add_get("/health", health)
        app.router.add_get("/auth/login", auth_login)
        app.router.add_get("/auth/callback", auth_callback)
        app.router.add_post("/auth/logout", auth_logout)
        app.router.add_get("/auth/me", auth_me)
        app.router.add_get("/api/status", api_status)
        app.router.add_post("/api/action", api_action)
        app.router.add_get("/metrics", prometheus_metrics)
        self._web_runner = web.AppRunner(app)
        await self._web_runner.setup()
        self._web_site = web.TCPSite(self._web_runner, self.web_panel_host, self.web_panel_port)
        await self._web_site.start()
        LOGGER.info("Painel web ativo em http://%s:%s", self.web_panel_host, self.web_panel_port)

    async def _stop_web_panel(self) -> None:
        if self._web_site:
            await self._web_site.stop()
            self._web_site = None
        if self._web_runner:
            await self._web_runner.cleanup()
            self._web_runner = None
