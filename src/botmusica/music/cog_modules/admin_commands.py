from __future__ import annotations

import asyncio
import logging
import os
import shutil

import discord
from discord import app_commands

from botmusica.music.views import ControlRoomView, HelpView
from botmusica.music.storage import ControlRoomStateRecord

LOGGER = logging.getLogger("botmusica.music")


class AdminCommandsMixin:
    def _is_control_room_panel_message(self, message: discord.Message) -> bool:
        bot_user_id = getattr(getattr(self.bot, "user", None), "id", 0)
        if not message.author or message.author.id != bot_user_id:
            return False
        if not message.embeds:
            return False
        title = (message.embeds[0].title or "").strip()
        return title in {"🎛️ Control Room", "🎛️ Central de Comandos"}

    async def _find_control_room_panel_message(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        *,
        expected_message_id: int | None = None,
    ) -> discord.Message | None:
        candidate_ids: list[int] = []
        if expected_message_id:
            candidate_ids.append(int(expected_message_id))
        cached = self._control_room_state_cache.get(guild.id)
        if cached and cached[0] == channel.id and cached[1] not in candidate_ids:
            candidate_ids.append(int(cached[1]))

        for message_id in candidate_ids:
            try:
                message = await channel.fetch_message(message_id)
            except Exception:
                continue
            if self._is_control_room_panel_message(message):
                return message

        # Retomada rapida: reaproveita a ultima mensagem do bot no canal quando ela ja for o painel.
        try:
            bot_user_id = getattr(getattr(self.bot, "user", None), "id", 0)
            async for message in channel.history(limit=10):
                if not message.author or message.author.id != bot_user_id:
                    continue
                if self._is_control_room_panel_message(message):
                    return message
                break
        except Exception:
            return None

        try:
            async for message in channel.history(limit=50):
                if self._is_control_room_panel_message(message):
                    return message
        except Exception:
            return None
        return None

    async def _upsert_control_room_panel_message(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        *,
        operator_id: int,
        expected_message_id: int | None = None,
        pin_reason: str,
    ) -> tuple[discord.Message, int]:
        embed = await self._build_control_room_embed(guild)
        view = ControlRoomView(self, guild.id, operator_user_id=operator_id)
        reused = await self._find_control_room_panel_message(
            guild,
            channel,
            expected_message_id=expected_message_id,
        )
        if reused is not None:
            message = await reused.edit(embed=embed, view=view)
            reused_count = 1
        else:
            message = await channel.send(embed=embed, view=view)
            reused_count = 0
        try:
            await message.pin(reason=pin_reason)
        except Exception:
            pass
        await self.store.upsert_control_room_state(
            ControlRoomStateRecord(
                guild_id=guild.id,
                channel_id=channel.id,
                message_id=message.id,
                operator_user_id=operator_id,
            )
        )
        self._control_room_state_cache[guild.id] = (channel.id, message.id)
        self.bot.add_view(ControlRoomView(self, guild.id, operator_user_id=operator_id), message_id=message.id)
        return message, reused_count

    async def _reject_if_admin_slash_disabled(self, interaction: discord.Interaction, command_name: str) -> bool:
        if self.admin_slash_enabled:
            warned = getattr(self, "_admin_slash_deprecation_seen", set())
            if command_name not in warned:
                LOGGER.warning(
                    "Comando /%s esta em modo deprecated (admin migrando para painel web).",
                    command_name,
                )
                warned.add(command_name)
                setattr(self, "_admin_slash_deprecation_seen", warned)
            return False
        panel_url = f"http://{self.web_panel_host}:{self.web_panel_port}"
        await self._send_response(
            interaction,
            embed=self._warn_embed(
                "Comando migrado para painel web",
                (
                    f"O comando `/{command_name}` foi desativado no slash.\n"
                    f"Use o painel administrativo: `{panel_url}`."
                ),
            ),
            ephemeral=True,
        )
        return True

    async def _provision_control_room(
        self,
        guild: discord.Guild,
        *,
        channel_name: str,
        operator_id: int,
        actor_label: str,
    ) -> dict[str, int]:
        topic = (
            "Central de comandos do bot. Somente o bot envia mensagens aqui. "
            "Use os botoes do painel fixado para controlar a reproducao."
        )
        bot_member = guild.me or guild.get_member(getattr(getattr(self.bot, "user", None), "id", 0))
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                send_messages=False,
                add_reactions=False,
                create_public_threads=False,
                create_private_threads=False,
                send_messages_in_threads=False,
            ),
        }
        if bot_member is not None:
            overwrites[bot_member] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_messages=True,
                read_message_history=True,
                embed_links=True,
                attach_files=True,
            )

        channel = discord.utils.get(guild.text_channels, name=channel_name)
        created = 0
        if channel is None:
            channel = await guild.create_text_channel(
                name=channel_name,
                topic=topic,
                overwrites=overwrites,
                reason=f"Criado por {actor_label} via control_room",
            )
            created = 1
        else:
            merged_overwrites = dict(channel.overwrites)
            merged_overwrites.update(overwrites)
            await channel.edit(topic=topic, overwrites=merged_overwrites, reason="Padronizacao da sala control_room")

        self._control_room_operator[guild.id] = operator_id
        self._control_room_push_history(guild.id, f"{actor_label} abriu/controlou a central")
        panel_message, reused_existing = await self._upsert_control_room_panel_message(
            guild,
            channel,
            operator_id=operator_id,
            pin_reason="Painel central do bot",
        )
        self._schedule_control_room_status_updater(guild.id)
        await self._upsert_voice_mini_panel(guild, channel, reason="control_room_bootstrap")
        return {
            "created": created,
            "reused_panel": reused_existing,
            "channel_id": channel.id,
            "message_id": panel_message.id,
        }

    async def _upsert_voice_mini_panel(
        self,
        guild: discord.Guild,
        text_channel: discord.abc.Messageable | None,
        *,
        reason: str = "",
    ) -> None:
        # Mini painel de voz foi descontinuado: centralizamos controles no NowPlaying.
        # Mantemos este método como compatibilidade para os fluxos antigos que ainda chamam ele.
        if reason:
            LOGGER.debug("Mini painel desativado no guild %s (motivo=%s)", guild.id, reason)
        await self._clear_voice_mini_panel(guild.id)
        if text_channel is None or not isinstance(text_channel, (discord.TextChannel, discord.Thread)):
            return
        try:
            await self._upsert_nowplaying_message(guild, text_channel)
            self._schedule_nowplaying_updater(guild)
        except Exception:
            LOGGER.debug("Falha ao atualizar nowplaying via alias de mini painel no guild %s", guild.id, exc_info=True)

    async def _clear_voice_mini_panel(self, guild_id: int) -> None:
        state = self._voice_mini_panel_state.pop(guild_id, None)
        if state is None:
            return
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return
        channel = guild.get_channel(state[0])
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        try:
            message = await channel.fetch_message(state[1])
            await message.delete()
        except Exception:
            return

    async def _apply_control_preset(self, guild_id: int, preset: str) -> tuple[str, int]:
        player = await self._get_player(guild_id)
        normalized = preset.strip().casefold()
        if normalized == "festa":
            player.volume = 1.20
            player.audio_filter = "bassboost"
            player.loop_mode = "queue"
            player.autoplay = True
        elif normalized == "chill":
            player.volume = 0.85
            player.audio_filter = "vaporwave"
            player.loop_mode = "off"
            player.autoplay = True
        elif normalized == "focus":
            player.volume = 0.70
            player.audio_filter = "off"
            player.loop_mode = "off"
            player.autoplay = False
        else:
            normalized = "padrao"
            player.volume = 1.0
            player.audio_filter = "off"
            player.loop_mode = "off"
            player.autoplay = False
        await self._save_player_settings(guild_id, player)
        return normalized, int(round(player.volume * 100))

    async def _build_control_room_embed(self, guild: discord.Guild) -> discord.Embed:
        player = await self._get_player(guild.id)
        queue_size = len(player.snapshot_queue())
        current = player.current
        status = self._player_state_label(guild.id)
        voice_client = guild.voice_client
        voice_channel = getattr(voice_client, "channel", None)
        voice_label = voice_channel.name if voice_channel else "desconectado"
        nowplaying = (
            f"**{current.title}**\n`{self._format_duration(current.duration_seconds)}` • "
            f"pedido por `{current.requested_by}`"
            if current
            else "Nenhuma musica em reproducao."
        )
        embed = self._embed(
            "🎛️ Control Room",
            "Central operacional do player (somente bot escreve aqui).",
            color=self._theme_color("admin"),
        )
        embed.add_field(
            name="📡 Estado",
            value=(
                f"• Status: `{status}`\n"
                f"• Canal de voz: `{voice_label}`\n"
                f"• Fila pendente: `{queue_size}`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🎶 Agora",
            value=nowplaying,
            inline=False,
        )
        embed.add_field(
            name="⚙️ Ajustes",
            value=(
                f"• Volume: `{int(round(player.volume * 100))}%`\n"
                f"• Filtro: `{player.audio_filter}`\n"
                f"• Loop: `{player.loop_mode}` • Autoplay: `{'on' if player.autoplay else 'off'}`"
            ),
            inline=False,
        )
        recent = self._control_room_recent_history(guild.id, limit=5)
        if recent:
            embed.add_field(name="🧾 Historico", value="\n".join(f"• {item}" for item in recent), inline=False)
        embed.set_footer(text=f"Guild: {guild.name} • Atualizacao automatica ativa")
        return embed

    async def _control_room_message(self, guild_id: int) -> discord.Message | None:
        state = await self.store.get_control_room_state(guild_id)
        if state is None:
            return None
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return None
        channel = guild.get_channel(state.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return None
        try:
            return await channel.fetch_message(state.message_id)
        except Exception:
            return None

    async def _refresh_control_room_panel(self, guild_id: int) -> bool:
        message = await self._control_room_message(guild_id)
        if message is None:
            return False
        guild = message.guild
        if guild is None:
            return False
        operator_id = self._control_room_operator.get(guild_id, 0)
        embed = await self._build_control_room_embed(guild)
        try:
            await message.edit(embed=embed, view=ControlRoomView(self, guild_id, operator_user_id=operator_id))
            return True
        except Exception:
            return False

    def _cancel_control_room_status_updater(self, guild_id: int) -> None:
        task = self._control_room_status_tasks.pop(guild_id, None)
        if task and not task.done():
            task.cancel()

    def _schedule_control_room_status_updater(self, guild_id: int) -> None:
        self._cancel_control_room_status_updater(guild_id)

        async def worker() -> None:
            while True:
                try:
                    await asyncio.sleep(self.control_room_status_interval_seconds)
                    ok = await self._refresh_control_room_panel(guild_id)
                    if not ok:
                        return
                except asyncio.CancelledError:
                    return
                except Exception:
                    return

        self._control_room_status_tasks[guild_id] = self.bot.loop.create_task(worker())

    async def _restore_control_room_panels(self) -> None:
        restored_guild_ids: set[int] = set()
        try:
            rows = await self.store.list_control_room_states()
        except Exception:
            rows = []
        for row in rows:
            guild = self.bot.get_guild(row.guild_id)
            if guild is None:
                continue
            channel = guild.get_channel(row.channel_id)
            if not isinstance(channel, discord.TextChannel):
                await self.store.delete_control_room_state(row.guild_id)
                continue
            try:
                message = await channel.fetch_message(row.message_id)
            except Exception:
                message = None
            if message is None:
                # auto-repair no startup
                try:
                    message, _ = await self._upsert_control_room_panel_message(
                        guild,
                        channel,
                        operator_id=int(row.operator_user_id),
                        expected_message_id=row.message_id,
                        pin_reason="Painel central do bot (auto-repair)",
                    )
                except Exception:
                    continue
            self._control_room_state_cache[guild.id] = (channel.id, message.id)
            self._control_room_operator[guild.id] = int(row.operator_user_id)
            self.bot.add_view(ControlRoomView(self, guild.id, operator_user_id=int(row.operator_user_id)), message_id=message.id)
            self._schedule_control_room_status_updater(guild.id)
            restored_guild_ids.add(guild.id)
            LOGGER.info(
                "control_room startup_restore guild=%s channel=%s message=%s",
                guild.id,
                channel.id,
                message.id,
            )

        # Fallback de startup: se existir a sala/painel no Discord, reaproveita mesmo sem estado persistido.
        for guild in self.bot.guilds:
            if guild.id in restored_guild_ids:
                continue
            LOGGER.info("control_room startup_scan guild=%s channels=%s", guild.id, len(guild.text_channels))
            channel: discord.TextChannel | None = None
            panel_message: discord.Message | None = None
            preferred = discord.utils.get(guild.text_channels, name="bot-controle")
            candidate_channels: list[discord.TextChannel] = []
            if isinstance(preferred, discord.TextChannel):
                candidate_channels.append(preferred)
            candidate_channels.extend(
                text_channel
                for text_channel in guild.text_channels
                if preferred is None or text_channel.id != preferred.id
            )
            for candidate in candidate_channels:
                try:
                    panel_message = await asyncio.wait_for(
                        self._find_control_room_panel_message(guild, candidate),
                        timeout=2.0,
                    )
                except asyncio.TimeoutError:
                    LOGGER.warning(
                        "control_room startup_scan_timeout guild=%s channel=%s",
                        guild.id,
                        candidate.id,
                    )
                    continue
                except Exception:
                    LOGGER.warning(
                        "control_room startup_scan_error guild=%s channel=%s",
                        guild.id,
                        candidate.id,
                        exc_info=True,
                    )
                    continue
                if panel_message is None:
                    continue
                channel = candidate
                break
            if channel is None:
                LOGGER.info("control_room startup_scan_miss guild=%s", guild.id)
                continue
            LOGGER.info(
                "control_room startup_scan_hit guild=%s channel=%s message=%s",
                guild.id,
                channel.id,
                panel_message.id if panel_message else 0,
            )
            if panel_message is None:
                continue
            operator_id = int(self._control_room_operator.get(guild.id, 0))
            try:
                message, reused_existing = await self._upsert_control_room_panel_message(
                    guild,
                    channel,
                    operator_id=operator_id,
                    expected_message_id=panel_message.id,
                    pin_reason="Painel central do bot (startup-sync)",
                )
            except Exception:
                continue
            self._control_room_state_cache[guild.id] = (channel.id, message.id)
            self._control_room_operator[guild.id] = operator_id
            self._schedule_control_room_status_updater(guild.id)
            LOGGER.info(
                "control_room startup_sync guild=%s channel=%s reused=%s",
                guild.id,
                channel.id,
                reused_existing,
            )

    async def _recreate_control_room_panel(self, guild_id: int) -> bool:
        state = await self.store.get_control_room_state(guild_id)
        if state is None:
            return False
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return False
        channel = guild.get_channel(state.channel_id)
        if not isinstance(channel, discord.TextChannel):
            await self.store.delete_control_room_state(guild_id)
            self._control_room_state_cache.pop(guild_id, None)
            self._control_room_operator.pop(guild_id, None)
            self._cancel_control_room_status_updater(guild_id)
            return False
        operator_id = int(state.operator_user_id)
        self._control_room_operator[guild_id] = operator_id
        try:
            message, _ = await self._upsert_control_room_panel_message(
                guild,
                channel,
                operator_id=operator_id,
                expected_message_id=state.message_id,
                pin_reason="Painel central do bot (auto-repair)",
            )
            self._schedule_control_room_status_updater(guild_id)
            return True
        except Exception:
            return False

    @app_commands.command(name="control_room", description="(Teste) Cria a sala central de comandos do bot.")
    @app_commands.describe(nome="Nome do canal de texto que sera criado/usado")
    async def control_room(self, interaction: discord.Interaction, nome: str = "bot-controle") -> None:
        if await self._reject_if_admin_slash_disabled(interaction, "control_room"):
            return
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

        channel_name = (nome or "bot-controle").strip().lower().replace(" ", "-")
        if not channel_name:
            channel_name = "bot-controle"

        operator_id = interaction.user.id if interaction.user else 0
        result = await self._provision_control_room(
            guild,
            channel_name=channel_name,
            operator_id=operator_id,
            actor_label=interaction.user.display_name if interaction.user else "user",
        )

        await self._send_response(
            interaction,
            embed=self._ok_embed(
                "Sala de controle pronta",
                (
                    f"{'Canal criado' if result['created'] else 'Canal reutilizado'}: <#{result['channel_id']}>\n"
                    f"Painel {'reaproveitado e atualizado' if result['reused_panel'] else 'publicado e fixado'}.\n"
                    f"Operador atual: <@{operator_id}>."
                ),
            ),
            ephemeral=True,
        )

    @app_commands.command(name="metrics", description="Mostra metricas basicas do bot.")
    async def metrics(self, interaction: discord.Interaction) -> None:
        if await self._reject_if_admin_slash_disabled(interaction, "metrics"):
            return
        if not await self._require_control_permissions(interaction):
            return

        snapshot = self._metrics_snapshot()
        bot_name = getattr(getattr(self.bot, "user", None), "display_name", None) or getattr(
            getattr(self.bot, "user", None), "name", "Bot"
        )
        embed = self._embed(
            f"📊 Metricas do {bot_name}",
            "Visao geral de uso e saude do bot.",
            color=self._theme_color("metrics"),
        )
        embed.add_field(
            name="📈 Comandos",
            value=(
                f"• Executados: `{snapshot.command_calls}`\n"
                f"• Erros: `{snapshot.command_errors}`\n"
                f"• Latencia media: `{snapshot.average_latency_ms:.1f} ms`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🎵 Player",
            value=(
                f"• Falhas extracao: `{snapshot.extraction_failures}`\n"
                f"• Falhas playback: `{snapshot.playback_failures}`\n"
                f"• Queue max: `{self.max_queue_size}`\n"
                f"• Playlist import max: `{self.max_playlist_import}`"
            ),
            inline=False,
        )
        embed.add_field(
            name="⏱️ Janela 5m",
            value=(
                f"• /play avg (5m): `{self._command_metrics_window.avg_ms('play', window_seconds=300):.1f} ms`\n"
                f"• /play p95/p99 (5m): `{self._command_metrics_window.percentile_ms('play', 95, window_seconds=300):.1f}` / "
                f"`{self._command_metrics_window.percentile_ms('play', 99, window_seconds=300):.1f} ms`\n"
                f"• /search avg (5m): `{self._command_metrics_window.avg_ms('search', window_seconds=300):.1f} ms`\n"
                f"• /search p95/p99 (5m): `{self._command_metrics_window.percentile_ms('search', 95, window_seconds=300):.1f}` / "
                f"`{self._command_metrics_window.percentile_ms('search', 99, window_seconds=300):.1f} ms`\n"
                f"• /playlist_load avg (5m): `{self._command_metrics_window.avg_ms('playlist_load', window_seconds=300):.1f} ms`"
            ),
            inline=False,
        )
        await self._send_response(interaction, embed=embed, ephemeral=True)

    @app_commands.command(name="cache", description="Mostra/limpa caches de busca e autocomplete (admin).")
    @app_commands.describe(
        acao="show, clear_search, clear_autocomplete, clear_all",
    )
    async def cache(self, interaction: discord.Interaction, acao: str = "show") -> None:
        if await self._reject_if_admin_slash_disabled(interaction, "cache"):
            return
        if not await self._require_control_permissions(interaction):
            return
        action = acao.strip().casefold()
        if action == "show":
            embed = self._embed(
                "🧠 Cache",
                "Estado atual dos caches do bot.",
                color=self._theme_color("metrics"),
            )
            embed.add_field(name="Resumo", value=self._cache_stats_summary(), inline=False)
            await self._send_response(interaction, embed=embed, ephemeral=True)
            return

        if action == "clear_search":
            self._search_cache.clear()
        elif action == "clear_autocomplete":
            self._autocomplete_rank_cache.clear()
        elif action == "clear_all":
            self._search_cache.clear()
            self._autocomplete_rank_cache.clear()
        else:
            await self._send_response(
                interaction,
                embed=self._warn_embed("Acao invalida", "Use: `show`, `clear_search`, `clear_autocomplete` ou `clear_all`."),
                ephemeral=True,
            )
            return

        await self._send_response(
            interaction,
            embed=self._ok_embed("Cache atualizado", f"Acao aplicada: `{action}`.\n{self._cache_stats_summary()}"),
            ephemeral=True,
        )

    @app_commands.command(name="moderation", description="Configura moderacao por duracao e dominios.")
    @app_commands.describe(
        acao="show, set_duration, add_whitelist, remove_whitelist, add_blacklist, remove_blacklist, clear_whitelist, clear_blacklist",
        valor="Dominio para adicionar/remover (quando aplicavel)",
        segundos="Duracao maxima em segundos para set_duration (0 desativa)",
    )
    async def moderation(
        self,
        interaction: discord.Interaction,
        acao: str,
        valor: str | None = None,
        segundos: int | None = None,
    ) -> None:
        if await self._reject_if_admin_slash_disabled(interaction, "moderation"):
            return
        if not await self._require_control_permissions(interaction):
            return
        guild = interaction.guild
        if guild is None:
            await self._send_response(interaction, 
                embed=self._warn_embed("Comando indisponivel", "Esse comando so funciona em servidor."),
                ephemeral=True,
            )
            return
        player = await self._get_player(guild.id)
        policy = self._policy_for_guild(guild.id)
        action = acao.strip().casefold()
        domain = (valor or "").strip().casefold()

        if action == "show":
            whitelist = ", ".join(sorted(policy.domain_whitelist)) if policy.domain_whitelist else "vazia"
            blacklist = ", ".join(sorted(policy.domain_blacklist)) if policy.domain_blacklist else "vazia"
            await self._send_response(interaction, 
                embed=self._embed(
                    "🛡️ Moderacao",
                    (
                        f"max_duracao: `{policy.max_track_duration_seconds or 0}`\n"
                        f"whitelist: {whitelist}\n"
                        f"blacklist: {blacklist}"
                    ),
                    color=self._theme_color("admin"),
                ),
                ephemeral=True,
            )
            return

        if action == "set_duration":
            if segundos is None or segundos < 0:
                await self._send_response(interaction, 
                    embed=self._warn_embed("Valor invalido", "Informe `segundos` >= 0."),
                    ephemeral=True,
                )
                return
            policy.max_track_duration_seconds = int(segundos)
        elif action == "add_whitelist":
            if not domain:
                await self._send_response(interaction, 
                    embed=self._warn_embed("Dominio invalido", "Informe `valor` com o dominio."),
                    ephemeral=True,
                )
                return
            policy.domain_whitelist.add(domain)
        elif action == "remove_whitelist":
            if not domain:
                await self._send_response(interaction, 
                    embed=self._warn_embed("Dominio invalido", "Informe `valor` com o dominio."),
                    ephemeral=True,
                )
                return
            policy.domain_whitelist.discard(domain)
        elif action == "add_blacklist":
            if not domain:
                await self._send_response(interaction, 
                    embed=self._warn_embed("Dominio invalido", "Informe `valor` com o dominio."),
                    ephemeral=True,
                )
                return
            policy.domain_blacklist.add(domain)
        elif action == "remove_blacklist":
            if not domain:
                await self._send_response(interaction, 
                    embed=self._warn_embed("Dominio invalido", "Informe `valor` com o dominio."),
                    ephemeral=True,
                )
                return
            policy.domain_blacklist.discard(domain)
        elif action == "clear_whitelist":
            policy.domain_whitelist.clear()
        elif action == "clear_blacklist":
            policy.domain_blacklist.clear()
        else:
            await self._send_response(interaction, 
                embed=self._warn_embed("Acao invalida", "Use uma acao valida de moderacao."),
                ephemeral=True,
            )
            return

        self._guild_policy[guild.id] = policy
        await self._save_player_settings(guild.id, player)
        await self._send_response(interaction, 
            embed=self._ok_embed("Moderacao atualizada", self._policy_summary(guild.id)),
            ephemeral=True,
        )

    @app_commands.command(name="diagnostics", description="Mostra diagnostico de dependencias e integracoes.")
    async def diagnostics(self, interaction: discord.Interaction) -> None:
        if await self._reject_if_admin_slash_disabled(interaction, "diagnostics"):
            return
        await self._send_response(interaction, embed=self._build_diagnostics_embed(interaction), ephemeral=True)

    @app_commands.command(name="diagnostico", description="Mostra diagnostico tecnico rapido do bot.")
    async def diagnostico(self, interaction: discord.Interaction) -> None:
        if await self._reject_if_admin_slash_disabled(interaction, "diagnostico"):
            return
        await self._send_response(interaction, embed=self._build_diagnostics_embed(interaction), ephemeral=True)

    def _build_diagnostics_embed(self, interaction: discord.Interaction) -> discord.Embed:
        guild = interaction.guild
        guild_id = guild.id if guild else 0
        ffmpeg_path = shutil.which("ffmpeg") or "nao encontrado"
        deno_path = shutil.which("deno") or "nao encontrado"
        node_path = shutil.which("node") or "nao encontrado"
        discord_ping_ms = getattr(self.bot, "latency", 0.0) * 1000
        search_avg = self._command_metrics_window.avg_ms("search", window_seconds=300)
        play_avg = self._command_metrics_window.avg_ms("play", window_seconds=300)
        search_p99 = self._command_metrics_window.percentile_ms("search", 99, window_seconds=300)
        play_p99 = self._command_metrics_window.percentile_ms("play", 99, window_seconds=300)
        search_cache_stage_avg = self._avg_stage_latency_ms("cache")
        search_resolver_stage_avg = self._avg_stage_latency_ms("resolver")
        player = self.music.get_player(guild_id) if guild_id else None
        queue_size = len(player.snapshot_queue()) if player is not None else 0
        in_memory_cache = len(self._search_cache)
        jobs_queue = getattr(self.music, "_extract_jobs", None)
        worker_backlog = jobs_queue.qsize() if jobs_queue is not None else 0
        workers_total = len(getattr(self.music, "_extract_workers", []))

        embed = self._embed(
            "🧪 Diagnostico",
            "Checagem tecnica do ambiente atual.",
            color=self._theme_color("diagnostics"),
        )
        embed.add_field(
            name="🔧 Dependencias",
            value=(
                f"• Opus: `{'loaded' if discord.opus.is_loaded() else 'not_loaded'}`\n"
                f"• ffmpeg: `{ffmpeg_path}`\n"
                f"• deno: `{deno_path}`\n"
                f"• node: `{node_path}`"
            ),
            inline=False,
        )
        embed.add_field(
            name="⚡ Runtime",
            value=(
                f"• Discord ping: `{discord_ping_ms:.1f} ms`\n"
                f"• Painel web: `{'on' if self.web_panel_enabled else 'off'}`\n"
                f"• Bind: `{self.web_panel_host}:{self.web_panel_port}`\n"
                f"• Repository: `{getattr(self.bot, 'repository_backend', 'sqlite')}`\n"
                f"• DB: `{getattr(self.bot, 'db_path', 'botmusica.db')}`\n"
                "• Audio backend: `native_ffmpeg`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🎯 Performance",
            value=(
                f"• /play avg: `{play_avg:.1f} ms`\n"
                f"• /play p99: `{play_p99:.1f} ms`\n"
                f"• /search avg: `{search_avg:.1f} ms`\n"
                f"• /search p99: `{search_p99:.1f} ms`\n"
                f"• Search stage avg: cache=`{search_cache_stage_avg:.1f} ms` "
                f"resolver=`{search_resolver_stage_avg:.1f} ms`\n"
                f"• Queue atual: `{queue_size}`\n"
                f"• Search cache (mem): `{in_memory_cache}` entradas\n"
                f"• Workers yt-dlp: `{workers_total}` backlog=`{worker_backlog}`"
            ),
            inline=False,
        )
        embed.add_field(name="🛡️ Moderacao", value=self._policy_summary(guild_id), inline=False)
        embed.add_field(
            name="Rate limit",
            value=(
                f"user: `{self.play_user_max_requests}/{self.play_user_window_seconds}s` | "
                f"guild: `{self.play_guild_max_requests}/{self.play_guild_window_seconds}s`\n"
                f"search user/guild: `{self.search_user_max_requests}/{self.search_user_window_seconds}s` • "
                f"`{self.search_guild_max_requests}/{self.search_guild_window_seconds}s`\n"
                f"playlist_load user/guild: `{self.playlist_load_user_max_requests}/{self.playlist_load_user_window_seconds}s` • "
                f"`{self.playlist_load_guild_max_requests}/{self.playlist_load_guild_window_seconds}s`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Provider Circuit",
            value=(
                f"extract=`{self._provider_breakers['extract'].state}` "
                f"search=`{self._provider_breakers['search'].state}`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Feature Flags",
            value=(
                f"playlist_jobs=`{self.feature_flags.playlist_jobs_enabled}` "
                f"play_progress=`{self.feature_flags.play_progress_updates}` "
                f"backpressure=`{self.feature_flags.extraction_backpressure_enabled}`\n"
                f"reconnect_strategy=`{self.feature_flags.reconnect_strategy_enabled}` "
                f"command_service=`{self.feature_flags.command_service_enabled}` "
                f"np_compact=`{self.feature_flags.nowplaying_compact_enabled}`"
            ),
            inline=False,
        )
        return embed

    @app_commands.command(name="help", description="Mostra ajuda interativa com categorias de comandos.")
    async def help(self, interaction: discord.Interaction) -> None:
        author_id = interaction.user.id if interaction.user else 0
        view = HelpView(self, author_id=author_id, initial="geral")
        embed = self._build_help_embed("geral")
        await self._send_response(interaction, embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="disconnect", description="Desconecta o bot do canal de voz.")
    async def disconnect(self, interaction: discord.Interaction) -> None:
        if await self._reject_if_admin_slash_disabled(interaction, "disconnect"):
            return
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
        voice_client = guild.voice_client
        if not self._is_voice_connected(voice_client):
            await self._send_response(interaction, 
                embed=self._warn_embed("Sem conexao", "O bot nao esta conectado."),
                ephemeral=True,
            )
            return

        player = await self._get_player(guild.id)
        lock = self._get_lock(guild.id)
        async with lock:
            self.queue_service.clear(player)
            player.current = None
            player.current_started_at = None
            player.pause_started_at = None
            player.paused_accumulated_seconds = 0.0
            player.suppress_after_playback = True
        self._cancel_nowplaying_updater(guild.id)
        await self._persist_queue_state(guild.id, player)
        await self._record_queue_event(guild.id, "disconnect")
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
        await self._send_response(interaction, embed=self._ok_embed("Disconnect", "Desconectado do canal de voz."))
