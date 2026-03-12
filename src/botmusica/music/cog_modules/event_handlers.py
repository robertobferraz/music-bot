from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from botmusica.music.command_domains import command_domain


class EventHandlersMixin:
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
