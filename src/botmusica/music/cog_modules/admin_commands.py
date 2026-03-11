from __future__ import annotations

import asyncio
import logging
import os
import shutil

import discord
from discord import app_commands

try:
    import wavelink
except ImportError:
    wavelink = None

from botmusica.music.views import ControlRoomView, HelpView
from botmusica.music.storage import ControlRoomStateRecord

LOGGER = logging.getLogger("botmusica.music")


class AdminCommandsMixin:
    async def _cleanup_legacy_control_room_channels(self, guild: discord.Guild, *, keep_channel_id: int) -> int:
        removed = 0
        legacy_name = "bot-controle"
        current_default = str(getattr(self, "control_room_default_channel_name", legacy_name)).strip().casefold()
        if current_default == legacy_name:
            return 0
        bot_member = guild.me or guild.get_member(getattr(getattr(self.bot, "user", None), "id", 0))
        if bot_member is None or not bot_member.guild_permissions.manage_channels:
            return 0
        for channel in list(guild.text_channels):
            if channel.id == keep_channel_id:
                continue
            if channel.name.strip().casefold() != legacy_name:
                continue
            try:
                await channel.delete(reason="Remocao automatica de canal legado control_room")
                removed += 1
            except Exception:
                continue
        return removed

    async def _clear_control_room_channel_history(self, channel: discord.TextChannel) -> int:
        deleted = 0
        # Remove mensagens antigas uma a uma para garantir limpeza completa do historico.
        while True:
            batch: list[discord.Message] = []
            try:
                async for message in channel.history(limit=100):
                    batch.append(message)
            except Exception:
                break
            if not batch:
                break
            for message in batch:
                try:
                    await message.delete()
                    deleted += 1
                except discord.Forbidden:
                    continue
                except discord.NotFound:
                    continue
                except Exception:
                    continue
        return deleted

    async def _bootstrap_control_rooms_on_ready(self) -> None:
        await self.bot.wait_until_ready()
        # Aguarda cache de guilds estabilizar apos reconnect/startup.
        await asyncio.sleep(1.0)
        for guild in list(self.bot.guilds):
            try:
                result = await self._provision_control_room(
                    guild,
                    channel_name=str(getattr(self, "control_room_default_channel_name", "bot-controle")),
                    operator_id=0,
                    actor_label="startup",
                    clear_history=True,
                )
                legacy_removed = await self._cleanup_legacy_control_room_channels(
                    guild,
                    keep_channel_id=int(result.get("channel_id", 0)),
                )
                LOGGER.info(
                    "control_room bootstrap guild=%s channel=%s created=%s cleared=%s legacy_removed=%s",
                    guild.id,
                    result.get("channel_id", 0),
                    result.get("created", 0),
                    result.get("cleared_messages", 0),
                    legacy_removed,
                )
            except Exception:
                LOGGER.warning("Falha ao bootstrap control_room no guild %s", guild.id, exc_info=True)

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
        clear_history: bool = False,
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

        self._control_room_maintenance.add(guild.id)
        try:
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

            removed_panels = 0
            cleared_messages = 0
            if clear_history:
                cleared_messages = await self._clear_control_room_channel_history(channel)
            else:
                bot_user_id = getattr(getattr(self.bot, "user", None), "id", 0)
                panel_titles = {"🎛️ Control Room", "🎛️ Central de Comandos"}
                try:
                    async for message in channel.history(limit=200):
                        if not message.author or message.author.id != bot_user_id:
                            continue
                        if not message.embeds:
                            continue
                        title = (message.embeds[0].title or "").strip()
                        if title not in panel_titles:
                            continue
                        try:
                            await message.delete()
                            removed_panels += 1
                        except Exception:
                            continue
                except Exception:
                    pass

            self._control_room_operator[guild.id] = operator_id
            self._control_room_push_history(guild.id, f"{actor_label} abriu/controlou a central")
            view = ControlRoomView(self, guild.id, operator_user_id=operator_id)
            embed = await self._build_control_room_embed(guild)
            panel_message = await channel.send(embed=embed, view=view)
            try:
                await panel_message.pin(reason="Painel central do bot")
            except Exception:
                pass
            await self.store.upsert_control_room_state(
                ControlRoomStateRecord(
                    guild_id=guild.id,
                    channel_id=channel.id,
                    message_id=panel_message.id,
                    operator_user_id=operator_id,
                )
            )
            self._control_room_state_cache[guild.id] = (channel.id, panel_message.id)
            self.bot.add_view(ControlRoomView(self, guild.id, operator_user_id=operator_id), message_id=panel_message.id)
            self._schedule_control_room_status_updater(guild.id)
            await self._upsert_voice_mini_panel(guild, channel, reason="control_room_bootstrap")
            return {
                "created": created,
                "removed_panels": removed_panels,
                "cleared_messages": cleared_messages,
                "channel_id": channel.id,
                "message_id": panel_message.id,
            }
        finally:
            self._control_room_maintenance.discard(guild.id)

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
        try:
            rows = await self.store.list_control_room_states()
        except Exception:
            return
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
                    embed = await self._build_control_room_embed(guild)
                    view = ControlRoomView(self, guild.id, operator_user_id=row.operator_user_id)
                    message = await channel.send(embed=embed, view=view)
                    try:
                        await message.pin(reason="Painel central do bot (auto-repair)")
                    except Exception:
                        pass
                    await self.store.upsert_control_room_state(
                        ControlRoomStateRecord(
                            guild_id=guild.id,
                            channel_id=channel.id,
                            message_id=message.id,
                            operator_user_id=row.operator_user_id,
                        )
                    )
                except Exception:
                    continue
            self._control_room_state_cache[guild.id] = (channel.id, message.id)
            self._control_room_operator[guild.id] = int(row.operator_user_id)
            self.bot.add_view(ControlRoomView(self, guild.id, operator_user_id=int(row.operator_user_id)), message_id=message.id)
            self._schedule_control_room_status_updater(guild.id)

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
        embed = await self._build_control_room_embed(guild)
        view = ControlRoomView(self, guild_id, operator_user_id=operator_id)
        try:
            message = await channel.send(embed=embed, view=view)
            try:
                await message.pin(reason="Painel central do bot (auto-repair)")
            except Exception:
                pass
            await self.store.upsert_control_room_state(
                ControlRoomStateRecord(
                    guild_id=guild_id,
                    channel_id=channel.id,
                    message_id=message.id,
                    operator_user_id=operator_id,
                )
            )
            self._control_room_state_cache[guild_id] = (channel.id, message.id)
            self.bot.add_view(ControlRoomView(self, guild_id, operator_user_id=operator_id), message_id=message.id)
            self._schedule_control_room_status_updater(guild_id)
            return True
        except Exception:
            return False

    async def _assign_dj_role_to_member(
        self,
        *,
        guild: discord.Guild,
        actor: discord.abc.User,
        target_member: discord.Member,
        dj_role: discord.Role,
    ) -> tuple[bool, str]:
        bot_member = guild.me or guild.get_member(getattr(getattr(self.bot, "user", None), "id", 0))
        if bot_member is None:
            return False, "Nao consegui validar a identidade do bot neste servidor."
        if not bot_member.guild_permissions.manage_roles:
            return False, "O bot precisa da permissao `Manage Roles` para atribuir cargos."

        # Hierarquia do Discord: o bot so pode gerenciar cargos abaixo do maior cargo dele.
        if dj_role >= bot_member.top_role:
            return (
                False,
                "Nao posso atribuir o cargo DJ porque ele esta acima (ou igual) ao meu maior cargo na hierarquia.",
            )

        # Tambem nao e possivel alterar cargos de membros com cargo maior/igual ao do bot.
        if target_member != guild.owner and target_member.top_role >= bot_member.top_role:
            return (
                False,
                "Nao posso editar cargos desse usuario por causa da hierarquia de cargos.",
            )

        if dj_role in target_member.roles:
            return True, f"O usuario <@{target_member.id}> ja possui o cargo DJ."

        try:
            await target_member.add_roles(
                dj_role,
                reason=f"Atribuicao automatica de DJ por {getattr(actor, 'display_name', 'admin')} via setup_music_role",
            )
            return True, f"Cargo DJ atribuido para <@{target_member.id}> com sucesso."
        except discord.Forbidden:
            return False, "Permissao insuficiente para atribuir o cargo DJ. Verifique permissoes e hierarquia."
        except discord.HTTPException:
            return False, "Falha de API ao atribuir o cargo DJ. Tente novamente em alguns segundos."

    @app_commands.command(name="setup_music_role", description="Cria o cargo DJ para comandos avancados de musica.")
    @app_commands.describe(usuario="Usuario para receber o cargo DJ apos a criacao (opcional)")
    async def setup_music_role(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member | None = None,
    ) -> None:
        if await self._reject_if_admin_slash_disabled(interaction, "setup_music_role"):
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

        bot_member = guild.me or guild.get_member(getattr(getattr(self.bot, "user", None), "id", 0))
        if bot_member is None:
            await self._send_response(
                interaction,
                embed=self._error_embed("Estado invalido", "Nao consegui validar as permissoes do bot neste servidor."),
                ephemeral=True,
            )
            return

        # Para criar e gerenciar cargos, o bot precisa explicitamente de Manage Roles.
        if not bot_member.guild_permissions.manage_roles:
            await self._send_response(
                interaction,
                embed=self._warn_embed(
                    "Permissao necessaria",
                    "Preciso da permissao `Manage Roles` para criar o cargo DJ.",
                ),
                ephemeral=True,
            )
            return

        existing_role = discord.utils.get(guild.roles, name="DJ")
        if existing_role is not None:
            await self._send_response(
                interaction,
                embed=self._warn_embed(
                    "Cargo existente",
                    (
                        f"O cargo **DJ** ja existe neste servidor.\n"
                        f"ID do cargo: `{existing_role.id}`"
                    ),
                ),
                ephemeral=True,
            )
            return

        try:
            # O cargo nasce com permissao de administrador para centralizar controle de comandos avancados.
            permissions = discord.Permissions.none()
            permissions.administrator = True
            dj_role = await guild.create_role(
                name="DJ",
                color=discord.Color.blurple(),
                hoist=True,
                mentionable=True,
                permissions=permissions,
                reason=f"Criado por {interaction.user.display_name if interaction.user else 'admin'} via setup_music_role",
            )
        except discord.Forbidden:
            await self._send_response(
                interaction,
                embed=self._error_embed(
                    "Falha ao criar cargo",
                    "Permissao insuficiente para criar o cargo DJ. Verifique `Manage Roles` e hierarquia do bot.",
                ),
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            await self._send_response(
                interaction,
                embed=self._error_embed("Falha ao criar cargo", "A API do Discord recusou a criacao do cargo DJ."),
                ephemeral=True,
            )
            return

        details = (
            f"Cargo **DJ** criado com sucesso.\n"
            f"ID do cargo: `{dj_role.id}`\n"
            "Esse cargo pode ser usado para controlar comandos avancados de musica."
        )
        if usuario is not None and isinstance(interaction.user, discord.abc.User):
            assigned, assign_message = await self._assign_dj_role_to_member(
                guild=guild,
                actor=interaction.user,
                target_member=usuario,
                dj_role=dj_role,
            )
            status_prefix = "Atribuicao automatica" if assigned else "Atribuicao automatica falhou"
            details = f"{details}\n\n{status_prefix}: {assign_message}"

        await self._send_response(
            interaction,
            embed=self._ok_embed("Cargo DJ configurado", details),
            ephemeral=True,
        )

    @app_commands.command(name="assign_dj_role", description="Atribui o cargo DJ para um usuario especifico.")
    @app_commands.describe(usuario="Usuario que recebera o cargo DJ")
    async def assign_dj_role(self, interaction: discord.Interaction, usuario: discord.Member) -> None:
        if await self._reject_if_admin_slash_disabled(interaction, "assign_dj_role"):
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

        dj_role = discord.utils.get(guild.roles, name="DJ")
        if dj_role is None:
            await self._send_response(
                interaction,
                embed=self._warn_embed("Cargo nao encontrado", "Execute `/setup_music_role` para criar o cargo DJ primeiro."),
                ephemeral=True,
            )
            return

        if not isinstance(interaction.user, discord.abc.User):
            await self._send_response(
                interaction,
                embed=self._error_embed("Permissao", "Nao consegui validar o usuario que executou o comando."),
                ephemeral=True,
            )
            return

        assigned, assign_message = await self._assign_dj_role_to_member(
            guild=guild,
            actor=interaction.user,
            target_member=usuario,
            dj_role=dj_role,
        )
        embed_factory = self._ok_embed if assigned else self._warn_embed
        title = "Cargo DJ atribuido" if assigned else "Nao foi possivel atribuir"
        await self._send_response(interaction, embed=embed_factory(title, assign_message), ephemeral=True)

    @app_commands.command(name="control_room", description="(Teste) Cria a sala central de comandos do bot.")
    @app_commands.describe(nome="Nome do canal de texto que sera criado/usado")
    async def control_room(self, interaction: discord.Interaction, nome: str | None = None) -> None:
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

        default_name = str(getattr(self, "control_room_default_channel_name", "bot-controle"))
        channel_name = (nome or default_name).strip().lower().replace(" ", "-")
        if not channel_name:
            channel_name = default_name

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
                    f"Painel publicado e fixado. Paineis antigos removidos: `{result['removed_panels']}`.\n"
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
        lavalink_enabled = os.getenv("LAVALINK_ENABLED", "false").strip().casefold() in {"1", "true", "yes", "on"}
        lavalink_host = os.getenv("LAVALINK_HOST", "lavalink").strip() or "lavalink"
        lavalink_port = os.getenv("LAVALINK_PORT", "2333").strip() or "2333"
        discord_ping_ms = getattr(self.bot, "latency", 0.0) * 1000
        search_avg = self._command_metrics_window.avg_ms("search", window_seconds=300)
        play_avg = self._command_metrics_window.avg_ms("play", window_seconds=300)
        search_p99 = self._command_metrics_window.percentile_ms("search", 99, window_seconds=300)
        play_p99 = self._command_metrics_window.percentile_ms("play", 99, window_seconds=300)
        search_cache_stage_avg = self._avg_stage_latency_ms("cache")
        search_lavalink_stage_avg = self._avg_stage_latency_ms("lavalink")
        search_resolver_stage_avg = self._avg_stage_latency_ms("resolver")
        player = self.music.get_player(guild_id) if guild_id else None
        queue_size = len(player.snapshot_queue()) if player is not None else 0
        in_memory_cache = len(self._search_cache)
        jobs_queue = getattr(self.music, "_extract_jobs", None)
        worker_backlog = jobs_queue.qsize() if jobs_queue is not None else 0
        workers_total = len(getattr(self.music, "_extract_workers", []))

        lavalink_status = "off"
        lavalink_nodes = 0
        lavalink_players = 0
        if wavelink is not None:
            pool = getattr(wavelink, "Pool", None)
            nodes = getattr(pool, "nodes", {}) if pool is not None else {}
            if isinstance(nodes, dict):
                lavalink_nodes = len(nodes)
                lavalink_players = sum(len(getattr(node, "players", {})) for node in nodes.values())
                lavalink_status = "connected" if lavalink_nodes > 0 else "connecting"

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
                f"• Lavalink cfg: `{'on' if lavalink_enabled else 'off'}` (`{lavalink_host}:{lavalink_port}`)\n"
                f"• Lavalink pool: `{lavalink_status}` nodes=`{lavalink_nodes}` players=`{lavalink_players}`"
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
                f"lavalink=`{search_lavalink_stage_avg:.1f} ms` resolver=`{search_resolver_stage_avg:.1f} ms`\n"
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
                f"search=`{self._provider_breakers['search'].state}` "
                f"lavalink_search=`{self._provider_breakers['lavalink_search'].state}`"
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
