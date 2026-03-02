from __future__ import annotations

import discord
from discord import app_commands
from typing import cast

from botmusica.music.player import Track
from botmusica.music.storage import FavoriteTrack, PlaylistTrack


async def _play_autocomplete_proxy(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    cog = interaction.client.get_cog("MusicCog")
    if cog is None:
        return []
    return await cast(object, cog)._play_autocomplete(interaction, current)


async def _playlist_name_autocomplete_proxy(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    cog = interaction.client.get_cog("MusicCog")
    if cog is None:
        return []
    return await cast(object, cog)._playlist_name_autocomplete(interaction, current)


class PlaylistFavoritesCommandsMixin:
    @app_commands.command(name="fav_add", description="Salva uma musica nos seus favoritos.")
    @app_commands.describe(link_ou_busca="URL ou termo de busca")
    @app_commands.autocomplete(link_ou_busca=_play_autocomplete_proxy)
    async def fav_add(self, interaction: discord.Interaction, link_ou_busca: str) -> None:
        guild = interaction.guild
        user = interaction.user
        if guild is None or user is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        if not await self._safe_defer(interaction, thinking=True, ephemeral=True):
            return
        try:
            track, resolved_spotify = await self._extract_track_with_spotify_fallback(
                link=link_ou_busca,
                requester=user.display_name,
            )
        except Exception as exc:
            self._metrics["extraction_failures"] += 1
            title, description = self._friendly_extraction_error(exc)
            await self._send_followup(interaction, 
                embed=self._error_embed(title, description),
                ephemeral=True,
            )
            return

        favorite = FavoriteTrack(
            title=track.title,
            source_query=track.source_query,
            webpage_url=track.webpage_url,
            duration_seconds=track.duration_seconds,
        )
        await self.favorites_repo.add(guild.id, user.id, favorite)
        self._record_query(guild.id, link_ou_busca)
        await self._send_followup(interaction, 
            embed=self._ok_embed(
                "Favorito salvo",
                (
                    f"**{track.title}** foi salvo nos seus favoritos."
                    if not resolved_spotify
                    else f"**{track.title}** foi salvo (resolvido via Spotify -> busca)."
                ),
            ),
            ephemeral=True,
        )

    @app_commands.command(name="fav_list", description="Lista os seus favoritos salvos.")
    async def fav_list(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        user = interaction.user
        if guild is None or user is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        favorites = await self.favorites_repo.list(guild.id, user.id)
        embed = self._embed("⭐ Seus Favoritos", "Lista de musicas salvas para uso rapido.", color=discord.Color.gold())
        if not favorites:
            embed.add_field(name="Vazio", value="Voce ainda nao tem favoritos.", inline=False)
            await self._send_response(interaction, embed=embed, ephemeral=True)
            return

        lines = [
            (
                f"`{idx}` {item.title} (`{self._format_duration(item.duration_seconds)}`)"
                + (
                    f" • artista: `{self._guess_artist(item.title)}`"
                    if self._guess_artist(item.title)
                    else ""
                )
            )
            for idx, item in enumerate(favorites[:20], start=1)
        ]
        embed.add_field(name="Favoritos", value="\n".join(lines), inline=False)
        if len(favorites) > 20:
            embed.set_footer(text=f"Mostrando 20 de {len(favorites)} favoritos.")
        await self._send_response(interaction, embed=embed, ephemeral=True)

    @app_commands.command(name="fav_remove", description="Remove um favorito pela posicao da lista.")
    @app_commands.describe(posicao="Posicao da lista em /fav_list")
    async def fav_remove(self, interaction: discord.Interaction, posicao: app_commands.Range[int, 1]) -> None:
        guild = interaction.guild
        user = interaction.user
        if guild is None or user is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        favorites = await self.favorites_repo.list(guild.id, user.id)
        if posicao > len(favorites):
            await self._send_response(interaction, 
                embed=self._warn_embed("Posicao invalida", "Nao existe favorito nessa posicao."),
                ephemeral=True,
            )
            return

        item = favorites[posicao - 1]
        deleted = await self.favorites_repo.remove(guild.id, user.id, item.source_query)
        if deleted <= 0:
            await self._send_response(interaction, 
                embed=self._warn_embed("Nao removido", "Nao consegui remover esse favorito."),
                ephemeral=True,
            )
            return

        await self._send_response(interaction, 
            embed=self._ok_embed("Favorito removido", f"Removido: **{item.title}**"),
            ephemeral=True,
        )

    @app_commands.command(name="fav_play", description="Adiciona um favorito na fila pela posicao da lista.")
    @app_commands.describe(posicao="Posicao da lista em /fav_list")
    async def fav_play(self, interaction: discord.Interaction, posicao: app_commands.Range[int, 1]) -> None:
        guild = interaction.guild
        user = interaction.user
        if guild is None or user is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        cooldown_left = self._check_cooldown(user.id, "fav_play", self.play_cooldown_seconds)
        if cooldown_left > 0:
            await self._send_response(interaction, 
                embed=self._warn_embed("Cooldown ativo", f"Aguarde `{cooldown_left:.1f}s` para usar novamente."),
                ephemeral=True,
            )
            return

        favorites = await self.favorites_repo.list(guild.id, user.id)
        if posicao > len(favorites):
            await self._send_response(interaction, 
                embed=self._warn_embed("Posicao invalida", "Nao existe favorito nessa posicao."),
                ephemeral=True,
            )
            return

        track = self._track_from_favorite(favorites[posicao - 1], requester=user.display_name)
        await self._enqueue_selected_track(interaction, track)

    @app_commands.command(name="playlist_save", description="Salva a fila atual em uma playlist pessoal.")
    @app_commands.describe(nome="Nome da playlist")
    async def playlist_save(self, interaction: discord.Interaction, nome: str) -> None:
        guild = interaction.guild
        user = interaction.user
        if guild is None or user is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        normalized = nome.strip()
        if not normalized:
            await self._send_response(interaction, 
                embed=self._warn_embed("Nome invalido", "Informe um nome valido para a playlist."),
                ephemeral=True,
            )
            return

        player = await self._get_player(guild.id)
        items: list[Track] = []
        if player.current:
            items.append(player.current)
        items.extend(player.snapshot_queue())
        if not items:
            await self._send_response(interaction, 
                embed=self._warn_embed("Fila vazia", "Nao ha musicas para salvar em playlist."),
                ephemeral=True,
            )
            return

        payload = [
            PlaylistTrack(
                title=track.title,
                source_query=track.source_query,
                webpage_url=track.webpage_url,
                duration_seconds=track.duration_seconds,
            )
            for track in items
        ]
        await self.playlist_repo.save(guild.id, user.id, normalized, payload)
        await self._send_response(interaction, 
            embed=self._ok_embed("Playlist salva", f"Playlist **{normalized}** salva com `{len(payload)}` faixas."),
            ephemeral=True,
        )

    @app_commands.command(name="playlist_list", description="Lista suas playlists salvas.")
    async def playlist_list(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        user = interaction.user
        if guild is None or user is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        names = await self.playlist_repo.list_names(guild.id, user.id)
        embed = self._embed("🗂️ Suas Playlists", "Playlists salvas na sua conta deste servidor.", color=discord.Color.teal())
        if not names:
            embed.add_field(name="Vazio", value="Voce ainda nao tem playlists salvas.", inline=False)
        else:
            preview_lines: list[str] = []
            for name in names[:20]:
                items = await self.playlist_repo.load(guild.id, user.id, name)
                if not items:
                    preview_lines.append(f"- `{name}` • `0 faixa(s)`")
                    continue
                first = items[0]
                artist = self._guess_artist(first.title)
                artist_part = f" • artista: `{artist}`" if artist else ""
                preview_lines.append(
                    f"- `{name}` • `{len(items)} faixa(s)` • {first.title}{artist_part}"
                )
            embed.add_field(name="Playlists", value="\n".join(preview_lines), inline=False)
            if len(names) > 20:
                embed.set_footer(text=f"Mostrando 20 de {len(names)} playlists.")
        await self._send_response(interaction, embed=embed, ephemeral=True)

    @app_commands.command(name="playlist_load", description="Carrega uma playlist pessoal na fila.")
    @app_commands.describe(nome="Nome da playlist")
    @app_commands.autocomplete(nome=_playlist_name_autocomplete_proxy)
    async def playlist_load(self, interaction: discord.Interaction, nome: str) -> None:
        guild = interaction.guild
        user = interaction.user
        if guild is None or user is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        cooldown_left = self._check_cooldown(user.id, "playlist_load", self.play_cooldown_seconds)
        if cooldown_left > 0:
            await self._send_response(interaction, 
                embed=self._warn_embed("Cooldown ativo", f"Aguarde `{cooldown_left:.1f}s` para usar novamente."),
                ephemeral=True,
            )
            return
        rate_left = self._check_play_rate_limits(
            guild_id=guild.id,
            user_id=user.id,
            key="playlist_load",
            channel_id=user.voice.channel.id if isinstance(user, discord.Member) and user.voice and user.voice.channel else 0,
        )
        if rate_left > 0:
            await self._send_response(
                interaction,
                embed=self._warn_embed("Rate limit", f"Muitas requisicoes de `/playlist_load`. Tente em `{rate_left:.1f}s`."),
                ephemeral=True,
            )
            return

        if not await self._safe_defer(interaction, thinking=True, ephemeral=True):
            return
        items = await self.playlist_repo.load(guild.id, user.id, nome.strip())
        if not items:
            await self._send_followup(interaction, 
                embed=self._warn_embed("Playlist vazia", "Nao encontrei itens nessa playlist."),
                ephemeral=True,
            )
            return

        voice_client = await self._ensure_voice(interaction)
        if voice_client is None:
            await self._send_followup(interaction, 
                embed=self._warn_embed("Canal de voz", "Entre em um canal de voz para usar `/playlist_load`."),
                ephemeral=True,
            )
            return

        player = await self._get_player(guild.id)
        lock = self._get_lock(guild.id)
        selected: list[Track] = []
        skipped_policy = 0
        skipped_user_limit = 0
        async with lock:
            capacity = max(self.max_queue_size - len(player.snapshot_queue()), 0)
            for item in items:
                if len(selected) >= capacity:
                    break
                track = self._track_from_playlist_item(item, requester=user.display_name)
                if self.max_user_queue_items > 0 and not self._is_user_queue_within_limit(player, user.display_name, incoming_items=len(selected) + 1):
                    skipped_user_limit += 1
                    continue
                if self._track_policy_error(guild.id, track):
                    skipped_policy += 1
                    continue
                selected.append(track)
            for track in selected:
                await self.queue_service.enqueue(player, track)
            await self._persist_queue_state(guild.id, player)
        await self._record_queue_event(
            guild.id,
            "playlist_load",
            playlist=nome,
            loaded=len(selected),
            skipped_policy=skipped_policy,
            skipped_user_limit=skipped_user_limit,
        )
        self._schedule_prefetch_next(guild.id, player)

        await self._start_next_if_needed(guild, interaction.channel)
        await self._send_followup(interaction, 
            embed=self._ok_embed(
                "Playlist carregada",
                f"Playlist **{nome}** carregada com `{len(selected)}` faixa(s).\n"
                f"Puladas por moderacao: `{skipped_policy}`\n"
                f"Puladas por limite de usuario: `{skipped_user_limit}`",
            ),
            ephemeral=True,
        )

    @app_commands.command(name="playlist_delete", description="Remove uma playlist pessoal.")
    @app_commands.describe(nome="Nome da playlist")
    @app_commands.autocomplete(nome=_playlist_name_autocomplete_proxy)
    async def playlist_delete(self, interaction: discord.Interaction, nome: str) -> None:
        guild = interaction.guild
        user = interaction.user
        if guild is None or user is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        removed = await self.playlist_repo.delete(guild.id, user.id, nome.strip())
        if removed <= 0:
            await self._send_response(interaction, 
                embed=self._warn_embed("Nao encontrada", "Nao existe playlist com esse nome."),
                ephemeral=True,
            )
            return

        await self._send_response(interaction, 
            embed=self._ok_embed("Playlist removida", f"Playlist **{nome}** removida com sucesso."),
            ephemeral=True,
        )

    @app_commands.command(name="playlist_job", description="Mostra status do job de importacao de playlist.")
    async def playlist_job(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await self._send_response(
                interaction,
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return
        job = self.playlist_jobs.active(guild.id) or self.playlist_jobs.latest(guild.id)
        if job is None:
            await self._send_response(
                interaction,
                embed=self._warn_embed("Sem job", "Nao existe importacao de playlist ativa/recente neste servidor."),
                ephemeral=True,
            )
            return
        embed = self._embed("🧰 Playlist Job", "Status da importacao em background.", color=self._theme_color("queue"))
        embed.add_field(
            name="Status",
            value=(
                f"• id: `{job.job_id}`\n"
                f"• status: `{job.status}`\n"
                f"• added: `{job.added}`\n"
                f"• skipped: `{job.skipped}`\n"
                f"• total: `{job.total}`"
            ),
            inline=False,
        )
        await self._send_response(interaction, embed=embed, ephemeral=True)

    @app_commands.command(name="playlist_job_cancel", description="Cancela importacao de playlist em andamento.")
    async def playlist_job_cancel(self, interaction: discord.Interaction) -> None:
        if not await self._require_control_permissions(interaction):
            return
        guild = interaction.guild
        if guild is None:
            await self._send_response(
                interaction,
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return
        active = self.playlist_jobs.active(guild.id)
        if active is None:
            await self._send_response(
                interaction,
                embed=self._warn_embed("Sem job ativo", "Nao ha importacao ativa para cancelar."),
                ephemeral=True,
            )
            return
        self._cancel_playlist_import(guild.id)
        self.playlist_jobs.cancel(guild.id, active.job_id)
        self._log_event("playlist_job_cancelled", guild=guild.id, job_id=active.job_id, user=interaction.user.id if interaction.user else "unknown")
        await self._send_response(
            interaction,
            embed=self._ok_embed("Job cancelado", f"Importacao `{active.job_id}` cancelada."),
            ephemeral=True,
        )
