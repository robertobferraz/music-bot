from __future__ import annotations

from dataclasses import dataclass

import discord


@dataclass(slots=True)
class ProgressHandle:
    interaction: discord.Interaction


class CommandService:
    async def begin_progress(
        self,
        interaction: discord.Interaction,
        *,
        title: str,
        description: str,
        color: discord.Color,
        embed_factory,
        edit_original,
        send_followup,
    ) -> ProgressHandle | None:
        embed = embed_factory(title, description, color=color)
        if await edit_original(interaction, embed=embed, view=None):
            return ProgressHandle(interaction=interaction)
        ok = await send_followup(interaction, embed=embed, ephemeral=True)
        if not ok:
            return None
        return ProgressHandle(interaction=interaction)

    async def update_progress(
        self,
        handle: ProgressHandle | None,
        *,
        title: str,
        description: str,
        color: discord.Color,
        embed_factory,
        edit_original,
    ) -> None:
        if handle is None:
            return
        embed = embed_factory(title, description, color=color)
        await edit_original(handle.interaction, embed=embed, view=None)
