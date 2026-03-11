from __future__ import annotations

import asyncio
import logging
import time
from typing import cast
from urllib.parse import urlparse

import discord
from discord import app_commands

from botmusica.music.command_domains import command_domain
from botmusica.music.player import Track, TrackBatch
from botmusica.music.services.playback_scheduler import QueuePriority
from botmusica.music.views import SearchView

LOGGER = logging.getLogger("botmusica.music")


async def _play_autocomplete_proxy(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    cog = interaction.client.get_cog("MusicCog")
    if cog is None:
        return []
    return await cast(object, cog)._play_autocomplete(interaction, current)


async def _search_autocomplete_proxy(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    cog = interaction.client.get_cog("MusicCog")
    if cog is None:
        return []
    return await cast(object, cog)._search_autocomplete(interaction, current)


class PlayCommandsMixin:
    @staticmethod
    def _is_spotify_or_apple_url(value: str) -> bool:
        raw = value.strip()
        if "://" not in raw:
            return False
        try:
            host = (urlparse(raw).hostname or "").casefold()
        except ValueError:
            return False
        if not host:
            return False
        return host.endswith("spotify.com") or host == "music.apple.com" or host.endswith(".music.apple.com")

    @staticmethod
    def _is_spotify_collection_url(value: str) -> bool:
        raw = value.strip()
        if "://" not in raw:
            return False
        try:
            parsed = urlparse(raw)
        except ValueError:
            return False
        host = (parsed.hostname or "").casefold()
        if host != "open.spotify.com" and not host.endswith(".spotify.com"):
            return False
        parts = [part for part in parsed.path.split("/") if part]
        if not parts:
            return False
        if parts[0].startswith("intl-") and len(parts) >= 2:
            kind = parts[1].casefold()
        else:
            kind = parts[0].casefold()
        return kind in {"playlist", "album"}

    @staticmethod
    def _looks_like_direct_url(value: str) -> bool:
        raw = value.strip()
        return "://" in raw and not raw.startswith("search:")

    def _can_use_lavalink_fastpath(self, query: str, *, to_front: bool) -> bool:
        if to_front:
            return False
        if not self.lavalink_enabled:
            return False
        if self._looks_like_playlist_query(query):
            return False
        if not self._looks_like_direct_url(query):
            return False
        if self._is_spotify_or_apple_url(query):
            return False
        return True

    @staticmethod
    def _is_streaming_catalog_url(value: str) -> bool:
        raw = value.strip()
        if "://" not in raw:
            return False
        try:
            host = (urlparse(raw).hostname or "").casefold()
        except ValueError:
            return False
        if not host:
            return False
        return (
            host.endswith("spotify.com")
            or host == "music.apple.com"
            or host.endswith(".music.apple.com")
            or host.endswith("deezer.com")
        )

    @staticmethod
    def _is_deezer_url(value: str) -> bool:
        raw = value.strip()
        if "://" not in raw:
            return False
        try:
            host = (urlparse(raw).hostname or "").casefold()
        except ValueError:
            return False
        return bool(host) and host.endswith("deezer.com")

    def _search_result_line(self, idx: int, track: Track) -> str:
        artist = (track.artist or "").strip() or self._guess_artist(track.title) or "desconhecido"
        return (
            f"`{idx}` **{track.title}**\n"
            f"`{self._format_duration(track.duration_seconds)}` • artista: `{artist}`"
        )

    async def _play_common(
        self,
        interaction: discord.Interaction,
        link_ou_busca: str,
        *,
        to_front: bool,
        cooldown_key: str,
        action_label: str,
    ) -> None:
        guild = interaction.guild
        self._log_event(
            "command_start",
            cid=self._correlation_id(interaction),
            command=action_label,
            domain=command_domain(action_label),
            guild=guild.id if guild else "dm",
            user=interaction.user.id if interaction.user else "unknown",
        )
        if guild is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return
        if not await self._enforce_control_room_channel(interaction, command_name=action_label):
            return

        user = interaction.user
        member = user if isinstance(user, discord.Member) else None
        user_id = user.id if user else 0
        requester_name = user.display_name if user else "desconhecido"
        voice_channel_id = member.voice.channel.id if member and member.voice and member.voice.channel else 0

        cooldown_left = self._check_cooldown(user_id, cooldown_key, self.play_cooldown_seconds)
        if cooldown_left > 0:
            await self._send_response(interaction, 
                embed=self._warn_embed("Cooldown ativo", f"Aguarde `{cooldown_left:.1f}s` para usar `/{action_label}` novamente."),
                ephemeral=True,
            )
            return

        rate_left = self._check_play_rate_limits(
            guild_id=guild.id,
            user_id=user_id,
            key=action_label,
            channel_id=voice_channel_id,
        )
        if rate_left > 0:
            await self._send_response(interaction, 
                embed=self._warn_embed(
                    "Rate limit",
                    (
                        f"Muitas requisicoes de `/{action_label}` em pouco tempo.\n"
                        f"Tente novamente em `{rate_left:.1f}s`."
                    ),
                ),
                ephemeral=True,
            )
            return

        if not await self._safe_defer(interaction, thinking=True):
            return

        if self.feature_flags.extraction_backpressure_enabled:
            backpressure_left = self._play_backpressure_wait_seconds(query=link_ou_busca, to_front=to_front)
            if backpressure_left > 0:
                await self._send_followup(
                    interaction,
                    embed=self._warn_embed(
                        "Fila interna ocupada",
                        (
                            "O sistema esta processando muitas extracoes agora.\n"
                            f"Tente novamente em `{backpressure_left:.1f}s`."
                        ),
                    ),
                    ephemeral=True,
                )
                self._metrics["play_backpressure_rejected"] += 1
                return

        if self._should_batch_ack_playlist(link_ou_busca, to_front=to_front):
            job = self.playlist_jobs.create(
                guild.id,
                link_ou_busca,
                requester_name,
                total=max(self.playlist_batch_ack_threshold, 1),
            )
            self._schedule_playlist_batch_ack_worker(
                guild=guild,
                query=link_ou_busca,
                requester=requester_name,
                text_channel=interaction.channel,
                job_id=job.job_id,
            )
            await self._send_followup(
                interaction,
                embed=self._ok_embed(
                    "Playlist em background",
                    (
                        f"Job `{job.job_id}` criado.\n"
                        "A playlist esta sendo importada em segundo plano.\n"
                        "Use `/playlist_job` para acompanhar."
                    ),
                ),
            )
            return

        progress_handle = None
        if self.feature_flags.command_service_enabled and self.feature_flags.play_progress_updates:
            progress_handle = await self.command_service.begin_progress(
                interaction,
                title="🎧 Preparando /play",
                description=(
                    f"Etapa: `conexao`\n"
                    f"Consulta: **{link_ou_busca[:120]}**\n"
                    f"{self._separator()}\nIniciando fluxo..."
                ),
                color=self._theme_color("general"),
                embed_factory=self._embed,
                edit_original=self._edit_original_response,
                send_followup=self._send_followup,
            )

        voice_task = asyncio.create_task(self._ensure_voice(interaction))
        t_extract_started = time.monotonic()

        player = await self._get_player(guild.id)
        capacity = max(self.max_queue_size - len(player.snapshot_queue()), 0)
        if capacity <= 0:
            voice_task.cancel()
            await self._send_followup(interaction, 
                embed=self._warn_embed(
                    "Fila lotada",
                    f"A fila atingiu o limite de `{self.max_queue_size}` musicas pendentes.",
                )
            )
            return

        lazy_extract_limit: int | None = None
        can_lazy_extract = self.playlist_incremental_enabled and not to_front and self._looks_like_playlist_query(link_ou_busca)
        if can_lazy_extract:
            lazy_extract_limit = min(max(self.playlist_initial_enqueue, 1), self.max_playlist_import)
        resolved_spotify = False
        prefer_lavalink_catalog = (
            self.lavalink_enabled
            and self._looks_like_direct_url(link_ou_busca)
            and self._is_streaming_catalog_url(link_ou_busca)
            and not self._is_spotify_or_apple_url(link_ou_busca)
            and not self._is_deezer_url(link_ou_busca)
            and not self._is_spotify_collection_url(link_ou_busca)
        )
        if prefer_lavalink_catalog:
            lavalink_limit = max(min(self.max_playlist_import, lazy_extract_limit or self.max_playlist_import), 1)
            lavalink_tracks = await self._search_tracks_lavalink(
                link_ou_busca.strip(),
                requester=requester_name,
                limit=lavalink_limit,
            )
            if lavalink_tracks:
                batch = TrackBatch(
                    tracks=lavalink_tracks,
                    total_items=len(lavalink_tracks),
                    invalid_items=0,
                )
                lowered_link = link_ou_busca.casefold()
                resolved_spotify = "spotify.com" in lowered_link
            else:
                batch, resolved_spotify = await self._extract_batch_with_spotify_fallback(
                    link=link_ou_busca,
                    requester=requester_name,
                    max_items=lazy_extract_limit,
                )
        elif self._can_use_lavalink_fastpath(link_ou_busca, to_front=to_front):
            normalized_link = link_ou_busca.strip()
            resolved_fastpath = await self._search_tracks_lavalink(
                normalized_link,
                requester=requester_name,
                limit=1,
            )
            fastpath_track = resolved_fastpath[0] if resolved_fastpath else None
            batch = TrackBatch(
                tracks=[
                    fastpath_track
                    if fastpath_track is not None
                    else Track(
                        source_query=normalized_link,
                        title=normalized_link,
                        webpage_url=normalized_link,
                        requested_by=requester_name,
                        duration_seconds=None,
                    )
                ],
                total_items=1,
                invalid_items=0,
            )
            if progress_handle is not None:
                await self.command_service.update_progress(
                    progress_handle,
                    title="🎧 Preparando /play",
                    description=(
                        "Etapa: `extracao` (fast-path Lavalink)\n"
                        "URL direta detectada, pulando extrator pesado.\n"
                        f"{self._separator()}\nConectando no canal de voz..."
                    ),
                    color=self._theme_color("general"),
                    embed_factory=self._embed,
                    edit_original=self._edit_original_response,
                )
        else:
            try:
                batch, resolved_spotify = await self._extract_batch_with_spotify_fallback(
                    link=link_ou_busca,
                    requester=requester_name,
                    max_items=lazy_extract_limit,
                )
                if progress_handle is not None:
                    await self.command_service.update_progress(
                        progress_handle,
                        title="🎧 Preparando /play",
                        description=(
                            "Etapa: `extracao`\n"
                            f"Itens detectados: `{batch.total_items}` (invalidas: `{batch.invalid_items}`)\n"
                            f"{self._separator()}\nConectando no canal de voz..."
                        ),
                        color=self._theme_color("general"),
                        embed_factory=self._embed,
                        edit_original=self._edit_original_response,
                    )
            except Exception as exc:
                voice_task.cancel()
                self._metrics["extraction_failures"] += 1
                title, description = self._friendly_extraction_error(exc)
                await self._send_followup(interaction, embed=self._error_embed(title, description))
                return
        self._record_command_stage_latency("play", "extract", (time.monotonic() - t_extract_started) * 1000.0)

        try:
            voice_client = await voice_task
        except Exception as exc:
            LOGGER.exception("Falha em _ensure_voice no guild %s (command=%s)", guild.id, action_label)
            await self._send_followup(
                interaction,
                embed=self._error_embed("Falha ao conectar no canal de voz", f"Detalhe tecnico: `{exc}`"),
                ephemeral=True,
            )
            return
        if voice_client is None:
            await self._send_followup(interaction, 
                embed=self._warn_embed("Canal de voz", "Entre em um canal de voz para usar `/play`."),
                ephemeral=True,
            )
            return

        playlist_window = min(len(batch.tracks), self.max_playlist_import)
        candidate_tracks = batch.tracks[:playlist_window]
        selected_tracks: list[Track] = []
        skipped_by_policy = 0
        selection_limit = capacity
        if self.playlist_incremental_enabled and not to_front and batch.total_items > 1:
            selection_limit = max(min(capacity, max(self.playlist_initial_enqueue, 1)), 1)
        for track in candidate_tracks:
            if len(selected_tracks) >= selection_limit:
                break
            track.requested_by = requester_name
            if self._track_policy_error(guild.id, track):
                skipped_by_policy += 1
                continue
            selected_tracks.append(track)
        skipped_by_import = max(len(batch.tracks) - playlist_window, 0)
        skipped_by_queue = max(len(candidate_tracks) - len(selected_tracks) - skipped_by_policy, 0)
        if not selected_tracks:
            embed = self._warn_embed(
                "Nada adicionado",
                (
                    "Nao entrou nenhuma faixa na fila.\n"
                    f"{self._separator()}\n"
                    f"Detectadas: `{batch.total_items}` | "
                    f"Puladas por moderacao: `{skipped_by_policy}` | "
                    f"Puladas por fila cheia: `{skipped_by_queue}` | "
                    f"Invalidas: `{batch.invalid_items}`"
                ),
            )
            embed.add_field(
                name="Dica",
                value="Se for playlist do YouTube, tente o link completo da playlist (`.../playlist?list=...`).",
                inline=False,
            )
            await self._send_followup(interaction, embed=embed)
            return

        plan = self.scheduler.plan_playlist_enqueue(
            tracks=selected_tracks,
            to_front=to_front,
            priority=QueuePriority.HIGH if to_front else QueuePriority.NORMAL,
            incremental_enabled=self.playlist_incremental_enabled and batch.total_items > 1,
            initial_enqueue=max(self.playlist_initial_enqueue, 1),
        )
        incremental_mode = plan.incremental
        t_queue_apply_started = time.monotonic()
        lock = self._get_lock(guild.id)
        async with lock:
            available_capacity = max(self.max_queue_size - len(player.snapshot_queue()), 0)
            if available_capacity <= 0:
                await self._send_followup(
                    interaction,
                    embed=self._warn_embed(
                        "Fila lotada",
                        f"A fila atingiu o limite de `{self.max_queue_size}` musicas pendentes.",
                    ),
                )
                return
            if not self._is_user_queue_within_limit(player, requester_name, incoming_items=1):
                await self._send_followup(
                    interaction,
                    embed=self._warn_embed(
                        "Limite por usuario",
                        f"Voce atingiu o limite de `{self.max_user_queue_items}` musica(s) pendentes na fila.",
                    ),
                )
                return
            if self.max_user_queue_items > 0:
                user_pending = self._count_user_pending(player, requester_name)
                user_available = max(self.max_user_queue_items - user_pending, 0)
                available_capacity = min(available_capacity, user_available)
                if available_capacity <= 0:
                    await self._send_followup(
                        interaction,
                        embed=self._warn_embed(
                            "Limite por usuario",
                            f"Voce atingiu o limite de `{self.max_user_queue_items}` musica(s) pendentes na fila.",
                        ),
                    )
                    return
            if len(selected_tracks) > available_capacity:
                selected_tracks = selected_tracks[:available_capacity]
                plan = self.scheduler.plan_playlist_enqueue(
                    tracks=selected_tracks,
                    to_front=to_front,
                    priority=QueuePriority.HIGH if to_front else QueuePriority.NORMAL,
                    incremental_enabled=self.playlist_incremental_enabled and batch.total_items > 1,
                    initial_enqueue=max(self.playlist_initial_enqueue, 1),
                )
            skipped_by_queue = max(len(candidate_tracks) - len(selected_tracks) - skipped_by_policy, 0)

            if plan.incremental:
                initial_tracks = list(plan.immediate)
                remaining_tracks = candidate_tracks
                for track in initial_tracks:
                    await self.queue_service.enqueue(player, track)
                initial_keys = {self._track_key(track) for track in initial_tracks}
                remaining_tracks = [track for track in remaining_tracks if self._track_key(track) not in initial_keys]
                full_playlist_pending = self._playlist_has_pending_items(
                    query=link_ou_busca,
                    batch=batch,
                    extraction_limit=lazy_extract_limit,
                )
                if full_playlist_pending:
                    job_id = None
                    if self.feature_flags.playlist_jobs_enabled:
                        job = self.playlist_jobs.create(
                            guild.id,
                            link_ou_busca,
                            requester_name,
                            total=max(batch.total_items - len(initial_tracks), 0),
                        )
                        job_id = job.job_id
                    self._schedule_lazy_playlist_resolve(
                        guild=guild,
                        query=link_ou_busca,
                        requester=requester_name,
                        initial_tracks=initial_tracks,
                        text_channel=interaction.channel,
                        job_id=job_id,
                    )
                else:
                    job_id = None
                    if self.feature_flags.playlist_jobs_enabled:
                        job = self.playlist_jobs.create(
                            guild.id,
                            link_ou_busca,
                            requester_name,
                            total=len(remaining_tracks),
                        )
                        job_id = job.job_id
                    self._schedule_incremental_enqueue(guild, remaining_tracks, interaction.channel, job_id=job_id)
                queued_now = len(initial_tracks)
                queued_later = max(batch.total_items - len(initial_tracks), 0) if full_playlist_pending else max(len(remaining_tracks), 0)
            else:
                if plan.to_front:
                    self.queue_service.enqueue_front_many(player, selected_tracks)
                else:
                    await self.queue_service.enqueue_many(player, selected_tracks)
                queued_now = len(selected_tracks)
                queued_later = 0
            await self._persist_queue_state(guild.id, player)
        self._record_command_stage_latency("play", "queue_apply", (time.monotonic() - t_queue_apply_started) * 1000.0)
        await self._record_queue_event(
            guild.id,
            "play_enqueue",
            query=link_ou_busca,
            to_front=to_front,
            queued_now=queued_now,
            queued_later=queued_later,
            total_detected=batch.total_items,
            skipped=(batch.invalid_items + skipped_by_policy + skipped_by_queue + skipped_by_import),
        )
        if progress_handle is not None:
            await self.command_service.update_progress(
                progress_handle,
                title="🎧 Finalizando /play",
                description=(
                    f"Etapa: `fila`\n"
                    f"Adicionadas agora: `{queued_now}`\n"
                    f"Pendentes em background: `{queued_later}`\n"
                    f"{self._separator()}\nIniciando playback..."
                ),
                color=self._theme_color("playback"),
                embed_factory=self._embed,
                edit_original=self._edit_original_response,
            )
        self._schedule_prefetch_next(guild.id, player)
        self._record_query(guild.id, link_ou_busca)
        if queued_now == 1 and queued_later == 0 and batch.total_items == 1 and batch.invalid_items == 0:
            only_track = selected_tracks[0]
            artist = (only_track.artist or "").strip() or self._guess_artist(only_track.title) or "desconhecido"
            embed = self._ok_embed(
                (
                    "Musica adicionada (via Spotify)"
                    if resolved_spotify and not to_front
                    else "Musica priorizada (via Spotify)"
                    if resolved_spotify and to_front
                    else "Musica adicionada"
                    if not to_front
                    else "Musica priorizada"
                ),
                (
                    f"**{only_track.title}**\n"
                    f"`{self._format_duration(only_track.duration_seconds)}` • artista: `{artist}` • pedido por `{only_track.requested_by}`"
                ),
            )
        else:
            queued = len(selected_tracks)
            skipped = skipped_by_queue + batch.invalid_items
            embed = self._ok_embed(
                "Playlist em importacao"
                if incremental_mode
                else "Playlist processada",
                "Importacao incremental iniciada."
                if incremental_mode
                else "Importacao concluida com sucesso.",
            )
            embed.add_field(name="✅ Adicionadas agora", value=f"`{queued_now}`", inline=True)
            if incremental_mode:
                embed.add_field(name="⏳ Em background", value=f"`{queued_later}`", inline=True)
                if self.feature_flags.playlist_jobs_enabled:
                    latest_job = self.playlist_jobs.latest(guild.id)
                    if latest_job is not None:
                        embed.add_field(name="🧰 Job", value=f"`{latest_job.job_id}`", inline=True)
            else:
                embed.add_field(name="✅ Adicionadas", value=f"`{queued}`", inline=True)
            embed.add_field(name="⛔ Puladas", value=f"`{skipped + skipped_by_import + skipped_by_policy}`", inline=True)
            embed.add_field(name="🎯 Origem", value="`Spotify -> YouTube`" if resolved_spotify else "`link/busca`", inline=True)
            embed.add_field(
                name="Detalhes",
                value=(
                    f"Limite de import: `{skipped_by_import}`\n"
                    f"Fila cheia: `{skipped_by_queue}`\n"
                    f"Moderacao: `{skipped_by_policy}`\n"
                    f"Invalidas: `{batch.invalid_items}`"
                ),
                inline=False,
            )
            if selected_tracks:
                embed.add_field(name="Primeira faixa", value=f"**{selected_tracks[0].title}**", inline=False)
            embed.set_footer(
                text=(
                    f"Total detectado: {batch.total_items} | "
                    f"Limite por comando: {self.max_playlist_import} | "
                    f"Total pulado: {skipped + skipped_by_import + skipped_by_policy}"
                )
            )
        await self._send_followup(interaction, embed=embed)
        # Remove o card de progresso ("Preparando/Finalizando /play") rapidamente.
        if progress_handle is not None:
            self._delete_original_response_later(interaction, delay_seconds=3.0)
        try:
            await asyncio.wait_for(self._start_next_if_needed(guild, interaction.channel), timeout=20.0)
        except asyncio.TimeoutError:
            LOGGER.warning("Timeout iniciando playback no guild %s", guild.id)
        except Exception:
            LOGGER.exception("Falha ao iniciar playback no guild %s", guild.id)

        # Guard-rail pos-/play em background: evita bloquear resposta do comando
        # e so tenta recover quando realmente ha fila pendente sem audio.
        async def post_play_guardrail() -> None:
            voice_client_after = guild.voice_client
            if not self._is_voice_connected(voice_client_after):
                return
            await asyncio.sleep(2.5)
            voice_client_after = guild.voice_client
            if not self._is_voice_connected(voice_client_after):
                return
            if self._is_voice_playing(voice_client_after) or self._is_voice_paused(voice_client_after):
                return
            try:
                player_now = await self._get_player(guild.id)
            except Exception:
                return
            if player_now.current is None and player_now.queue.empty():
                return
            try:
                await asyncio.wait_for(
                    self._recover_playback_after_reconnect(guild, interaction.channel),
                    timeout=12.0,
                )
            except Exception:
                LOGGER.exception("Falha no recover playback pos-/play no guild %s", guild.id)

        self.bot.loop.create_task(post_play_guardrail())

    @app_commands.command(name="play", description="Adiciona um link (ou busca) para tocar no canal de voz.")
    @app_commands.describe(link_ou_busca="URL ou termo de busca")
    @app_commands.autocomplete(link_ou_busca=_play_autocomplete_proxy)
    async def play(self, interaction: discord.Interaction, link_ou_busca: str) -> None:
        await self._play_common(
            interaction,
            link_ou_busca,
            to_front=False,
            cooldown_key="play",
            action_label="play",
        )

    @app_commands.command(name="playnext", description="Adiciona uma musica/playlist para tocar em seguida.")
    @app_commands.describe(link_ou_busca="URL ou termo de busca")
    @app_commands.autocomplete(link_ou_busca=_play_autocomplete_proxy)
    async def playnext(self, interaction: discord.Interaction, link_ou_busca: str) -> None:
        await self._play_common(
            interaction,
            link_ou_busca,
            to_front=True,
            cooldown_key="playnext",
            action_label="playnext",
        )

    @app_commands.command(name="search", description="Busca musicas e deixa escolher qual adicionar na fila.")
    @app_commands.describe(consulta="Termo de busca")
    @app_commands.autocomplete(consulta=_search_autocomplete_proxy)
    async def search(self, interaction: discord.Interaction, consulta: str) -> None:
        guild = interaction.guild
        if guild is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return
        if not await self._enforce_control_room_channel(interaction, command_name="search"):
            return

        cooldown_left = self._check_cooldown(
            interaction.user.id if interaction.user else 0,
            "search",
            self.play_cooldown_seconds,
        )
        if cooldown_left > 0:
            await self._send_response(interaction, 
                embed=self._warn_embed("Cooldown ativo", f"Aguarde `{cooldown_left:.1f}s` para usar `/search` novamente."),
                ephemeral=True,
            )
            return
        rate_left = self._check_play_rate_limits(
            guild_id=guild.id,
            user_id=interaction.user.id if interaction.user else 0,
            key="search",
            channel_id=interaction.user.voice.channel.id if isinstance(interaction.user, discord.Member) and interaction.user.voice and interaction.user.voice.channel else 0,
        )
        if rate_left > 0:
            await self._send_response(
                interaction,
                embed=self._warn_embed("Rate limit", f"Muitas requisicoes de `/search`. Tente novamente em `{rate_left:.1f}s`."),
                ephemeral=True,
            )
            return

        loading_embed = self._embed(
            "🔎 Buscando",
            f"Consulta: **{consulta}**\n{self._separator()}\nPreparando resultados...",
            color=self._theme_color("general"),
        )
        if interaction.response.is_done():
            if not await self._send_followup(interaction, embed=loading_embed, ephemeral=True):
                return
        else:
            try:
                await interaction.response.send_message(embed=loading_embed, ephemeral=True)
            except discord.InteractionResponded:
                if not await self._send_followup(interaction, embed=loading_embed, ephemeral=True):
                    return
            except discord.NotFound:
                LOGGER.warning("Interaction expirada antes de responder /search (cid=%s)", self._correlation_id(interaction))
                return
            except discord.HTTPException as exc:
                if getattr(exc, "code", None) == 10062:
                    LOGGER.warning("Unknown interaction em /search (cid=%s)", self._correlation_id(interaction))
                    return
                raise

        self._record_query(guild.id, consulta)
        requester = interaction.user.display_name if interaction.user else "desconhecido"
        user_id = interaction.user.id if interaction.user else 0
        effective_limit = self._effective_search_limit()
        normalized_query = self._normalize_search_query(consulta)
        user_cache_key = (guild.id, user_id, normalized_query, effective_limit)
        guild_cache_key = (guild.id, 0, normalized_query, effective_limit)
        results, stale = self._cache_get_search(user_cache_key, allow_stale=True)
        cache_scope = "user"
        if results is None:
            results, stale = self._cache_get_search(guild_cache_key, allow_stale=True)
            cache_scope = "guild"
        if results is not None:
            display_query = consulta
            if self._looks_like_direct_url(consulta) and results:
                lead = results[0]
                lead_artist = (lead.artist or "").strip() or self._guess_artist(lead.title) or "desconhecido"
                display_query = f"{lead.title} - {lead_artist}"
            if stale:
                self._schedule_search_refresh(user_cache_key, consulta, requester, effective_limit)
                self._schedule_search_refresh(guild_cache_key, consulta, "guild-cache", effective_limit)
            description = "\n".join(
                self._search_result_line(idx + 1, track)
                for idx, track in enumerate(results)
            )
            embed = self._embed(
                "🔎 Resultados da Busca",
                f"Consulta: **{display_query}**\n{self._separator()}\n{description}",
                color=self._theme_color("general"),
            )
            footer = "Resultados em cache"
            if stale:
                footer = f"Resultados em cache {cache_scope}; atualizando em background..."
            embed.set_footer(text=footer)
            view = SearchView(self, author_id=interaction.user.id if interaction.user else 0, tracks=results)
            if not await self._edit_original_response(interaction, embed=embed, view=view):
                await self._send_followup(interaction, embed=embed, view=view, ephemeral=True)
            return

        try:
            results = await self._search_tracks_guarded(
                consulta,
                requester=requester,
                limit=effective_limit,
                guild_id=guild.id,
                user_id=user_id,
            )
            self._cache_put_search(user_cache_key, results)
            self._cache_put_search(guild_cache_key, results)
        except Exception as exc:
            self._metrics["extraction_failures"] += 1
            message = str(exc).strip()
            if "temporariamente indisponivel" in message.casefold():
                message = f"{message}\n\n`codigo: ERR_PROVIDER_UNAVAILABLE`"
            embed = self._error_embed("Falha na busca", message)
            if not await self._edit_original_response(interaction, embed=embed, view=None):
                await self._send_followup(interaction, embed=embed, ephemeral=True)
            return

        if not results:
            embed = self._warn_embed("Sem resultados", "Nao encontrei resultados para essa busca.")
            if not await self._edit_original_response(interaction, embed=embed, view=None):
                await self._send_followup(interaction, embed=embed, ephemeral=True)
            return

        display_query = consulta
        if self._looks_like_direct_url(consulta) and results:
            lead = results[0]
            lead_artist = (lead.artist or "").strip() or self._guess_artist(lead.title) or "desconhecido"
            display_query = f"{lead.title} - {lead_artist}"

        description = "\n".join(
            self._search_result_line(idx + 1, track)
            for idx, track in enumerate(results)
        )
        embed = self._embed(
            "🔎 Resultados da Busca",
            f"Consulta: **{display_query}**\n{self._separator()}\n{description}",
            color=self._theme_color("general"),
        )
        embed.set_footer(text="Selecione no menu abaixo para adicionar na fila.")
        view = SearchView(self, author_id=interaction.user.id if interaction.user else 0, tracks=results)
        if not await self._edit_original_response(interaction, embed=embed, view=view):
            await self._send_followup(interaction, embed=embed, view=view, ephemeral=True)
