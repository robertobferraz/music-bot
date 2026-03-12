from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

import discord

from botmusica.music.player import FILTERS, GuildPlayer, Track
from botmusica.music.services.playback_scheduler import QueuePriority

if TYPE_CHECKING:
    from botmusica.music.cog import MusicCog


class HelpCategorySelect(discord.ui.Select):
    def __init__(self, cog: MusicCog, author_id: int, *, initial: str = "geral") -> None:
        self.cog = cog
        self.author_id = author_id
        options = [
            discord.SelectOption(label="📘 Geral", value="geral", description="Inicio rapido e comandos basicos"),
            discord.SelectOption(label="🎚️ Reproducao", value="reproducao", description="Controles de playback"),
            discord.SelectOption(label="📜 Fila", value="fila", description="Organizacao da fila"),
            discord.SelectOption(label="🛡️ Administracao", value="administracao", description="Comandos sensiveis"),
        ]
        super().__init__(
            placeholder="Escolha uma categoria de comandos",
            min_values=1,
            max_values=1,
            options=options,
        )
        self._mark_default(initial)

    def _mark_default(self, selected: str) -> None:
        for option in self.options:
            option.default = option.value == selected

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user is None or interaction.user.id != self.author_id:
            await interaction.response.send_message("🔒 Este menu pertence a quem abriu o `/help`.", ephemeral=True)
            return

        category = self.values[0]
        self._mark_default(category)
        embed = self.cog._build_help_embed(category)
        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpView(discord.ui.View):
    def __init__(self, cog: MusicCog, author_id: int, *, initial: str = "geral") -> None:
        super().__init__(timeout=180)
        self.author_id = author_id
        self.add_item(HelpCategorySelect(cog, author_id, initial=initial))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user is None or interaction.user.id != self.author_id:
            await interaction.response.send_message("🔒 Este menu pertence a quem abriu o `/help`.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True


class SearchResultSelect(discord.ui.Select):
    def __init__(self, cog: MusicCog, author_id: int, tracks: list[Track]) -> None:
        self.cog = cog
        self.author_id = author_id
        self.tracks = tracks

        options = [
            discord.SelectOption(
                label=f"{idx + 1}. {track.title[:90]}",
                value=str(idx),
                description=f"Duracao: {cog._format_duration(track.duration_seconds)}",
            )
            for idx, track in enumerate(tracks[:10])
        ]
        super().__init__(
            placeholder="Escolha uma musica para adicionar na fila",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user is None or interaction.user.id != self.author_id:
            await interaction.response.send_message("🔒 Este menu pertence a quem abriu o `/search`.", ephemeral=True)
            return

        index = int(self.values[0])
        track = self.tracks[index]
        await self.cog._enqueue_selected_track(interaction, track)
        for item in self.view.children:
            item.disabled = True
        if interaction.message:
            try:
                await interaction.message.edit(view=self.view)
            except discord.NotFound:
                # Mensagem pode ter sido removida por auto-delete entre o clique e o edit.
                return
            except discord.HTTPException:
                # Falhas transientes de API nao devem quebrar o callback apos enqueue.
                return


class SearchView(discord.ui.View):
    def __init__(self, cog: MusicCog, author_id: int, tracks: list[Track]) -> None:
        super().__init__(timeout=120)
        self.author_id = author_id
        self.add_item(SearchResultSelect(cog, author_id, tracks))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user is None or interaction.user.id != self.author_id:
            await interaction.response.send_message("🔒 Este menu pertence a quem abriu o `/search`.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True


class QueueView(discord.ui.View):
    def __init__(self, cog: MusicCog, author_id: int, player: GuildPlayer, items: list[Track], *, initial_page: int = 0) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.author_id = author_id
        self.player = player
        self.items = items
        self.total_pages = max(math.ceil(len(items) / 10), 1)
        self.page = initial_page
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        last_page = max(self.total_pages - 1, 0)
        self.prev_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= last_page

    async def _render(self, interaction: discord.Interaction) -> None:
        embed = self.cog._build_queue_embed(player=self.player, items=self.items, page=self.page)
        self._sync_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user is None or interaction.user.id != self.author_id:
            await interaction.response.send_message("🔒 Este menu pertence a quem abriu o `/queue`.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="◀️ Anterior", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if self.page > 0:
            self.page -= 1
        await self._render(interaction)

    @discord.ui.button(label="Proxima ▶️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if self.page < max(self.total_pages - 1, 0):
            self.page += 1
        await self._render(interaction)


class QueueSwapSelect(discord.ui.Select):
    def __init__(self, cog: MusicCog, author_id: int, guild_id: int, items: list[Track]) -> None:
        self.cog = cog
        self.author_id = author_id
        self.guild_id = guild_id
        options = [
            discord.SelectOption(
                label=f"{idx}. {track.title[:80]}",
                value=str(idx),
                description=f"{cog._format_duration(track.duration_seconds)} • {track.requested_by[:40]}",
            )
            for idx, track in enumerate(items[:25], start=1)
        ]
        super().__init__(
            placeholder="Escolha uma faixa da fila para tocar agora",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user is None or interaction.user.id != self.author_id:
            await interaction.response.send_message("🔒 Este menu pertence a quem abriu a troca rapida.", ephemeral=True)
            return
        if not await self.cog._require_control_permissions(interaction):
            return
        if not await self.cog._require_same_voice_channel(interaction):
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                embed=self.cog._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        voice_client = guild.voice_client
        if not self.cog._is_voice_connected(voice_client):
            await interaction.response.send_message(
                embed=self.cog._warn_embed("Sem conexao", "O bot nao esta conectado no canal de voz."),
                ephemeral=True,
            )
            return

        player = await self.cog._get_player(guild.id)
        selected_position = int(self.values[0])
        lock = self.cog._get_lock(guild.id)
        async with lock:
            try:
                picked = self.cog.queue_service.remove(player, selected_position)
            except IndexError:
                await interaction.response.send_message(
                    embed=self.cog._warn_embed("Fila atualizada", "A fila mudou. Abra o seletor novamente."),
                    ephemeral=True,
                )
                return
            self.cog.queue_service.enqueue_front(player, picked)
            player.suppress_after_playback = True
            await self.cog._persist_queue_state(guild.id, player)
        await self.cog._stop_voice(voice_client)
        await interaction.response.send_message(
            embed=self.cog._ok_embed("Troca aplicada", f"Tocando agora: **{picked.title}**"),
            ephemeral=True,
        )


class QueueSwapView(discord.ui.View):
    def __init__(self, cog: MusicCog, author_id: int, guild_id: int, items: list[Track]) -> None:
        super().__init__(timeout=120)
        self.author_id = author_id
        self.add_item(QueueSwapSelect(cog, author_id, guild_id, items))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user is None or interaction.user.id != self.author_id:
            await interaction.response.send_message("🔒 Este menu pertence a quem abriu a troca rapida.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True


class NowPlayingView(discord.ui.View):
    def __init__(self, cog: MusicCog, guild_id: int, author_id: int) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.guild_id = guild_id
        self.author_id = author_id
        if not getattr(cog.feature_flags, "nowplaying_compact_enabled", True):
            self.remove_item(self.compact_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.author_id and (interaction.user is None or interaction.user.id != self.author_id):
            await interaction.response.send_message("🔒 Este painel pertence a quem usou `/nowplaying`.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True

    async def _check_action_cooldown(self, interaction: discord.Interaction, action: str) -> bool:
        guild = interaction.guild
        user = interaction.user
        if guild is None or user is None:
            return True
        debounced_left = self.cog._button_action_debounced(guild.id, action)
        if debounced_left > 0:
            await interaction.response.send_message(
                embed=self.cog._warn_embed("Aguarde", f"Acao muito rapida. Tente em `{debounced_left:.1f}s`."),
                ephemeral=True,
            )
            return False
        left = self.cog._check_button_cooldown(guild_id=guild.id, user_id=user.id, action=action)
        if left > 0:
            await interaction.response.send_message(
                embed=self.cog._warn_embed("Aguarde", f"Espere `{left:.1f}s` antes de usar esse botao novamente."),
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="⏸️", style=discord.ButtonStyle.secondary)
    async def pause_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if not await self._check_action_cooldown(interaction, "np_pause"):
            return
        if not await self.cog._require_control_permissions(interaction):
            return
        if not await self.cog._require_same_voice_channel(interaction):
            return
        guild = interaction.guild
        if guild is None or guild.voice_client is None or not self.cog._is_voice_playing(guild.voice_client):
            await interaction.response.send_message(embed=self.cog._warn_embed("Sem reproducao", "Nada esta tocando agora."), ephemeral=True)
            return
        player = await self.cog._get_player(guild.id)
        await self.cog._pause_voice(guild.voice_client)
        if player.pause_started_at is None:
            player.pause_started_at = time.monotonic()
        await interaction.response.send_message(embed=self.cog._ok_embed("Pause", "Reproducao pausada."), ephemeral=True)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.success)
    async def resume_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if not await self._check_action_cooldown(interaction, "np_resume"):
            return
        if not await self.cog._require_control_permissions(interaction):
            return
        if not await self.cog._require_same_voice_channel(interaction):
            return
        guild = interaction.guild
        if guild is None or guild.voice_client is None or not self.cog._is_voice_paused(guild.voice_client):
            await interaction.response.send_message(embed=self.cog._warn_embed("Nao pausada", "A musica nao esta pausada."), ephemeral=True)
            return
        player = await self.cog._get_player(guild.id)
        if player.pause_started_at is not None:
            player.paused_accumulated_seconds += max(time.monotonic() - player.pause_started_at, 0.0)
            player.pause_started_at = None
        await self.cog._resume_voice(guild.voice_client)
        await interaction.response.send_message(embed=self.cog._ok_embed("Resume", "Reproducao retomada."), ephemeral=True)

    @discord.ui.button(label="⏭️", style=discord.ButtonStyle.primary)
    async def skip_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if not await self._check_action_cooldown(interaction, "np_skip"):
            return
        if not await self.cog._require_same_voice_channel(interaction):
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(embed=self.cog._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."), ephemeral=True)
            return
        voice_client = guild.voice_client
        if voice_client is None or not self.cog._is_voice_playing(voice_client):
            await interaction.response.send_message(embed=self.cog._warn_embed("Sem reproducao", "Nao ha musica tocando agora."), ephemeral=True)
            return
        player = await self.cog._get_player(guild.id)
        if not self.cog._is_control_admin(interaction):
            approved = await self.cog._try_vote_action(interaction, "skip")
            if not approved:
                return
        else:
            self.cog._votes.pop((guild.id, "skip"), None)
            await self.cog.store.delete_vote_state(guild.id, "skip")
        player.suppress_after_playback = True
        await self.cog._stop_voice(voice_client)
        await interaction.response.send_message(embed=self.cog._ok_embed("Skip", "Musica pulada."), ephemeral=True)

    @discord.ui.button(label="📜", style=discord.ButtonStyle.secondary)
    async def queue_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if not await self._check_action_cooldown(interaction, "np_queue"):
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(embed=self.cog._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."), ephemeral=True)
            return
        player = await self.cog._get_player(guild.id)
        items = player.snapshot_queue()
        embed = self.cog._build_queue_embed(player=player, items=items, page=0)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🔀 Trocar", style=discord.ButtonStyle.primary)
    async def swap_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if not await self._check_action_cooldown(interaction, "np_swap"):
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                embed=self.cog._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return
        player = await self.cog._get_player(guild.id)
        items = player.snapshot_queue()
        if not items:
            await interaction.response.send_message(
                embed=self.cog._warn_embed("Fila vazia", "Nao ha faixas pendentes para trocar."),
                ephemeral=True,
            )
            return
        author_id = interaction.user.id if interaction.user else 0
        view = QueueSwapView(self.cog, author_id=author_id, guild_id=guild.id, items=items)
        await interaction.response.send_message(
            embed=self.cog._embed(
                "🔀 Troca Rapida",
                "Selecione uma faixa da fila para tocar imediatamente.",
                color=self.cog._theme_color("queue"),
            ),
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="🪄 Compact", style=discord.ButtonStyle.secondary)
    async def compact_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                embed=self.cog._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return
        enabled = await self.cog._toggle_nowplaying_compact(guild.id)
        player = await self.cog._get_player(guild.id)
        if player.current is not None:
            await self.cog._upsert_nowplaying_message(guild, interaction.channel)
        await interaction.response.send_message(
            embed=self.cog._ok_embed(
                "NowPlaying visual",
                "Modo compacto ativado." if enabled else "Modo compacto desativado.",
            ),
            ephemeral=True,
        )


class ControlRoomPlayModal(discord.ui.Modal, title="Adicionar musica"):
    def __init__(self, cog: MusicCog, guild_id: int) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.guild_id = guild_id
        self.link_ou_busca = discord.ui.TextInput(
            label="Link ou busca",
            placeholder="Cole URL (YouTube/Spotify/Apple) ou digite a busca",
            max_length=180,
            required=True,
        )
        self.add_item(self.link_ou_busca)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None or guild.id != self.guild_id:
            await interaction.response.send_message(
                embed=self.cog._warn_embed("Comando indisponivel", "Use este painel no servidor correto."),
                ephemeral=True,
            )
            return
        if not await self.cog._safe_defer(interaction, thinking=True, ephemeral=True):
            return
        voice_client = await self.cog._ensure_voice(interaction)
        if voice_client is None:
            await self.cog._send_followup(
                interaction,
                embed=self.cog._warn_embed("Canal de voz", "Entre em um canal de voz para adicionar musica."),
                ephemeral=True,
            )
            return

        player = await self.cog._get_player(guild.id)
        if not self.cog._has_queue_capacity(player):
            await self.cog._send_followup(
                interaction,
                embed=self.cog._warn_embed("Fila lotada", f"A fila atingiu o limite de `{self.cog.max_queue_size}`."),
                ephemeral=True,
            )
            return
        query = str(self.link_ou_busca.value).strip()
        requester = interaction.user.display_name if interaction.user else "desconhecido"
        lazy_extract_limit: int | None = None
        is_spotify_collection = "spotify.com/playlist/" in query.casefold() or "spotify.com/album/" in query.casefold()
        can_lazy_extract = self.cog.playlist_incremental_enabled and self.cog._looks_like_playlist_query(query) and not is_spotify_collection
        if can_lazy_extract:
            lazy_extract_limit = min(max(self.cog.playlist_initial_enqueue, 1), self.cog.max_playlist_import)
        try:
            batch, resolved_spotify = await self.cog._extract_batch_with_spotify_fallback(
                link=query,
                requester=requester,
                max_items=lazy_extract_limit,
            )
        except Exception as exc:
            title, description = self.cog._friendly_extraction_error(exc)
            await self.cog._send_followup(interaction, embed=self.cog._error_embed(title, description), ephemeral=True)
            return

        capacity = max(self.cog.max_queue_size - len(player.snapshot_queue()), 0)
        playlist_window = min(len(batch.tracks), self.cog.max_playlist_import)
        candidate_tracks = batch.tracks[:playlist_window]
        selected_tracks: list[Track] = []
        skipped_by_policy = 0
        selection_limit = capacity
        for track in candidate_tracks:
            if len(selected_tracks) >= selection_limit:
                break
            track.requested_by = requester
            reason = self.cog._track_policy_error(guild.id, track)
            if reason:
                skipped_by_policy += 1
                continue
            selected_tracks.append(track)
        skipped_by_import = max(len(batch.tracks) - playlist_window, 0)
        skipped_by_queue = max(len(candidate_tracks) - len(selected_tracks) - skipped_by_policy, 0)
        if not selected_tracks:
            await self.cog._send_followup(
                interaction,
                embed=self.cog._warn_embed(
                    "Nada adicionado",
                    (
                        "Nao entrou nenhuma faixa na fila.\n"
                        f"{self.cog._separator()}\n"
                        f"Detectadas: `{batch.total_items}` | "
                        f"Puladas por moderacao: `{skipped_by_policy}` | "
                        f"Puladas por fila cheia: `{skipped_by_queue}` | "
                        f"Invalidas: `{batch.invalid_items}`"
                    ),
                ),
                ephemeral=True,
            )
            return

        lock = self.cog._get_lock(guild.id)
        async with lock:
            await self.cog._drop_restored_queue_if_idle(guild.id, player, reason="control_room_play")
            if not self.cog._has_queue_capacity(player):
                await self.cog._send_followup(
                    interaction,
                    embed=self.cog._warn_embed("Fila lotada", f"A fila atingiu o limite de `{self.cog.max_queue_size}`."),
                    ephemeral=True,
                )
                return
            if not self.cog._is_user_queue_within_limit(player, requester, incoming_items=1):
                await self.cog._send_followup(
                    interaction,
                    embed=self.cog._warn_embed(
                        "Limite por usuario",
                        f"Voce atingiu o limite de `{self.cog.max_user_queue_items}` musica(s) pendentes.",
                    ),
                    ephemeral=True,
                )
                return

            plan = self.cog.scheduler.plan_playlist_enqueue(
                tracks=selected_tracks,
                to_front=False,
                priority=QueuePriority.NORMAL,
                incremental_enabled=self.cog.playlist_incremental_enabled and batch.total_items > 1,
                initial_enqueue=max(self.cog.playlist_initial_enqueue, 1),
            )

            full_playlist_pending = batch.total_items > len(batch.tracks)
            if plan.incremental:
                initial_tracks = list(plan.immediate)
                remaining_tracks = candidate_tracks
                for track in initial_tracks:
                    await self.cog.queue_service.enqueue(player, track)
                initial_keys = {self.cog._track_key(track) for track in initial_tracks}
                remaining_tracks = [track for track in remaining_tracks if self.cog._track_key(track) not in initial_keys]
                if full_playlist_pending:
                    job_id = None
                    if self.cog.feature_flags.playlist_jobs_enabled:
                        job = self.cog.playlist_jobs.create(
                            guild.id,
                            query,
                            requester,
                            total=max(batch.total_items - len(initial_tracks), 0),
                        )
                        job_id = job.job_id
                    self.cog._schedule_lazy_playlist_resolve(
                        guild=guild,
                        query=query,
                        requester=requester,
                        initial_tracks=initial_tracks,
                        text_channel=interaction.channel,
                        job_id=job_id,
                    )
                else:
                    job_id = None
                    if self.cog.feature_flags.playlist_jobs_enabled:
                        job = self.cog.playlist_jobs.create(
                            guild.id,
                            query,
                            requester,
                            total=len(remaining_tracks),
                        )
                        job_id = job.job_id
                    self.cog._schedule_incremental_enqueue(guild, remaining_tracks, interaction.channel, job_id=job_id)
                queued_now = len(initial_tracks)
                queued_later = (
                    max(batch.total_items - len(initial_tracks), 0)
                    if full_playlist_pending
                    else max(len(remaining_tracks), 0)
                )
            else:
                await self.cog.queue_service.enqueue_many(player, selected_tracks)
                queued_now = len(selected_tracks)
                queued_later = 0
                # Quando a extracao inicial foi limitada (ex.: 10 primeiras),
                # continua a importacao em background igual ao /play.
                if full_playlist_pending and self.cog.playlist_incremental_enabled:
                    job_id = None
                    if self.cog.feature_flags.playlist_jobs_enabled:
                        job = self.cog.playlist_jobs.create(
                            guild.id,
                            query,
                            requester,
                            total=max(batch.total_items - len(selected_tracks), 0),
                        )
                        job_id = job.job_id
                    self.cog._schedule_lazy_playlist_resolve(
                        guild=guild,
                        query=query,
                        requester=requester,
                        initial_tracks=list(selected_tracks),
                        text_channel=interaction.channel,
                        job_id=job_id,
                    )
                    queued_later = max(batch.total_items - len(selected_tracks), 0)
            await self.cog._persist_queue_state(guild.id, player)

        self.cog._schedule_prefetch_next(guild.id, player)
        self.cog._record_query(guild.id, query)
        await self.cog._record_queue_event(
            guild.id,
            "control_room_enqueue",
            title=selected_tracks[0].title if selected_tracks else "playlist",
            requested_by=requester,
            queued_now=queued_now,
            queued_later=queued_later,
            total_detected=batch.total_items,
            skipped=(batch.invalid_items + skipped_by_policy + skipped_by_queue + skipped_by_import),
        )
        if queued_now == 1 and queued_later == 0 and batch.total_items == 1:
            first = selected_tracks[0]
            await self.cog._send_followup(
                interaction,
                embed=self.cog._ok_embed(
                    "Adicionada",
                    (
                        f"**{first.title}** (`{self.cog._format_duration(first.duration_seconds)}`)"
                        + (" • origem: Spotify" if resolved_spotify else "")
                    ),
                ),
                ephemeral=True,
            )
        else:
            embed = self.cog._ok_embed(
                "Playlist em importacao" if queued_later > 0 else "Playlist processada",
                "Importacao incremental iniciada." if queued_later > 0 else "Importacao concluida com sucesso.",
            )
            embed.add_field(name="✅ Adicionadas agora", value=f"`{queued_now}`", inline=True)
            if queued_later > 0:
                embed.add_field(name="⏳ Em background", value=f"`{queued_later}`", inline=True)
            embed.add_field(
                name="⛔ Puladas",
                value=f"`{batch.invalid_items + skipped_by_policy + skipped_by_queue + skipped_by_import}`",
                inline=True,
            )
            embed.add_field(name="🎯 Origem", value="`Spotify -> YouTube`" if resolved_spotify else "`link/busca`", inline=True)
            await self.cog._send_followup(interaction, embed=embed, ephemeral=True)
        await self.cog._start_next_if_needed(guild, interaction.channel)
        await self.cog._refresh_control_room_panel(guild.id)


class DJQueueMoveModal(discord.ui.Modal, title="Mover faixa na fila"):
    def __init__(self, cog: MusicCog, guild_id: int) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.guild_id = guild_id
        self.source_pos = discord.ui.TextInput(
            label="Posicao origem",
            placeholder="Ex.: 8",
            max_length=4,
            required=True,
        )
        self.target_pos = discord.ui.TextInput(
            label="Posicao destino",
            placeholder="Ex.: 2",
            max_length=4,
            required=True,
        )
        self.add_item(self.source_pos)
        self.add_item(self.target_pos)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None or guild.id != self.guild_id:
            await interaction.response.send_message(
                embed=self.cog._warn_embed("Comando indisponivel", "Use este painel no servidor correto."),
                ephemeral=True,
            )
            return
        if not await self.cog._require_control_permissions(interaction):
            return
        if not await self.cog._require_same_voice_channel(interaction):
            return
        try:
            source = int(str(self.source_pos.value).strip())
            target = int(str(self.target_pos.value).strip())
        except ValueError:
            await interaction.response.send_message(
                embed=self.cog._warn_embed("Posicao invalida", "Informe numeros inteiros nas posicoes."),
                ephemeral=True,
            )
            return
        if source < 1 or target < 1:
            await interaction.response.send_message(
                embed=self.cog._warn_embed("Posicao invalida", "As posicoes devem ser maiores que zero."),
                ephemeral=True,
            )
            return
        player = await self.cog._get_player(guild.id)
        lock = self.cog._get_lock(guild.id)
        async with lock:
            try:
                moved = self.cog.queue_service.move(player, source, target)
            except Exception:
                await interaction.response.send_message(
                    embed=self.cog._warn_embed("Falha ao mover", "Posicao fora do intervalo da fila."),
                    ephemeral=True,
                )
                return
            await self.cog._persist_queue_state(guild.id, player)
        actor = interaction.user.display_name if interaction.user else "usuario"
        self.cog._control_room_push_history(guild.id, f"{actor} moveu fila: {source} -> {target} ({moved.title[:48]})")
        await self.cog._refresh_control_room_panel(guild.id)
        await interaction.response.send_message(
            embed=self.cog._ok_embed("Fila atualizada", f"**{moved.title}** movida de `{source}` para `{target}`."),
            ephemeral=True,
        )


class ControlRoomView(discord.ui.View):
    def __init__(self, cog: MusicCog, guild_id: int, *, operator_user_id: int = 0) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.operator_user_id = operator_user_id

    @staticmethod
    def _next_loop_mode(current: str) -> str:
        normalized = (current or "off").strip().casefold()
        if normalized == "off":
            return "track"
        if normalized == "track":
            return "queue"
        return "off"

    @staticmethod
    def _next_filter_mode(current: str) -> str:
        modes = list(FILTERS.keys())
        if not modes:
            return "off"
        normalized = (current or "off").strip().casefold()
        if normalized not in modes:
            return "off"
        idx = modes.index(normalized)
        return modes[(idx + 1) % len(modes)]

    async def _check_cooldown(self, interaction: discord.Interaction, action: str) -> bool:
        guild = interaction.guild
        user = interaction.user
        if guild is None or user is None:
            return True
        debounced_left = self.cog._button_action_debounced(guild.id, action)
        if debounced_left > 0:
            await interaction.response.send_message(
                embed=self.cog._warn_embed("Aguarde", f"Acao muito rapida. Tente em `{debounced_left:.1f}s`."),
                ephemeral=True,
            )
            return False
        return True

    async def _check_operator_lock(self, interaction: discord.Interaction) -> bool:
        guild = interaction.guild
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if guild is None or member is None:
            return True
        if not self.cog.control_room_lock_operator_enabled:
            return True
        operator_id = self.operator_user_id or self.cog._control_room_operator.get(guild.id, 0)
        if operator_id <= 0:
            self.cog._control_room_operator[guild.id] = member.id
            self.operator_user_id = member.id
            return True
        if member.id == operator_id or self.cog._is_control_admin(interaction):
            return True
        await interaction.response.send_message(
            embed=self.cog._warn_embed(
                "Painel bloqueado",
                f"Somente o operador atual (<@{operator_id}>) ou administradores podem usar este painel.",
            ),
            ephemeral=True,
        )
        return False

    async def _refresh_panel(self, guild_id: int) -> None:
        await self.cog._refresh_control_room_panel(guild_id)

    def _push_history(self, guild_id: int, interaction: discord.Interaction, action: str) -> None:
        actor = interaction.user.display_name if interaction.user else "usuario"
        self.cog._control_room_push_history(guild_id, f"{actor} • {action}")

    async def _allow_critical_action(self, interaction: discord.Interaction, action: str) -> bool:
        if self.cog._is_control_admin(interaction):
            return True
        return await self.cog._try_vote_action(interaction, action)

    @discord.ui.button(label="➕ Musica", style=discord.ButtonStyle.primary, custom_id="control_room:add", row=0)
    async def add_music_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if interaction.guild is None or interaction.guild.id != self.guild_id:
            await interaction.response.send_message("Painel invalido para este servidor.", ephemeral=True)
            return
        if not await self._check_cooldown(interaction, "cr_add"):
            return
        if not await self._check_operator_lock(interaction):
            return
        await interaction.response.send_modal(ControlRoomPlayModal(self.cog, self.guild_id))

    @discord.ui.button(label="🔌 Conectar", style=discord.ButtonStyle.success, custom_id="control_room:join", row=0)
    async def join_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            return
        if not await self._check_cooldown(interaction, "cr_join"):
            return
        if not await self._check_operator_lock(interaction):
            return
        async with self.cog._control_room_lock(guild.id):
            if not await self.cog._safe_defer(interaction, thinking=False, ephemeral=True):
                return
            voice_client = await self.cog._ensure_voice(interaction)
            if voice_client is None:
                await self.cog._send_followup(
                    interaction,
                    embed=self.cog._warn_embed("Canal de voz", "Entre em um canal de voz para conectar o bot."),
                    ephemeral=True,
                )
                return
            self._push_history(guild.id, interaction, "conectou o bot no canal de voz")
            await self._refresh_panel(guild.id)
            await self.cog._send_followup(
                interaction,
                embed=self.cog._ok_embed("Conectado", "Bot conectado ao seu canal de voz."),
                ephemeral=True,
            )

    @discord.ui.button(label="⏸️ Pause", style=discord.ButtonStyle.secondary, custom_id="control_room:pause", row=0)
    async def pause_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            return
        if not await self._check_cooldown(interaction, "cr_pause"):
            return
        if not await self._check_operator_lock(interaction):
            return
        async with self.cog._control_room_lock(guild.id):
            if not await self.cog._require_control_permissions(interaction):
                return
            if not await self.cog._require_same_voice_channel(interaction):
                return
            if guild.voice_client is None or not self.cog._is_voice_playing(guild.voice_client):
                await interaction.response.send_message(
                    embed=self.cog._warn_embed("Sem reproducao", "Nada esta tocando agora."),
                    ephemeral=True,
                )
                return
            player = await self.cog._get_player(guild.id)
            await self.cog._pause_voice(guild.voice_client)
            if player.pause_started_at is None:
                player.pause_started_at = time.monotonic()
            self._push_history(guild.id, interaction, "pausou a reproducao")
            await self._refresh_panel(guild.id)
            await interaction.response.send_message(embed=self.cog._ok_embed("Pause", "Reproducao pausada."), ephemeral=True)

    @discord.ui.button(label="▶️ Resume", style=discord.ButtonStyle.success, custom_id="control_room:resume", row=0)
    async def resume_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            return
        if not await self._check_cooldown(interaction, "cr_resume"):
            return
        if not await self._check_operator_lock(interaction):
            return
        async with self.cog._control_room_lock(guild.id):
            if not await self.cog._require_control_permissions(interaction):
                return
            if not await self.cog._require_same_voice_channel(interaction):
                return
            if guild.voice_client is None or not self.cog._is_voice_paused(guild.voice_client):
                await interaction.response.send_message(
                    embed=self.cog._warn_embed("Nao pausada", "A musica nao esta pausada."),
                    ephemeral=True,
                )
                return
            player = await self.cog._get_player(guild.id)
            if player.pause_started_at is not None:
                player.paused_accumulated_seconds += max(time.monotonic() - player.pause_started_at, 0.0)
                player.pause_started_at = None
            await self.cog._resume_voice(guild.voice_client)
            self._push_history(guild.id, interaction, "retomou a reproducao")
            await self._refresh_panel(guild.id)
            await interaction.response.send_message(embed=self.cog._ok_embed("Resume", "Reproducao retomada."), ephemeral=True)

    @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.primary, custom_id="control_room:skip", row=0)
    async def skip_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            return
        if not await self._check_cooldown(interaction, "cr_skip"):
            return
        if not await self._check_operator_lock(interaction):
            return
        async with self.cog._control_room_lock(guild.id):
            if not await self.cog._require_same_voice_channel(interaction):
                return
            voice_client = guild.voice_client
            if voice_client is None or not self.cog._is_voice_playing(voice_client):
                await interaction.response.send_message(
                    embed=self.cog._warn_embed("Sem reproducao", "Nao ha musica tocando agora."),
                    ephemeral=True,
                )
                return
            if not await self._allow_critical_action(interaction, "skip"):
                return
            player = await self.cog._get_player(guild.id)
            player.suppress_after_playback = True
            await self.cog._stop_voice(voice_client)
            self._push_history(guild.id, interaction, "pulou a musica")
            await self._refresh_panel(guild.id)
            await interaction.response.send_message(embed=self.cog._ok_embed("Skip", "Musica pulada."), ephemeral=True)

    @discord.ui.button(label="⏹️ Stop", style=discord.ButtonStyle.danger, custom_id="control_room:stop", row=1)
    async def stop_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            return
        if not await self._check_cooldown(interaction, "cr_stop"):
            return
        if not await self._check_operator_lock(interaction):
            return
        async with self.cog._control_room_lock(guild.id):
            if not await self.cog._require_same_voice_channel(interaction):
                return
            if not await self._allow_critical_action(interaction, "stop"):
                return
            player = await self.cog._get_player(guild.id)
            lock = self.cog._get_lock(guild.id)
            async with lock:
                removed = self.cog.queue_service.clear(player)
                player.current = None
                player.current_started_at = None
                player.pause_started_at = None
                player.paused_accumulated_seconds = 0.0
                player.suppress_after_playback = True
                await self.cog._persist_queue_state(guild.id, player)
            voice_client = guild.voice_client
            if self.cog._is_voice_connected(voice_client):
                await self.cog._stop_voice(voice_client)
            self._push_history(guild.id, interaction, f"parou playback e limpou {len(removed)} item(ns)")
            await self._refresh_panel(guild.id)
            await interaction.response.send_message(
                embed=self.cog._ok_embed("Stop", f"Fila limpa. Removidas {len(removed)} pendentes."),
                ephemeral=True,
            )

    @discord.ui.button(label="🔌 Sair", style=discord.ButtonStyle.danger, custom_id="control_room:disconnect", row=1)
    async def disconnect_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            return
        if not await self._check_cooldown(interaction, "cr_disconnect"):
            return
        if not await self._check_operator_lock(interaction):
            return
        async with self.cog._control_room_lock(guild.id):
            if not await self.cog._require_same_voice_channel(interaction):
                return
            if not await self._allow_critical_action(interaction, "disconnect"):
                return
            voice_client = guild.voice_client
            if not self.cog._is_voice_connected(voice_client):
                await interaction.response.send_message(
                    embed=self.cog._warn_embed("Sem conexao", "O bot nao esta conectado."),
                    ephemeral=True,
                )
                return
            player = await self.cog._get_player(guild.id)
            lock = self.cog._get_lock(guild.id)
            async with lock:
                self.cog.queue_service.clear(player)
                player.current = None
                player.current_started_at = None
                player.pause_started_at = None
                player.paused_accumulated_seconds = 0.0
                player.suppress_after_playback = True
            self.cog._cancel_nowplaying_updater(guild.id)
            await self.cog._persist_queue_state(guild.id, player)
            await self.cog._record_queue_event(guild.id, "control_room_disconnect")
            await self.cog._stop_voice(voice_client)
            self.cog._cancel_idle_timer(guild.id)
            self.cog._cancel_prefetch(guild.id)
            self.cog._mark_voice_reconnect_required(guild.id)
            await voice_client.disconnect(force=True)
            await self.cog._clear_nowplaying_message(guild.id)
            await self.cog._clear_voice_mini_panel(guild.id)
            await self.cog._clear_votes_for_guild(guild.id)
            self.cog.music.remove_player(guild.id)
            self.cog._loaded_settings.discard(guild.id)
            self._push_history(guild.id, interaction, "desconectou o bot da call")
            await self._refresh_panel(guild.id)
            await interaction.response.send_message(
                embed=self.cog._ok_embed("Disconnect", "Desconectado do canal de voz."),
                ephemeral=True,
            )

    @discord.ui.button(label="🔀 Shuffle", style=discord.ButtonStyle.secondary, custom_id="control_room:shuffle", row=1)
    async def shuffle_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            return
        if not await self._check_cooldown(interaction, "cr_shuffle"):
            return
        if not await self._check_operator_lock(interaction):
            return
        async with self.cog._control_room_lock(guild.id):
            if not await self.cog._require_control_permissions(interaction):
                return
            player = await self.cog._get_player(guild.id)
            lock = self.cog._get_lock(guild.id)
            async with lock:
                total = self.cog.queue_service.shuffle(player)
                await self.cog._persist_queue_state(guild.id, player)
            await self.cog._record_queue_event(guild.id, "control_room_shuffle", total=total)
            self._push_history(guild.id, interaction, f"embaralhou a fila ({total})")
            await self._refresh_panel(guild.id)
            await interaction.response.send_message(
                embed=self.cog._ok_embed("Shuffle", f"Fila embaralhada ({total} item(ns))."),
                ephemeral=True,
            )

    @discord.ui.button(label="🔁 Loop", style=discord.ButtonStyle.secondary, custom_id="control_room:loop", row=1)
    async def loop_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            return
        if not await self._check_cooldown(interaction, "cr_loop"):
            return
        if not await self._check_operator_lock(interaction):
            return
        async with self.cog._control_room_lock(guild.id):
            if not await self.cog._require_control_permissions(interaction):
                return
            player = await self.cog._get_player(guild.id)
            player.loop_mode = self._next_loop_mode(player.loop_mode)
            await self.cog._save_player_settings(guild.id, player)
            self._push_history(guild.id, interaction, f"alterou loop para {player.loop_mode}")
            await self._refresh_panel(guild.id)
            await interaction.response.send_message(
                embed=self.cog._ok_embed("Loop atualizado", f"Modo atual: **{player.loop_mode}**."),
                ephemeral=True,
            )

    @discord.ui.button(label="🤖 Autoplay", style=discord.ButtonStyle.secondary, custom_id="control_room:autoplay", row=1)
    async def autoplay_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            return
        if not await self._check_cooldown(interaction, "cr_autoplay"):
            return
        if not await self._check_operator_lock(interaction):
            return
        async with self.cog._control_room_lock(guild.id):
            if not await self.cog._require_control_permissions(interaction):
                return
            player = await self.cog._get_player(guild.id)
            player.autoplay = not player.autoplay
            await self.cog._save_player_settings(guild.id, player)
            self._push_history(guild.id, interaction, f"autoplay {'on' if player.autoplay else 'off'}")
            await self._refresh_panel(guild.id)
            await interaction.response.send_message(
                embed=self.cog._ok_embed("Autoplay", "Ativado." if player.autoplay else "Desativado."),
                ephemeral=True,
            )

    @discord.ui.button(label="🔉 Vol-", style=discord.ButtonStyle.secondary, custom_id="control_room:vol_down", row=2)
    async def volume_down_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            return
        if not await self._check_cooldown(interaction, "cr_vol_down"):
            return
        if not await self._check_operator_lock(interaction):
            return
        async with self.cog._control_room_lock(guild.id):
            if not await self.cog._require_control_permissions(interaction):
                return
            player = await self.cog._get_player(guild.id)
            current_percent = int(round(player.volume * 100))
            next_percent = max(1, min(200, current_percent - 10))
            normalized = next_percent / 100.0
            player.volume = normalized
            voice_client = guild.voice_client
            if self.cog._is_voice_connected(voice_client):
                await self.cog._set_voice_volume(voice_client, normalized)
            await self.cog._save_player_settings(guild.id, player)
            self._push_history(guild.id, interaction, f"volume {next_percent}%")
            await self._refresh_panel(guild.id)
            await interaction.response.send_message(
                embed=self.cog._ok_embed("Volume atualizado", f"Volume ajustado para **{next_percent}%**."),
                ephemeral=True,
            )

    @discord.ui.button(label="🔊 Vol+", style=discord.ButtonStyle.secondary, custom_id="control_room:vol_up", row=2)
    async def volume_up_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            return
        if not await self._check_cooldown(interaction, "cr_vol_up"):
            return
        if not await self._check_operator_lock(interaction):
            return
        async with self.cog._control_room_lock(guild.id):
            if not await self.cog._require_control_permissions(interaction):
                return
            player = await self.cog._get_player(guild.id)
            current_percent = int(round(player.volume * 100))
            next_percent = max(1, min(200, current_percent + 10))
            normalized = next_percent / 100.0
            player.volume = normalized
            voice_client = guild.voice_client
            if self.cog._is_voice_connected(voice_client):
                await self.cog._set_voice_volume(voice_client, normalized)
            await self.cog._save_player_settings(guild.id, player)
            self._push_history(guild.id, interaction, f"volume {next_percent}%")
            await self._refresh_panel(guild.id)
            await interaction.response.send_message(
                embed=self.cog._ok_embed("Volume atualizado", f"Volume ajustado para **{next_percent}%**."),
                ephemeral=True,
            )

    @discord.ui.button(label="🎚️ Filtro", style=discord.ButtonStyle.secondary, custom_id="control_room:filter", row=2)
    async def filter_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            return
        if not await self._check_cooldown(interaction, "cr_filter"):
            return
        if not await self._check_operator_lock(interaction):
            return
        async with self.cog._control_room_lock(guild.id):
            if not await self.cog._require_control_permissions(interaction):
                return
            player = await self.cog._get_player(guild.id)
            player.audio_filter = self._next_filter_mode(player.audio_filter)
            await self.cog._save_player_settings(guild.id, player)
            self._push_history(guild.id, interaction, f"filtro {player.audio_filter}")
            await self._refresh_panel(guild.id)
            await interaction.response.send_message(
                embed=self.cog._ok_embed(
                    "Filtro atualizado",
                    f"Filtro atual: **{player.audio_filter}**. A nova faixa usara esse filtro automaticamente.",
                ),
                ephemeral=True,
            )

    @discord.ui.button(label="🎧 DJ Queue", style=discord.ButtonStyle.primary, custom_id="control_room:dj_queue", row=3)
    async def dj_queue_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            return
        if not await self._check_operator_lock(interaction):
            return
        if not await self.cog._require_control_permissions(interaction):
            return
        await interaction.response.send_modal(DJQueueMoveModal(self.cog, guild.id))

    @discord.ui.button(label="🎛️ Preset", style=discord.ButtonStyle.primary, custom_id="control_room:preset", row=3)
    async def preset_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            return
        if not await self._check_operator_lock(interaction):
            return
        if not await self.cog._require_control_permissions(interaction):
            return
        player = await self.cog._get_player(guild.id)
        options = ("festa", "chill", "focus", "padrao")
        idx = int(self.cog._control_room_preset_cursor.get(guild.id, -1))
        next_preset = options[(idx + 1) % len(options)]
        applied, volume_percent = await self.cog._apply_control_preset(guild.id, next_preset)
        self.cog._control_room_preset_cursor[guild.id] = options.index(applied) if applied in options else 0
        self._push_history(guild.id, interaction, f"preset {applied} ({volume_percent}%)")
        await self._refresh_panel(guild.id)
        await interaction.response.send_message(
            embed=self.cog._ok_embed(
                "Preset aplicado",
                f"Preset: **{applied}**\nVolume: `{volume_percent}%` • Filtro: `{player.audio_filter}`",
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="🔐 Assumir", style=discord.ButtonStyle.secondary, custom_id="control_room:takeover", row=3)
    async def takeover_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            return
        if not await self.cog._require_control_permissions(interaction):
            return
        if interaction.user is None:
            return
        self.operator_user_id = interaction.user.id
        self.cog._control_room_operator[guild.id] = interaction.user.id
        self._push_history(guild.id, interaction, "assumiu a operacao da central")
        await self._refresh_panel(guild.id)
        await interaction.response.send_message(
            embed=self.cog._ok_embed("Controle assumido", f"Novo operador: <@{interaction.user.id}>."),
            ephemeral=True,
        )

    @discord.ui.button(label="📜 Queue", style=discord.ButtonStyle.secondary, custom_id="control_room:queue", row=2)
    async def queue_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                embed=self.cog._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return
        player = await self.cog._get_player(guild.id)
        items = player.snapshot_queue()
        embed = self.cog._build_queue_embed(player=player, items=items, page=0)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🎵 NowPlaying", style=discord.ButtonStyle.secondary, custom_id="control_room:nowplaying", row=2)
    async def nowplaying_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                embed=self.cog._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return
        player = await self.cog._get_player(guild.id)
        if not player.current:
            await interaction.response.send_message(
                embed=self.cog._warn_embed("Sem reproducao", "Nao ha musica tocando agora."),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(embed=self.cog._build_nowplaying_embed(player, player.current), ephemeral=True)


class MiniVoiceView(discord.ui.View):
    def __init__(self, cog: MusicCog, guild_id: int) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

    @discord.ui.button(label="⏸️", style=discord.ButtonStyle.secondary, custom_id="mini_voice:pause")
    async def pause_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            return
        if not await self.cog._require_same_voice_channel(interaction):
            return
        vc = guild.voice_client
        if vc is None or not self.cog._is_voice_playing(vc):
            await interaction.response.send_message(embed=self.cog._warn_embed("Sem reproducao", "Nada tocando agora."), ephemeral=True)
            return
        await self.cog._pause_voice(vc)
        await interaction.response.send_message(embed=self.cog._ok_embed("Pause", "Pausado."), ephemeral=True)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.success, custom_id="mini_voice:resume")
    async def resume_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            return
        if not await self.cog._require_same_voice_channel(interaction):
            return
        vc = guild.voice_client
        if vc is None or not self.cog._is_voice_paused(vc):
            await interaction.response.send_message(embed=self.cog._warn_embed("Nao pausada", "A musica nao esta pausada."), ephemeral=True)
            return
        await self.cog._resume_voice(vc)
        await interaction.response.send_message(embed=self.cog._ok_embed("Resume", "Retomado."), ephemeral=True)

    @discord.ui.button(label="⏭️", style=discord.ButtonStyle.primary, custom_id="mini_voice:skip")
    async def skip_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            return
        if not await self.cog._require_same_voice_channel(interaction):
            return
        vc = guild.voice_client
        if vc is None or not self.cog._is_voice_playing(vc):
            await interaction.response.send_message(embed=self.cog._warn_embed("Sem reproducao", "Nao ha musica tocando."), ephemeral=True)
            return
        if not self.cog._is_control_admin(interaction):
            approved = await self.cog._try_vote_action(interaction, "skip")
            if not approved:
                return
        await self.cog._stop_voice(vc)
        await interaction.response.send_message(embed=self.cog._ok_embed("Skip", "Musica pulada."), ephemeral=True)

    @discord.ui.button(label="⏹️", style=discord.ButtonStyle.danger, custom_id="mini_voice:stop")
    async def stop_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            return
        if not await self.cog._require_same_voice_channel(interaction):
            return
        if not self.cog._is_control_admin(interaction):
            approved = await self.cog._try_vote_action(interaction, "stop")
            if not approved:
                return
        player = await self.cog._get_player(guild.id)
        lock = self.cog._get_lock(guild.id)
        async with lock:
            self.cog.queue_service.clear(player)
            player.current = None
            player.current_started_at = None
            player.pause_started_at = None
            player.paused_accumulated_seconds = 0.0
            player.suppress_after_playback = True
            await self.cog._persist_queue_state(guild.id, player)
        vc = guild.voice_client
        if self.cog._is_voice_connected(vc):
            await self.cog._stop_voice(vc)
        await interaction.response.send_message(embed=self.cog._ok_embed("Stop", "Fila limpa."), ephemeral=True)

    @discord.ui.button(label="🔌", style=discord.ButtonStyle.danger, custom_id="mini_voice:disconnect")
    async def disconnect_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            return
        if not await self.cog._require_same_voice_channel(interaction):
            return
        if not self.cog._is_control_admin(interaction):
            approved = await self.cog._try_vote_action(interaction, "disconnect")
            if not approved:
                return
        vc = guild.voice_client
        if vc and self.cog._is_voice_connected(vc):
            await vc.disconnect(force=True)
        await self.cog._clear_voice_mini_panel(guild.id)
        await interaction.response.send_message(embed=self.cog._ok_embed("Disconnect", "Bot desconectado."), ephemeral=True)
