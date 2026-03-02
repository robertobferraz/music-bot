from __future__ import annotations

import logging
from dataclasses import dataclass

import discord
from discord import app_commands

from botmusica.music.player import FILTERS, GuildPlayer, Track
from botmusica.music.services.player_state import PlayerState
from botmusica.music.storage import GuildSettings, FavoriteTrack, PlaylistTrack, QueueTrack

LOGGER = logging.getLogger("botmusica.music")


@dataclass(slots=True)
class GuildPolicy:
    max_track_duration_seconds: int
    domain_whitelist: set[str]
    domain_blacklist: set[str]


class StatePolicyMixin:
    @staticmethod
    def _correlation_id(interaction: discord.Interaction) -> str:
        return f"cmd-{interaction.id}"

    def _policy_for_guild(self, guild_id: int) -> GuildPolicy:
        policy = self._guild_policy.get(guild_id)
        if policy is not None:
            return policy
        default = GuildPolicy(
            max_track_duration_seconds=self.default_max_track_duration_seconds,
            domain_whitelist=set(self.default_domain_whitelist),
            domain_blacklist=set(self.default_domain_blacklist),
        )
        self._guild_policy[guild_id] = default
        return default

    def _has_queue_capacity(self, player: GuildPlayer) -> bool:
        return len(player.snapshot_queue()) < self.max_queue_size

    def _count_user_pending(self, player: GuildPlayer, requester_name: str) -> int:
        requester_key = requester_name.strip().casefold()
        if not requester_key:
            return 0
        return sum(1 for track in player.snapshot_queue() if track.requested_by.strip().casefold() == requester_key)

    def _is_user_queue_within_limit(self, player: GuildPlayer, requester_name: str, incoming_items: int = 1) -> bool:
        if self.max_user_queue_items <= 0:
            return True
        pending = self._count_user_pending(player, requester_name)
        return (pending + max(incoming_items, 0)) <= self.max_user_queue_items


    @staticmethod
    def _track_from_favorite(item: FavoriteTrack, requester: str) -> Track:
        return Track(
            source_query=item.source_query,
            title=item.title,
            webpage_url=item.webpage_url,
            requested_by=requester,
            artist=None,
            duration_seconds=item.duration_seconds,
        )

    @staticmethod
    def _track_from_playlist_item(item: PlaylistTrack, requester: str) -> Track:
        return Track(
            source_query=item.source_query,
            title=item.title,
            webpage_url=item.webpage_url,
            requested_by=requester,
            artist=None,
            duration_seconds=item.duration_seconds,
        )

    @staticmethod
    def _track_from_queue_item(item: QueueTrack) -> Track:
        return Track(
            source_query=item.source_query,
            title=item.title,
            webpage_url=item.webpage_url,
            requested_by=item.requested_by,
            artist=None,
            duration_seconds=item.duration_seconds,
        )

    @staticmethod
    def _track_to_queue_item(track: Track) -> QueueTrack:
        return QueueTrack(
            title=track.title,
            source_query=track.source_query,
            webpage_url=track.webpage_url,
            duration_seconds=track.duration_seconds,
            requested_by=track.requested_by,
        )

    def _build_persisted_queue_tracks(self, player: GuildPlayer) -> list[QueueTrack]:
        tracks: list[QueueTrack] = []
        if player.current is not None:
            tracks.append(self._track_to_queue_item(player.current))
        tracks.extend(self._track_to_queue_item(item) for item in player.snapshot_queue())
        return tracks

    async def _persist_queue_state(self, guild_id: int, player: GuildPlayer) -> None:
        await self.queue_repo.save(guild_id, self._build_persisted_queue_tracks(player))

    def _build_queue_embed(self, *, player: GuildPlayer, items: list[Track], page: int) -> discord.Embed:
        return self.embeds.build_queue_embed(
            player=player,
            items=items,
            page=page,
            format_duration=self._format_duration,
        )

    async def _playlist_name_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        guild = interaction.guild
        user = interaction.user
        if guild is None or user is None:
            return []
        names = await self.playlist_repo.list_names(guild.id, user.id)
        current_lower = current.casefold().strip()
        filtered = [name for name in names if not current_lower or current_lower in name.casefold()]
        return [app_commands.Choice(name=name[:100], value=name) for name in filtered[:20]]

    async def _get_player(self, guild_id: int) -> GuildPlayer:
        player = self.music.get_player(guild_id)
        await self._restore_nowplaying_message_if_needed(guild_id)
        if guild_id in self._loaded_settings:
            return player

        settings = await self.guild_settings_repo.get(guild_id)
        if settings:
            player.volume = min(max(settings.volume, 0.01), 2.0)
            player.loop_mode = settings.loop_mode if settings.loop_mode in {"off", "track", "queue"} else "off"
            player.autoplay = bool(settings.autoplay)
            player.stay_connected = bool(settings.stay_connected)
            player.audio_filter = settings.audio_filter if settings.audio_filter in FILTERS else "off"
            self._guild_policy[guild_id] = GuildPolicy(
                max_track_duration_seconds=max(int(settings.max_track_duration_seconds), 0),
                domain_whitelist={item.strip().casefold() for item in settings.domain_whitelist.split(",") if item.strip()},
                domain_blacklist={item.strip().casefold() for item in settings.domain_blacklist.split(",") if item.strip()},
            )
        else:
            self._guild_policy[guild_id] = GuildPolicy(
                max_track_duration_seconds=self.default_max_track_duration_seconds,
                domain_whitelist=set(self.default_domain_whitelist),
                domain_blacklist=set(self.default_domain_blacklist),
            )
        restored_queue = await self.queue_repo.load(guild_id)
        if restored_queue and not player.current and player.queue.empty():
            for item in restored_queue:
                await self.queue_service.enqueue(player, self._track_from_queue_item(item))
            LOGGER.info("Fila restaurada no guild %s com %s item(ns)", guild_id, len(restored_queue))
        runtime_state = await self.store.get_player_runtime_state(guild_id)
        if runtime_state:
            try:
                restored_state = PlayerState(runtime_state.state)
            except Exception:
                restored_state = PlayerState.IDLE
            self.player_state.transition(guild_id, restored_state, reason="restored_from_store")

        self._loaded_settings.add(guild_id)
        return player

    async def _save_player_settings(self, guild_id: int, player: GuildPlayer) -> None:
        policy = self._policy_for_guild(guild_id)
        settings = GuildSettings(
            volume=player.volume,
            loop_mode=player.loop_mode,
            autoplay=player.autoplay,
            stay_connected=player.stay_connected,
            audio_filter=player.audio_filter,
            max_track_duration_seconds=policy.max_track_duration_seconds,
            domain_whitelist=",".join(sorted(policy.domain_whitelist)),
            domain_blacklist=",".join(sorted(policy.domain_blacklist)),
        )
        await self.guild_settings_repo.upsert(guild_id, settings)

    @staticmethod
    def _format_duration(seconds: int | None) -> str:
        if seconds is None:
            return "ao vivo/desconhecida"
        minutes, secs = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    def _policy_summary(self, guild_id: int) -> str:
        policy = self._policy_for_guild(guild_id)
        return (
            f"max_duracao=`{policy.max_track_duration_seconds or 'off'}` "
            f"whitelist=`{len(policy.domain_whitelist)}` "
            f"blacklist=`{len(policy.domain_blacklist)}`"
        )
