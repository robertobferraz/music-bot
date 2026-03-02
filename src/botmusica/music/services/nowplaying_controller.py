from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import discord

from botmusica.music.storage import NowPlayingStateRecord


BuildEmbedFn = Callable[[], discord.Embed]
BuildViewFn = Callable[[], discord.ui.View]
TrackKeyFn = Callable[[], str]
ResolveChannelFn = Callable[[discord.Guild, discord.abc.Messageable | None], discord.TextChannel | discord.Thread | None]
OnMessageLostFn = Callable[[int], None]


class NowPlayingController:
    def __init__(self, *, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self.tasks: dict[int, asyncio.Task[None]] = {}
        self.messages: dict[int, discord.Message] = {}
        self.track_keys: dict[int, str] = {}
        self.render_signatures: dict[int, str] = {}
        self.restored_guilds: set[int] = set()

    def cancel_updater(self, guild_id: int) -> None:
        task = self.tasks.pop(guild_id, None)
        if task and not task.done():
            task.cancel()

    def forget(self, guild_id: int) -> None:
        self.messages.pop(guild_id, None)
        self.track_keys.pop(guild_id, None)
        self.render_signatures.pop(guild_id, None)
        self.cancel_updater(guild_id)

    async def restore_message_if_needed(
        self,
        *,
        guild_id: int,
        bot: discord.Client,
        store: Any,
    ) -> None:
        if guild_id in self.restored_guilds:
            return
        self.restored_guilds.add(guild_id)
        record = await store.get_nowplaying_state(guild_id)
        if record is None:
            return
        guild = bot.get_guild(guild_id)
        if guild is None:
            return
        channel = guild.get_channel(record.channel_id)
        if channel is None or not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await store.delete_nowplaying_state(guild_id)
            return
        try:
            message = await channel.fetch_message(record.message_id)
        except Exception:
            await store.delete_nowplaying_state(guild_id)
            return
        self.messages[guild_id] = message

    async def upsert_message(
        self,
        *,
        guild: discord.Guild,
        text_channel: discord.abc.Messageable | None,
        store: Any,
        nowplaying_auto_pin: bool,
        nowplaying_repost_on_track_change: bool,
        build_embed: BuildEmbedFn,
        build_view: BuildViewFn,
        track_key: TrackKeyFn,
        resolve_channel: ResolveChannelFn,
    ) -> None:
        embed = build_embed()
        signature = repr(embed.to_dict())
        live_view = build_view()
        message = self.messages.get(guild.id)
        new_track_key = track_key()
        old_track_key = self.track_keys.get(guild.id)
        should_repost = bool(
            nowplaying_repost_on_track_change
            and message is not None
            and old_track_key
            and old_track_key != new_track_key
        )
        if should_repost and message is not None:
            try:
                await message.delete()
            except Exception:
                pass
            self.messages.pop(guild.id, None)
            message = None
        if message is not None:
            try:
                if self.render_signatures.get(guild.id) == signature:
                    return
                await message.edit(embed=embed, view=live_view)
                self.render_signatures[guild.id] = signature
                self.track_keys[guild.id] = new_track_key
                if nowplaying_auto_pin and not message.pinned:
                    try:
                        await message.pin(reason="Now Playing fixado automaticamente")
                    except Exception:
                        pass
                await store.upsert_nowplaying_state(
                    NowPlayingStateRecord(
                        guild_id=guild.id,
                        channel_id=message.channel.id,
                        message_id=message.id,
                    )
                )
                return
            except Exception:
                self.messages.pop(guild.id, None)

        channel = resolve_channel(guild, text_channel)
        if channel is None:
            return
        try:
            sent = await channel.send(embed=embed, view=live_view)
        except Exception:
            return
        self.messages[guild.id] = sent
        self.render_signatures[guild.id] = signature
        self.track_keys[guild.id] = new_track_key
        await store.upsert_nowplaying_state(
            NowPlayingStateRecord(
                guild_id=guild.id,
                channel_id=sent.channel.id,
                message_id=sent.id,
            )
        )
        if nowplaying_auto_pin:
            try:
                await sent.pin(reason="Now Playing fixado automaticamente")
            except Exception:
                pass

    def schedule_updater(
        self,
        *,
        guild: discord.Guild,
        get_build_embed: Callable[[], Awaitable[discord.Embed | None]],
        build_view: BuildViewFn,
        on_message_lost: OnMessageLostFn,
        interval_seconds: float = 5.0,
    ) -> None:
        self.cancel_updater(guild.id)

        async def worker() -> None:
            while True:
                try:
                    await asyncio.sleep(max(interval_seconds, 1.0))
                    message = self.messages.get(guild.id)
                    if message is None:
                        return
                    embed = await get_build_embed()
                    if embed is None:
                        return
                    signature = repr(embed.to_dict())
                    if self.render_signatures.get(guild.id) == signature:
                        continue
                    await message.edit(embed=embed, view=build_view())
                    self.render_signatures[guild.id] = signature
                except asyncio.CancelledError:
                    return
                except Exception:
                    on_message_lost(guild.id)
                    return

        self.tasks[guild.id] = self._loop.create_task(worker())
