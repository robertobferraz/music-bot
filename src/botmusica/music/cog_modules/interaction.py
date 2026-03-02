from __future__ import annotations

import asyncio
import logging
from typing import Any, Mapping

import discord

LOGGER = logging.getLogger("botmusica.music")


class InteractionResponseMixin:
    def _interaction_command_name(self, interaction: discord.Interaction | None) -> str:
        if interaction is None:
            return ""
        command = getattr(interaction, "command", None)
        name = getattr(command, "name", None)
        if isinstance(name, str) and name:
            return name.casefold()
        data = getattr(interaction, "data", None)
        if isinstance(data, Mapping):
            data_name = data.get("name")
            if isinstance(data_name, str) and data_name:
                return data_name.casefold()
        return ""

    def _apply_auto_delete_policy(
        self,
        payload: dict[str, Any],
        *,
        interaction: discord.Interaction | None = None,
    ) -> dict[str, Any]:
        if payload.get("ephemeral", False):
            return payload
        if "delete_after" in payload:
            return payload
        command_name = self._interaction_command_name(interaction)
        if command_name and command_name in self.auto_delete_exempt_commands:
            return payload
        if self.public_message_delete_after_seconds > 0:
            payload["delete_after"] = self.public_message_delete_after_seconds
        return payload

    async def _fallback_unknown_interaction(self, interaction: discord.Interaction, payload: dict[str, Any]) -> None:
        if payload.get("ephemeral", False):
            return
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        content = payload.get("content")
        embed = payload.get("embed")
        if content is None and embed is None:
            return
        try:
            await channel.send(
                **self._apply_auto_delete_policy(
                    {"content": content, "embed": embed},
                    interaction=interaction,
                )
            )
            self._metrics["unknown_interaction_fallback_sent"] += 1
        except Exception:
            self._metrics["unknown_interaction_fallback_error"] += 1

    async def _send_response(self, interaction: discord.Interaction, **kwargs: Any) -> None:
        payload = self._apply_auto_delete_policy(kwargs, interaction=interaction)
        try:
            if interaction.response.is_done():
                await self._send_followup(interaction, **payload)
                return
            await interaction.response.send_message(**payload)
        except discord.InteractionResponded:
            await self._send_followup(interaction, **payload)
        except discord.NotFound:
            LOGGER.warning("Interaction expirada antes de responder (cid=%s)", self._correlation_id(interaction))
        except discord.HTTPException as exc:
            if getattr(exc, "code", None) == 10062:
                LOGGER.warning("Unknown interaction ao responder (cid=%s)", self._correlation_id(interaction))
                self._metrics["unknown_interaction"] += 1
                await self._fallback_unknown_interaction(interaction, payload)
                return
            raise

    async def _send_followup(self, interaction: discord.Interaction, **kwargs: Any) -> bool:
        payload = self._apply_auto_delete_policy(kwargs, interaction=interaction)
        delete_after = payload.pop("delete_after", None)
        try:
            message = await interaction.followup.send(wait=True, **payload)
        except discord.NotFound:
            LOGGER.warning("Interaction expirada antes de followup (cid=%s)", self._correlation_id(interaction))
            return False
        except discord.HTTPException as exc:
            if getattr(exc, "code", None) == 10062:
                LOGGER.warning("Unknown interaction no followup (cid=%s)", self._correlation_id(interaction))
                self._metrics["unknown_interaction"] += 1
                await self._fallback_unknown_interaction(interaction, payload)
                return False
            raise
        if (
            delete_after
            and isinstance(delete_after, (int, float))
            and delete_after > 0
            and message is not None
            and not payload.get("ephemeral", False)
        ):
            async def delete_later() -> None:
                try:
                    await asyncio.sleep(float(delete_after))
                    await message.delete()
                except Exception:
                    return

            self.bot.loop.create_task(delete_later())
        return True

    async def _edit_original_response(self, interaction: discord.Interaction, **kwargs: Any) -> bool:
        payload = self._apply_auto_delete_policy(kwargs, interaction=interaction)
        payload.pop("delete_after", None)
        payload.pop("ephemeral", None)
        edit_fn = getattr(interaction, "edit_original_response", None)
        if edit_fn is None:
            return False
        try:
            await edit_fn(**payload)
            return True
        except discord.NotFound:
            LOGGER.warning("Interaction expirada antes de editar resposta (cid=%s)", self._correlation_id(interaction))
            return False
        except discord.HTTPException as exc:
            if getattr(exc, "code", None) == 10062:
                LOGGER.warning("Unknown interaction ao editar resposta (cid=%s)", self._correlation_id(interaction))
                self._metrics["unknown_interaction"] += 1
                return False
            raise

    def _delete_original_response_later(self, interaction: discord.Interaction, *, delay_seconds: float) -> None:
        if delay_seconds <= 0:
            return

        async def worker() -> None:
            try:
                await asyncio.sleep(float(delay_seconds))
                await interaction.delete_original_response()
            except Exception:
                return

        self.bot.loop.create_task(worker())

    async def _safe_defer(self, interaction: discord.Interaction, *, thinking: bool = True, ephemeral: bool = False) -> bool:
        if interaction.response.is_done():
            return True
        try:
            await interaction.response.defer(thinking=thinking, ephemeral=ephemeral)
            return True
        except discord.InteractionResponded:
            return True
        except discord.NotFound:
            LOGGER.warning("Interaction expirada antes do defer (cid=%s)", self._correlation_id(interaction))
            return False
        except discord.HTTPException as exc:
            if getattr(exc, "code", None) == 40060:
                # Ja houve ACK por outro fluxo; seguir com followup para nao perder o comando.
                return True
            if getattr(exc, "code", None) == 10062:
                LOGGER.warning("Unknown interaction no defer (cid=%s)", self._correlation_id(interaction))
                self._metrics["unknown_interaction"] += 1
                return False
            raise

    async def _send_channel(self, channel: discord.abc.Messageable, content: str | None = None, **kwargs: Any) -> None:
        payload: dict[str, Any] = dict(kwargs)
        if content is not None:
            payload["content"] = content
        await channel.send(**self._apply_auto_delete_policy(payload, interaction=None))

    @staticmethod
    def _has_control_permissions(*, is_admin: bool, can_manage_channels: bool) -> bool:
        return is_admin or can_manage_channels
