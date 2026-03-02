from __future__ import annotations

import json
import time
from collections import deque
from typing import cast

import discord
from discord import app_commands

from botmusica.music.player import FILTERS
from botmusica.music.services.player_state import PlayerState
from botmusica.music.views import NowPlayingView, QueueView


async def _filter_autocomplete_proxy(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    cog = interaction.client.get_cog("MusicCog")
    if cog is None:
        return []
    return await cast(object, cog)._filter_autocomplete(interaction, current)


async def _loop_autocomplete_proxy(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    cog = interaction.client.get_cog("MusicCog")
    if cog is None:
        return []
    return await cast(object, cog)._loop_autocomplete(interaction, current)


class PlayerCommandsMixin:
    @app_commands.command(name="join", description="Faz o bot entrar no seu canal de voz.")
    async def join(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        voice_client = await self._ensure_voice(interaction)
        if voice_client is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Canal de voz", "Entre em um canal de voz para usar `/join`."),
                ephemeral=True,
            )
            return
        resumed = await self._recover_playback_after_reconnect(guild, interaction.channel)
        await self._send_response(interaction, 
            embed=self._ok_embed(
                "Conectado",
                (
                    f"Entrei no canal **{voice_client.channel.name}** e retomei a fila."
                    if resumed
                    else f"Entrei no canal **{voice_client.channel.name}**."
                ),
            )
        )

    @app_commands.command(name="skip", description="Pula a musica atual.")
    async def skip(self, interaction: discord.Interaction) -> None:
        if not await self._require_same_voice_channel(interaction):
            return

        guild = interaction.guild
        if guild is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        voice_client = guild.voice_client
        if not self._is_voice_connected(voice_client) or (
            not self._is_voice_playing(voice_client) and not self._is_voice_paused(voice_client)
        ):
            await self._send_response(interaction, 
                embed=self._warn_embed("Sem reproducao", "Nao ha musica tocando agora."),
                ephemeral=True,
            )
            return

        player = await self._get_player(guild.id)
        if not self._is_control_admin(interaction):
            approved = await self._try_vote_action(interaction, "skip")
            if not approved:
                return
        else:
            self._votes.pop((guild.id, "skip"), None)
            await self.store.delete_vote_state(guild.id, "skip")
        lock = self._get_lock(guild.id)
        async with lock:
            player.suppress_after_playback = True
        await self._record_queue_event(guild.id, "skip")
        await self._stop_voice(voice_client)
        await self._send_response(interaction, embed=self._ok_embed("Skip", "Musica pulada."))

    @app_commands.command(name="pause", description="Pausa a musica atual.")
    async def pause(self, interaction: discord.Interaction) -> None:
        if not await self._require_control_permissions(interaction):
            return
        if not await self._require_same_voice_channel(interaction):
            return

        guild = interaction.guild
        if guild is None or guild.voice_client is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Player inativo", "Nao ha player ativo."),
                ephemeral=True,
            )
            return
        if not self._is_voice_playing(guild.voice_client):
            await self._send_response(interaction, 
                embed=self._warn_embed("Sem reproducao", "Nada esta tocando agora."),
                ephemeral=True,
            )
            return

        player = await self._get_player(guild.id)
        await self._pause_voice(guild.voice_client)
        if player.pause_started_at is None:
            player.pause_started_at = time.monotonic()
        self._set_player_state(guild.id, PlayerState.PAUSED, reason="pause_command")
        await self._send_response(interaction, embed=self._ok_embed("Pause", "Reproducao pausada."))

    @app_commands.command(name="resume", description="Retoma a musica pausada.")
    async def resume(self, interaction: discord.Interaction) -> None:
        if not await self._require_control_permissions(interaction):
            return
        if not await self._require_same_voice_channel(interaction):
            return

        guild = interaction.guild
        if guild is None or guild.voice_client is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Player inativo", "Nao ha player ativo."),
                ephemeral=True,
            )
            return
        player = await self._get_player(guild.id)
        if not self._is_voice_paused(guild.voice_client):
            resumed = await self._recover_playback_after_reconnect(guild, interaction.channel)
            if resumed:
                await self._send_response(
                    interaction,
                    embed=self._ok_embed("Resume", "Playback retomado apos reconexao."),
                )
                return
            await self._send_response(interaction, 
                embed=self._warn_embed("Nao pausada", "A musica nao esta pausada e nao ha fila para retomar."),
                ephemeral=True,
            )
            return

        if player.pause_started_at is not None:
            player.paused_accumulated_seconds += max(time.monotonic() - player.pause_started_at, 0.0)
            player.pause_started_at = None
        await self._resume_voice(guild.voice_client)
        self._set_player_state(guild.id, PlayerState.PLAYING, reason="resume_command")
        await self._send_response(interaction, embed=self._ok_embed("Resume", "Reproducao retomada."))

    @app_commands.command(name="stop", description="Para a musica e limpa a fila.")
    async def stop(self, interaction: discord.Interaction) -> None:
        if not await self._require_same_voice_channel(interaction):
            return

        guild = interaction.guild
        if guild is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        voice_client = guild.voice_client
        player = await self._get_player(guild.id)
        if not self._is_control_admin(interaction):
            approved = await self._try_vote_action(interaction, "stop")
            if not approved:
                return
        else:
            self._votes.pop((guild.id, "stop"), None)
            await self.store.delete_vote_state(guild.id, "stop")
        lock = self._get_lock(guild.id)
        async with lock:
            removed = self.queue_service.clear(player)
            player.current = None
            player.current_started_at = None
            player.pause_started_at = None
            player.paused_accumulated_seconds = 0.0
            player.suppress_after_playback = True
            await self._persist_queue_state(guild.id, player)
        await self._clear_nowplaying_message(guild.id)
        await self._record_queue_event(guild.id, "stop", removed=len(removed))
        if self._is_voice_connected(voice_client):
            await self._stop_voice(voice_client)
            self._schedule_idle_disconnect(guild, interaction.channel)
        self._set_player_state(guild.id, PlayerState.IDLE, reason="stop_command")
        await self._send_response(interaction, 
            embed=self._ok_embed("Stop", f"Fila limpa. Removidas {len(removed)} musicas pendentes.")
        )

    @app_commands.command(name="clear", description="Limpa apenas os itens pendentes da fila.")
    async def clear(self, interaction: discord.Interaction) -> None:
        if not await self._require_control_permissions(interaction):
            return
        if not await self._require_same_voice_channel(interaction):
            return

        guild = interaction.guild
        if guild is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        player = await self._get_player(guild.id)
        lock = self._get_lock(guild.id)
        async with lock:
            removed = self.queue_service.clear(player)
            await self._persist_queue_state(guild.id, player)
        await self._record_queue_event(guild.id, "clear", removed=len(removed))
        await self._send_response(interaction, 
            embed=self._ok_embed("Clear", f"Fila pendente limpa: {len(removed)} removidas.")
        )

    @app_commands.command(name="queue", description="Mostra a fila atual.")
    async def queue(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        player = await self._get_player(guild.id)
        items = player.snapshot_queue()
        embed = self._build_queue_embed(player=player, items=items, page=0)
        if len(items) <= 10:
            await self._send_response(interaction, embed=embed)
            return
        view = QueueView(self, author_id=interaction.user.id if interaction.user else 0, player=player, items=items, initial_page=0)
        await self._send_response(interaction, embed=embed, view=view)

    @app_commands.command(name="nowplaying", description="Mostra detalhes da musica atual.")
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        player = await self._get_player(guild.id)
        if not player.current:
            await self._send_response(interaction, 
                embed=self._warn_embed("Sem reproducao", "Nao ha musica tocando agora."),
                ephemeral=True,
            )
            return
        embed = self._build_nowplaying_embed(player, player.current)
        view = NowPlayingView(
            self,
            guild_id=guild.id,
            author_id=interaction.user.id if interaction.user else 0,
        )
        await self._send_response(interaction, embed=embed, view=view)

    @app_commands.command(name="lyrics", description="Busca a letra da musica atual.")
    async def lyrics(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await self._send_response(
                interaction,
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        player = await self._get_player(guild.id)
        if not player.current:
            await self._send_response(
                interaction,
                embed=self._warn_embed("Sem reproducao", "Nao ha musica tocando agora."),
                ephemeral=True,
            )
            return

        if not await self._safe_defer(interaction, thinking=True, ephemeral=True):
            return
        track = player.current
        lyrics = await self._search_lyrics(track.title)
        if not lyrics:
            await self._send_followup(
                interaction,
                embed=self._warn_embed("Letra nao encontrada", "Nao encontrei letra para a musica atual."),
                ephemeral=True,
            )
            return

        max_len = 3800
        clipped = lyrics if len(lyrics) <= max_len else f"{lyrics[:max_len].rstrip()}\n..."
        embed = self._embed(
            "📝 Letra",
            f"**{track.title}**\n{self._separator()}\n{clipped}",
            color=self._theme_color("playback"),
        )
        await self._send_followup(interaction, embed=embed, ephemeral=True)

    @app_commands.command(name="history", description="Mostra as ultimas faixas reproduzidas neste servidor.")
    async def history(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await self._send_response(
                interaction,
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        titles = list(self._autoplay_recent_titles.get(guild.id, deque()))
        if not titles:
            await self._send_response(
                interaction,
                embed=self._warn_embed("Sem historico", "Ainda nao ha faixas reproduzidas para exibir."),
                ephemeral=True,
            )
            return

        recent = list(reversed(titles[-10:]))
        lines = [f"`{idx}` {title}" for idx, title in enumerate(recent, start=1)]
        embed = self._embed(
            "🕘 Historico Recente",
            f"Ultimas faixas tocadas neste servidor.\n{self._separator()}",
            color=self._theme_color("queue"),
        )
        embed.add_field(name="Faixas", value="\n".join(lines), inline=False)
        embed.set_footer(text=f"Mostrando {len(recent)} de {len(titles)} registradas")
        await self._send_response(interaction, embed=embed)

    @app_commands.command(name="queue_events", description="Mostra eventos recentes da fila (admin).")
    @app_commands.describe(limite="Quantidade de eventos (1-30)")
    async def queue_events(self, interaction: discord.Interaction, limite: app_commands.Range[int, 1, 30] = 15) -> None:
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
        events = await self.store.list_queue_events(guild.id, limit=int(limite))
        if not events:
            await self._send_response(
                interaction,
                embed=self._warn_embed("Sem eventos", "Nao ha eventos de fila registrados ainda."),
                ephemeral=True,
            )
            return

        lines: list[str] = []
        for event in events:
            try:
                details = json.loads(event.details_json or "{}")
                if isinstance(details, dict):
                    compact = ", ".join(f"{k}={v}" for k, v in list(details.items())[:2])
                else:
                    compact = "-"
            except Exception:
                compact = "-"
            lines.append(f"`#{event.id}` {event.action} • {compact}")
        embed = self._embed(
            "🧾 Queue Events",
            f"Ultimos eventos duraveis da fila.\n{self._separator()}",
            color=self._theme_color("metrics"),
        )
        embed.add_field(name="Eventos", value="\n".join(lines[:15]), inline=False)
        await self._send_response(interaction, embed=embed, ephemeral=True)

    @app_commands.command(name="remove", description="Remove uma musica da fila por posicao.")
    @app_commands.describe(posicao="Posicao na fila (1 = primeiro da fila)")
    async def remove(self, interaction: discord.Interaction, posicao: app_commands.Range[int, 1]) -> None:
        if not await self._require_control_permissions(interaction):
            return
        if not await self._require_same_voice_channel(interaction):
            return

        guild = interaction.guild
        if guild is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        player = await self._get_player(guild.id)
        lock = self._get_lock(guild.id)
        try:
            async with lock:
                removed = self.queue_service.remove(player, posicao)
                await self._persist_queue_state(guild.id, player)
        except IndexError:
            await self._send_response(interaction, 
                embed=self._warn_embed("Posicao invalida", "Posicao invalida para a fila atual."),
                ephemeral=True,
            )
            return
        await self._record_queue_event(guild.id, "remove", position=posicao, title=removed.title)
        await self._send_response(interaction, embed=self._ok_embed("Remove", f"Removida da fila: **{removed.title}**"))

    @app_commands.command(name="move", description="Move uma musica na fila de uma posicao para outra.")
    @app_commands.describe(origem="Posicao original", destino="Nova posicao")
    async def move(
        self,
        interaction: discord.Interaction,
        origem: app_commands.Range[int, 1],
        destino: app_commands.Range[int, 1],
    ) -> None:
        if not await self._require_control_permissions(interaction):
            return
        if not await self._require_same_voice_channel(interaction):
            return
        guild = interaction.guild
        if guild is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return
        player = await self._get_player(guild.id)
        lock = self._get_lock(guild.id)
        try:
            async with lock:
                moved = self.queue_service.move(player, origem, destino)
                await self._persist_queue_state(guild.id, player)
        except IndexError:
            await self._send_response(interaction, 
                embed=self._warn_embed("Posicoes invalidas", "Posicoes invalidas para a fila atual."),
                ephemeral=True,
            )
            return
        await self._record_queue_event(guild.id, "move", source=origem, target=destino, title=moved.title)
        await self._send_response(interaction, 
            embed=self._ok_embed("Move", f"Movida: **{moved.title}** ({origem} -> {destino})")
        )

    @app_commands.command(name="jump", description="Traz um item da fila para tocar em seguida.")
    @app_commands.describe(posicao="Posicao da fila para subir ao topo")
    async def jump(self, interaction: discord.Interaction, posicao: app_commands.Range[int, 1]) -> None:
        if not await self._require_control_permissions(interaction):
            return
        if not await self._require_same_voice_channel(interaction):
            return
        guild = interaction.guild
        if guild is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return
        player = await self._get_player(guild.id)
        lock = self._get_lock(guild.id)
        try:
            async with lock:
                picked = self.queue_service.jump(player, posicao)
                await self._persist_queue_state(guild.id, player)
        except IndexError:
            await self._send_response(interaction, 
                embed=self._warn_embed("Posicao invalida", "Posicao invalida para a fila atual."),
                ephemeral=True,
            )
            return
        await self._record_queue_event(guild.id, "jump", position=posicao, title=picked.title)
        await self._send_response(interaction, embed=self._ok_embed("Jump", f"Vai tocar em seguida: **{picked.title}**"))

    @app_commands.command(name="replay", description="Reinicia a musica atual do inicio.")
    async def replay(self, interaction: discord.Interaction) -> None:
        if not await self._require_control_permissions(interaction):
            return
        if not await self._require_same_voice_channel(interaction):
            return
        guild = interaction.guild
        if guild is None or guild.voice_client is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Player inativo", "Nao ha player ativo."),
                ephemeral=True,
            )
            return
        player = await self._get_player(guild.id)
        if not player.current:
            await self._send_response(interaction, 
                embed=self._warn_embed("Sem reproducao", "Nao ha musica tocando agora."),
                ephemeral=True,
            )
            return

        lock = self._get_lock(guild.id)
        async with lock:
            self.queue_service.enqueue_front(player, player.current)
            player.suppress_after_playback = True
            await self._persist_queue_state(guild.id, player)
        await self._record_queue_event(guild.id, "replay", title=player.current.title if player.current else "unknown")
        await self._stop_voice(guild.voice_client)
        await self._send_response(interaction, embed=self._ok_embed("Replay", "Musica atual reiniciada."))

    @app_commands.command(name="seek", description="Avanca para um ponto especifico da musica atual (segundos).")
    @app_commands.describe(segundos="Posicao em segundos")
    async def seek(self, interaction: discord.Interaction, segundos: app_commands.Range[int, 0]) -> None:
        if not await self._require_control_permissions(interaction):
            return
        if not await self._require_same_voice_channel(interaction):
            return
        guild = interaction.guild
        if guild is None or guild.voice_client is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Player inativo", "Nao ha player ativo."),
                ephemeral=True,
            )
            return
        player = await self._get_player(guild.id)
        if not player.current:
            await self._send_response(interaction, 
                embed=self._warn_embed("Sem reproducao", "Nao ha musica tocando agora."),
                ephemeral=True,
            )
            return
        if player.current.duration_seconds is not None and segundos >= player.current.duration_seconds:
            await self._send_response(interaction, 
                embed=self._warn_embed("Posicao invalida", "Posicao maior que a duracao da musica."),
                ephemeral=True,
            )
            return

        lock = self._get_lock(guild.id)
        async with lock:
            player.pending_seek_seconds = int(segundos)
            self.queue_service.enqueue_front(player, player.current)
            player.suppress_after_playback = True
            player.current_started_at = None
            player.pause_started_at = None
            player.paused_accumulated_seconds = 0.0
            await self._persist_queue_state(guild.id, player)
        await self._record_queue_event(guild.id, "seek", seconds=int(segundos), title=player.current.title if player.current else "unknown")
        await self._stop_voice(guild.voice_client)
        await self._send_response(interaction, embed=self._ok_embed("Seek", f"Seek aplicado para `{segundos}s`."))

    @app_commands.command(name="shuffle", description="Embaralha a fila pendente.")
    async def shuffle(self, interaction: discord.Interaction) -> None:
        if not await self._require_control_permissions(interaction):
            return
        if not await self._require_same_voice_channel(interaction):
            return
        guild = interaction.guild
        if guild is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return
        player = await self._get_player(guild.id)
        lock = self._get_lock(guild.id)
        async with lock:
            total = self.queue_service.shuffle(player)
            if total > 1:
                await self._persist_queue_state(guild.id, player)
        if total <= 1:
            await self._send_response(interaction, 
                embed=self._warn_embed("Fila pequena", "Fila pequena demais para embaralhar."),
                ephemeral=True,
            )
            return
        await self._record_queue_event(guild.id, "shuffle", total=total)
        await self._send_response(interaction, embed=self._ok_embed("Shuffle", f"Fila embaralhada ({total} itens)."))

    @app_commands.command(name="volume", description="Define o volume do player (1 a 200).")
    @app_commands.describe(percentual="Percentual de volume")
    async def volume(self, interaction: discord.Interaction, percentual: app_commands.Range[int, 1, 200]) -> None:
        if not await self._require_control_permissions(interaction):
            return
        if not await self._require_same_voice_channel(interaction):
            return
        guild = interaction.guild
        if guild is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        player = await self._get_player(guild.id)
        normalized = percentual / 100.0
        player.volume = normalized
        await self._save_player_settings(guild.id, player)

        voice_client = guild.voice_client
        if self._is_voice_connected(voice_client):
            await self._set_voice_volume(voice_client, normalized)
        await self._send_response(interaction, 
            embed=self._ok_embed("Volume atualizado", f"O volume foi ajustado para **{percentual}%**.")
        )

    @app_commands.command(name="filter", description="Define filtro de audio do player.")
    @app_commands.describe(modo="off, bassboost, nightcore, vaporwave, karaoke")
    @app_commands.autocomplete(modo=_filter_autocomplete_proxy)
    async def filter(self, interaction: discord.Interaction, modo: str) -> None:
        if not await self._require_control_permissions(interaction):
            return
        if not await self._require_same_voice_channel(interaction):
            return
        guild = interaction.guild
        if guild is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        player = await self._get_player(guild.id)
        normalized_mode = modo.strip().casefold()
        if normalized_mode not in FILTERS:
            await self._send_response(interaction, 
                embed=self._warn_embed("Filtro invalido", "Use um filtro valido: off, bassboost, nightcore, vaporwave, karaoke."),
                ephemeral=True,
            )
            return

        player.audio_filter = normalized_mode
        await self._save_player_settings(guild.id, player)

        voice_client = guild.voice_client
        if voice_client and player.current:
            lock = self._get_lock(guild.id)
            async with lock:
                self.queue_service.enqueue_front(player, player.current)
                player.suppress_after_playback = True
                await self._persist_queue_state(guild.id, player)
            await self._stop_voice(voice_client)
            await self._send_response(interaction, 
                embed=self._ok_embed(
                    "Filtro atualizado",
                    f"Filtro definido para **{normalized_mode}** e a musica atual foi reiniciada.",
                )
            )
            return
        await self._send_response(interaction, 
            embed=self._ok_embed("Filtro atualizado", f"Filtro definido para **{normalized_mode}**.")
        )

    @app_commands.command(name="loop", description="Define o modo de repeticao.")
    @app_commands.describe(modo="off, track ou queue")
    @app_commands.autocomplete(modo=_loop_autocomplete_proxy)
    async def loop(self, interaction: discord.Interaction, modo: str) -> None:
        if not await self._require_control_permissions(interaction):
            return
        if not await self._require_same_voice_channel(interaction):
            return
        guild = interaction.guild
        if guild is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return
        player = await self._get_player(guild.id)
        normalized_mode = modo.strip().casefold()
        if normalized_mode not in {"off", "track", "queue"}:
            await self._send_response(interaction, 
                embed=self._warn_embed("Loop invalido", "Use um modo valido: off, track ou queue."),
                ephemeral=True,
            )
            return

        player.loop_mode = normalized_mode
        await self._save_player_settings(guild.id, player)
        await self._send_response(interaction, 
            embed=self._ok_embed("Loop atualizado", f"Modo de loop ajustado para **{normalized_mode}**.")
        )

    @app_commands.command(name="autoplay", description="Liga/desliga autoplay quando a fila acabar.")
    @app_commands.describe(ativo="true para ligar, false para desligar")
    async def autoplay(self, interaction: discord.Interaction, ativo: bool) -> None:
        if not await self._require_control_permissions(interaction):
            return
        if not await self._require_same_voice_channel(interaction):
            return
        guild = interaction.guild
        if guild is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        player = await self._get_player(guild.id)
        player.autoplay = ativo
        await self._save_player_settings(guild.id, player)
        await self._send_response(interaction, 
            embed=self._ok_embed("Autoplay atualizado", f"Autoplay **{'ligado' if ativo else 'desligado'}**.")
        )

    @app_commands.command(name="247", description="Liga/desliga modo 24/7 para manter o bot conectado.")
    @app_commands.describe(ativo="true para manter conectado, false para permitir idle disconnect")
    async def mode_247(self, interaction: discord.Interaction, ativo: bool) -> None:
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
        player = await self._get_player(guild.id)
        player.stay_connected = ativo
        await self._save_player_settings(guild.id, player)
        if not ativo:
            self._schedule_idle_disconnect(guild, interaction.channel)
        else:
            self._cancel_idle_timer(guild.id)
        await self._send_response(
            interaction,
            embed=self._ok_embed("Modo 24/7", f"Modo 24/7 **{'ligado' if ativo else 'desligado'}**."),
        )

    @app_commands.command(name="settings", description="Mostra as configuracoes atuais do player.")
    async def settings(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return

        player = await self._get_player(guild.id)
        volume_percent = int(player.volume * 100)
        queue_size = len(player.snapshot_queue())
        current = player.current.title if player.current else "nada"
        autoplay = "on" if player.autoplay else "off"
        stay_connected = "on" if player.stay_connected else "off"
        embed = self._embed(
            "⚙️ Configuracoes do Servidor",
            "Preferencias persistidas do player neste servidor.",
            color=self._theme_color("general"),
        )
        embed.add_field(
            name="Player",
            value=(
                f"• Volume: `{volume_percent}%`\n"
                f"• Loop: `{player.loop_mode}`\n"
                f"• Autoplay: `{autoplay}`\n"
                f"• 24/7: `{stay_connected}`\n"
                f"• Filtro: `{player.audio_filter}`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Sessao",
            value=(
                f"• Tocando: `{current}`\n"
                f"• Fila pendente: `{queue_size}`\n"
                f"• Playlist import max: `{self.max_playlist_import}`"
            ),
            inline=False,
        )
        policy = self._policy_for_guild(guild.id)
        embed.add_field(
            name="🛡️ Moderacao",
            value=(
                f"max_duracao: `{policy.max_track_duration_seconds or 'off'}`\n"
                f"whitelist: `{len(policy.domain_whitelist)}`\n"
                f"blacklist: `{len(policy.domain_blacklist)}`"
            ),
            inline=False,
        )
        await self._send_response(interaction, embed=embed)
