from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from botmusica.music.command_domains import command_domain

LOGGER = logging.getLogger("botmusica.music")


class EventHandlersMixin:
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Detect when the bot is left alone in a voice channel and auto-disconnect."""
        # Ignore the bot's own state changes for the alone-check logic.
        if member.id == self.bot.user.id:
            # If the bot was disconnected externally, clean up state.
            if before.channel is not None and after.channel is None and member.guild.id not in self._voice_refresh_in_progress:
                guild = member.guild
                player = await self._get_player(guild.id)
                await self._persist_queue_state(guild.id, player)
                self._cancel_prefetch(guild.id)
                self._cancel_idle_timer(guild.id)
                self._cancel_playback_watchdog(guild.id)
                await self._clear_votes_for_guild(guild.id)
                await self._clear_nowplaying_message(guild.id)
                await self._clear_voice_mini_panel(guild.id)
                self.music.remove_player(guild.id)
                self._loaded_settings.discard(guild.id)
                from botmusica.music.services.player_state import PlayerState
                self._set_player_state(guild.id, PlayerState.IDLE, reason="bot_disconnected_externally")
            return

        guild = member.guild
        voice_client = guild.voice_client
        if voice_client is None or not self._is_voice_connected(voice_client):
            return

        bot_channel = getattr(voice_client, "channel", None)
        if bot_channel is None:
            return

        # Only act when someone leaves the bot's channel.
        if before.channel != bot_channel:
            return

        # Count non-bot members remaining in the channel.
        human_members = sum(1 for m in bot_channel.members if not m.bot)
        if human_members > 0:
            return

        # Bot is alone — check if stay_connected (24/7 mode) is on.
        player = await self._get_player(guild.id)
        if player.stay_connected:
            return

        LOGGER.info("Bot ficou sozinho no canal de voz do guild %s. Desconectando.", guild.id)
        self._log_event("alone_disconnect", guild=guild.id, channel=bot_channel.id)

        try:
            await self._stop_voice(voice_client)
        except Exception:
            LOGGER.debug("Falha ao parar voz antes do alone disconnect guild %s", guild.id, exc_info=True)

        self._mark_voice_reconnect_required(guild.id)
        await voice_client.disconnect(force=True)
        await self._clear_nowplaying_message(guild.id)
        await self._clear_voice_mini_panel(guild.id)
        await self._clear_votes_for_guild(guild.id)
        self._cancel_playback_watchdog(guild.id)
        self._cancel_idle_timer(guild.id)
        self.music.remove_player(guild.id)
        self._loaded_settings.discard(guild.id)

        from botmusica.music.services.player_state import PlayerState
        self._set_player_state(guild.id, PlayerState.IDLE, reason="alone_disconnect")

        # Try to notify a text channel about the disconnect.
        text_channel_id = self._last_text_channel_id.get(guild.id)
        if text_channel_id:
            channel = guild.get_channel(text_channel_id)
            if isinstance(channel, (discord.TextChannel, discord.Thread)):
                try:
                    await self._send_channel(channel, self._note("Desconectado porque fiquei sozinho no canal de voz."))
                except Exception:
                    pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # A sala de controle aceita somente mensagens do bot.
        if message.guild is None:
            return
        if message.author.bot:
            return
        control_channel_id = self._control_room_channel_id(message.guild.id)
        if control_channel_id <= 0:
            return
        if int(message.channel.id) != int(control_channel_id):
            return
        try:
            await message.delete()
        except discord.Forbidden:
            return
        except discord.NotFound:
            return
        except Exception:
            return

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        for guild_id, state in list(self._control_room_state_cache.items()):
            _channel_id, message_id = state
            if int(payload.message_id) != int(message_id):
                continue
            recreated = await self._recreate_control_room_panel(guild_id)
            if recreated:
                self._log_event("control_room_repaired", guild=guild_id, reason="message_deleted")
            else:
                self._log_event("control_room_repair_failed", guild=guild_id, reason="message_deleted")
            return

    async def on_app_command_completion(self, interaction: discord.Interaction, _command: app_commands.Command) -> None:
        self._metrics["command_calls"] += 1
        created_at = interaction.created_at
        now_ts = discord.utils.utcnow()
        delta_ms = (now_ts - created_at).total_seconds() * 1000
        self._latency_total_ms += max(delta_ms, 0.0)
        self._latency_count += 1
        command_name = getattr(_command, "name", "unknown")
        self._command_latency_ms[command_name] += max(delta_ms, 0.0)
        self._command_latency_count[command_name] += 1
        self._command_metrics_window.add(command_name, max(delta_ms, 0.0))
        self._log_event(
            "command_completed",
            cid=self._correlation_id(interaction),
            command=command_name,
            domain=command_domain(command_name),
            guild=interaction.guild.id if interaction.guild else "dm",
            user=interaction.user.id if interaction.user else "unknown",
            latency_ms=f"{max(delta_ms, 0.0):.1f}",
        )
        self._maybe_profile(
            "command",
            command=command_name,
            latency_ms=f"{max(delta_ms, 0.0):.1f}",
            guild=interaction.guild.id if interaction.guild else "dm",
        )

    @commands.Cog.listener()
    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        self._metrics["command_errors"] += 1
        error_code = "ERR_COMMAND"
        if isinstance(error, app_commands.CommandInvokeError) and error.original is not None:
            title, desc = self._friendly_extraction_error(error.original)
            if "codigo:" in desc:
                error_code = desc.split("codigo:", 1)[1].split("`", 1)[0].strip() or error_code
            else:
                error_code = title
        self._log_event(
            "command_error",
            cid=self._correlation_id(interaction),
            domain=command_domain(getattr(interaction.command, "name", "unknown")),
            guild=interaction.guild.id if interaction.guild else "dm",
            user=interaction.user.id if interaction.user else "unknown",
            error_type=type(error).__name__,
            error_code=error_code,
            error=error,
        )
