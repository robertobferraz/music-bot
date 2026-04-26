from __future__ import annotations
# pyright: reportAttributeAccessIssue=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportOptionalMemberAccess=false
# mypy: disable-error-code=attr-defined

import asyncio
import logging
import time

import discord

from botmusica.music.player import GuildPlayer, Track
from botmusica.music.services.player_state import PlayerState

LOGGER = logging.getLogger("botmusica.music")


class RuntimePlaybackMixin:
    def _cancel_playback_watchdog(self, guild_id: int) -> None:
        task = self._playback_watchdog_tasks.pop(guild_id, None)
        if task and not task.done():
            task.cancel()

    def _schedule_playback_watchdog(
        self,
        guild: discord.Guild,
        text_channel: discord.abc.Messageable | None,
    ) -> None:
        existing = self._playback_watchdog_tasks.get(guild.id)
        if existing is not None and not existing.done():
            return

        async def worker() -> None:
            while True:
                try:
                    await asyncio.sleep(self.playback_watchdog_interval_seconds)
                    voice_client = guild.voice_client
                    if voice_client is None or not self._is_voice_connected(voice_client):
                        return
                    player = await self._get_player(guild.id)
                    if player.current is None:
                        return
                    state_entry = self.player_state.get(guild.id)
                    if state_entry.state in {
                        PlayerState.CONNECTING,
                        PlayerState.BUFFERING,
                        PlayerState.RECOVERING,
                    }:
                        continue
                    if guild.id in self._voice_reconnect_required:
                        continue
                    if self._is_voice_playing(voice_client) or self._is_voice_paused(voice_client):
                        continue
                    if player.current_started_at is None:
                        continue
                    stalled_for = time.monotonic() - player.current_started_at
                    if stalled_for < self.playback_watchdog_stall_seconds:
                        continue
                    LOGGER.warning(
                        "Playback watchdog detectou sessao travada no guild %s (stall=%.1fs).",
                        guild.id,
                        stalled_for,
                    )
                    self._log_event("playback_watchdog_detected", guild=guild.id, stall_seconds=f"{stalled_for:.1f}")
                    self._mark_voice_reconnect_required(guild.id)
                    refreshed = await self._force_voice_session_refresh(guild, voice_client)
                    if refreshed is None or not self._is_voice_session_usable(guild, refreshed):
                        self._log_event("playback_watchdog_refresh_failed", guild=guild.id)
                        self._set_player_state(guild.id, PlayerState.RECOVERING, reason="watchdog_refresh_failed")
                        continue
                    recovered = await self._recover_playback_after_reconnect(guild, text_channel)
                    if recovered:
                        self._log_event("playback_watchdog_recover_ok", guild=guild.id)
                        continue
                    self._log_event("playback_watchdog_recover_failed", guild=guild.id)
                    self._set_player_state(guild.id, PlayerState.ERROR, reason="watchdog_recover_failed")
                except asyncio.CancelledError:
                    return
                except Exception:
                    LOGGER.exception("Playback watchdog falhou no guild %s", guild.id)

        self._playback_watchdog_tasks[guild.id] = self.bot.loop.create_task(worker())

    def _mini_panel_channel(
        self,
        guild: discord.Guild,
        fallback: discord.abc.Messageable | None = None,
    ) -> discord.abc.Messageable | None:
        control_channel_id = self._control_room_channel_id(guild.id)
        if control_channel_id > 0:
            channel = guild.get_channel(control_channel_id)
            if isinstance(channel, (discord.TextChannel, discord.Thread)):
                return channel
        if isinstance(fallback, (discord.TextChannel, discord.Thread)):
            return fallback
        return None

    def _cancel_idle_timer(self, guild_id: int) -> None:
        task = self._idle_tasks.pop(guild_id, None)
        if task and not task.done():
            task.cancel()

    def _mark_voice_reconnect_required(self, guild_id: int) -> None:
        self._voice_reconnect_required.add(guild_id)

    def _clear_voice_reconnect_required(self, guild_id: int) -> None:
        self._voice_reconnect_required.discard(guild_id)

    async def _wait_voice_state_sync(
        self,
        guild: discord.Guild,
        channel: discord.VoiceChannel,
        *,
        timeout_seconds: float = 2.5,
    ) -> bool:
        deadline = time.monotonic() + max(timeout_seconds, 0.3)
        while time.monotonic() < deadline:
            me = guild.me
            if me and me.voice and me.voice.channel and me.voice.channel.id == channel.id:
                return True
            await asyncio.sleep(0.1)
        return False

    def _is_voice_connected(self, voice_client: discord.VoiceClient | None) -> bool:
        if voice_client is None:
            return False
        return voice_client.is_connected()

    def _is_voice_session_usable(self, guild: discord.Guild, voice_client: discord.VoiceClient | None) -> bool:
        if not self._is_voice_connected(voice_client):
            return False
        if voice_client is None:
            return False
        channel = getattr(voice_client, "channel", None)
        if not isinstance(channel, discord.VoiceChannel):
            return False
        me = guild.me
        if me is None or me.voice is None or me.voice.channel is None:
            return False
        return me.voice.channel.id == channel.id

    def _is_voice_playing(self, voice_client: discord.VoiceClient | None) -> bool:
        if voice_client is None:
            return False
        return voice_client.is_playing()

    def _is_voice_paused(self, voice_client: discord.VoiceClient | None) -> bool:
        if voice_client is None:
            return False
        return voice_client.is_paused()

    async def _pause_voice(self, voice_client: discord.VoiceClient) -> None:
        voice_client.pause()

    async def _resume_voice(self, voice_client: discord.VoiceClient) -> None:
        voice_client.resume()

    async def _stop_voice(self, voice_client: discord.VoiceClient) -> None:
        voice_client.stop()

    async def _set_voice_volume(self, voice_client: discord.VoiceClient, normalized: float) -> None:
        if isinstance(voice_client.source, discord.PCMVolumeTransformer):
            voice_client.source.volume = normalized

    async def _apply_track_finished_state(
        self,
        guild: discord.Guild,
        player: GuildPlayer,
        text_channel: discord.abc.Messageable | None,
        *,
        playback_error: Exception | None,
        finalize_queue_item: bool = True,
    ) -> None:
        finished_track = player.current
        skip_postplay = player.suppress_after_playback
        player.suppress_after_playback = False
        player.current = None
        player.current_started_at = None
        player.pause_started_at = None
        player.paused_accumulated_seconds = 0.0
        if finalize_queue_item:
            try:
                player.queue.task_done()
            except ValueError:
                pass

        if playback_error and text_channel:
            await self._send_channel(text_channel, self._error(f"Erro ao reproduzir audio: `{playback_error}`"))
            self._set_player_state(guild.id, PlayerState.ERROR, reason="playback_error")

        if finished_track and not playback_error and not skip_postplay:
            self._remember_finished_track(guild.id, finished_track)
            if player.loop_mode == "track":
                self.queue_service.enqueue_front(player, finished_track)
            elif player.loop_mode == "queue":
                await self.queue_service.enqueue(player, finished_track)
            elif player.autoplay and player.queue.empty():
                try:
                    recommended = await self._pick_autoplay_recommendation(guild.id, player, finished_track)
                    if recommended is None:
                        raise RuntimeError("Nao encontrei recomendacao compativel com o historico atual.")
                    if self._has_queue_capacity(player):
                        await self.queue_service.enqueue(player, recommended)
                        if text_channel:
                            await self._send_channel(
                                text_channel,
                                self._note(
                                    f"Autoplay adicionou: **{recommended.title}** "
                                    f"(`{self._format_duration(recommended.duration_seconds)}`)"
                                ),
                            )
                    elif text_channel:
                        await self._send_channel(text_channel, self._warn("Autoplay ignorado: fila no limite configurado."))
                except Exception as exc:
                    if text_channel:
                        await self._send_channel(text_channel, self._error(f"Autoplay falhou ao buscar recomendacao: `{exc}`"))

        await self._persist_queue_state(guild.id, player)
        self._schedule_prefetch_next(guild.id, player)
        if player.queue.empty() and player.current is None:
            self._cancel_playback_watchdog(guild.id)
            self._set_player_state(guild.id, PlayerState.IDLE, reason="track_finished")
        await self._start_next_if_needed(guild, text_channel)

    def _schedule_idle_disconnect(self, guild: discord.Guild, text_channel: discord.abc.Messageable | None) -> None:
        self._cancel_idle_timer(guild.id)

        async def idle_worker() -> None:
            try:
                await asyncio.sleep(self.idle_disconnect_seconds)
                voice_client = guild.voice_client
                player = await self._get_player(guild.id)
                if not self._is_voice_connected(voice_client):
                    return
                if self._is_voice_playing(voice_client) or self._is_voice_paused(voice_client):
                    return
                if player.current is not None or not player.queue.empty():
                    return
                if player.stay_connected:
                    return

                try:
                    await self._stop_voice(voice_client)
                except Exception:
                    LOGGER.debug("Falha ao parar voz antes do idle disconnect guild %s", guild.id, exc_info=True)
                if self._is_voice_playing(voice_client) or self._is_voice_paused(voice_client):
                    return
                player_recheck = await self._get_player(guild.id)
                if player_recheck.current is not None or not player_recheck.queue.empty():
                    return
                self._mark_voice_reconnect_required(guild.id)
                await voice_client.disconnect(force=True)
                await self._clear_nowplaying_message(guild.id)
                await self._clear_voice_mini_panel(guild.id)
                await self._clear_votes_for_guild(guild.id)
                self._cancel_playback_watchdog(guild.id)
                self.music.remove_player(guild.id)
                self._loaded_settings.discard(guild.id)
                self._set_player_state(guild.id, PlayerState.IDLE, reason="idle_disconnect")
                if text_channel:
                    await self._send_channel(text_channel, self._note(
                        f"Desconectado por inatividade ({self.idle_disconnect_seconds}s sem musica na fila)."
                    ))
            except asyncio.CancelledError:
                return

        self._idle_tasks[guild.id] = self.bot.loop.create_task(idle_worker())

    async def _require_user_voice_channel(self, interaction: discord.Interaction) -> discord.VoiceChannel | None:
        if not isinstance(interaction.user, discord.Member):
            return None
        voice_state = interaction.user.voice
        if not voice_state or not isinstance(voice_state.channel, discord.VoiceChannel):
            return None
        return voice_state.channel

    async def _connect_native_voice_with_retry(
        self,
        guild: discord.Guild,
        channel: discord.VoiceChannel,
    ) -> discord.VoiceClient:
        last_exc: Exception | None = None
        schedule = self.reconnect_policy.backoff_schedule()
        # Para conexao inicial de voz, garante no minimo 2 tentativas.
        if len(schedule) < 2:
            schedule = [0.0, 0.45]
        for attempt, delay in enumerate(schedule, start=1):
            try:
                if delay > 0:
                    await asyncio.sleep(delay)
                timeout = self.voice_connect_timeout_seconds + (1.5 if attempt > 1 else 0.0)
                connected = await channel.connect(self_deaf=True, timeout=timeout)
                synced = await self._wait_voice_state_sync(guild, channel, timeout_seconds=3.0)
                if not synced or not self._is_voice_session_usable(guild, connected):
                    raise TimeoutError("Sessao de voz conectou sem sincronizar no Discord.")
                return connected
            except Exception as exc:
                last_exc = exc
                stale = guild.voice_client
                if stale is not None and not self._is_voice_session_usable(guild, stale):
                    try:
                        await stale.disconnect(force=True)
                    except Exception:
                        LOGGER.debug("Falha limpando sessao de voz apos tentativa %s no guild %s", attempt, guild.id, exc_info=True)
                LOGGER.warning(
                    "Tentativa %s/%s de conexao FFmpeg falhou no guild %s",
                    attempt,
                    len(schedule),
                    guild.id,
                    exc_info=True,
                )
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Falha desconhecida ao conectar voz FFmpeg.")

    async def _ensure_voice(self, interaction: discord.Interaction) -> discord.VoiceClient | None:
        guild = interaction.guild
        if guild is None:
            return None

        user_channel = await self._require_user_voice_channel(interaction)
        if user_channel is None:
            return None

        existing = guild.voice_client
        # Nao forca reconnect agressivo quando o bot ja esta no canal.
        force_reconnect = guild.id in self._voice_reconnect_required

        # Se ja esta no mesmo canal do usuario e aparenta conectado, reaproveita a sessao.
        if existing is not None and getattr(existing, "channel", None) == user_channel:
            try:
                native_connected = existing.is_connected() if hasattr(existing, "is_connected") else False
            except Exception:
                native_connected = False
            if native_connected:
                self._clear_voice_reconnect_required(guild.id)
                self._set_player_state(guild.id, PlayerState.IDLE, reason="voice_reused_same_channel")
                try:
                    target = self._mini_panel_channel(guild, interaction.channel)
                    await self._upsert_voice_mini_panel(guild, target, reason="voice_reused")
                except Exception:
                    LOGGER.debug("Falha ao atualizar mini painel (voice_reused) no guild %s", guild.id, exc_info=True)
                return existing

        if existing is not None and (force_reconnect or not self._is_voice_session_usable(guild, existing)):
            try:
                await existing.disconnect(force=True)
            except Exception:
                LOGGER.debug("Falha ao limpar sessao de voz antiga no guild %s", guild.id, exc_info=True)
            existing = guild.voice_client

        if self._is_voice_session_usable(guild, existing):
            if existing.channel != user_channel:
                await existing.move_to(user_channel)
                await self._wait_voice_state_sync(guild, user_channel)
            self._clear_voice_reconnect_required(guild.id)
            self._set_player_state(guild.id, PlayerState.IDLE, reason="voice_connected")
            try:
                target = self._mini_panel_channel(guild, interaction.channel)
                await self._upsert_voice_mini_panel(guild, target, reason="voice_connected")
            except Exception:
                LOGGER.debug("Falha ao atualizar mini painel (voice_connected) no guild %s", guild.id, exc_info=True)
            return existing

        self._set_player_state(guild.id, PlayerState.CONNECTING, reason="joining_voice")
        fallback_existing = guild.voice_client
        if fallback_existing is not None and not self._is_voice_session_usable(guild, fallback_existing):
            try:
                await fallback_existing.disconnect(force=True)
            except Exception:
                LOGGER.debug("Falha ao limpar sessao antiga antes do fallback FFmpeg no guild %s", guild.id, exc_info=True)
        connected = await self._connect_native_voice_with_retry(guild, user_channel)
        self._clear_voice_reconnect_required(guild.id)
        self._set_player_state(guild.id, PlayerState.IDLE, reason="voice_joined_ffmpeg")
        try:
            target = self._mini_panel_channel(guild, interaction.channel)
            await self._upsert_voice_mini_panel(guild, target, reason="voice_joined_ffmpeg")
        except Exception:
            LOGGER.debug("Falha ao atualizar mini painel (voice_joined_ffmpeg) no guild %s", guild.id, exc_info=True)
        return connected

    def _mark_track_ffmpeg_fallback(self, guild_id: int, track: Track) -> None:
        return

    def _consume_track_ffmpeg_fallback(self, guild_id: int, track: Track) -> bool:
        return False

    async def _switch_voice_to_ffmpeg(
        self,
        guild: discord.Guild,
        voice_client: discord.VoiceClient,
    ) -> discord.VoiceClient | None:
        return voice_client

    async def _force_voice_session_refresh(
        self,
        guild: discord.Guild,
        voice_client: discord.VoiceClient | None,
    ) -> discord.VoiceClient | None:
        channel = getattr(voice_client, "channel", None) if voice_client is not None else None
        if not isinstance(channel, discord.VoiceChannel):
            return guild.voice_client
        try:
            if self._is_voice_connected(voice_client):
                try:
                    await self._stop_voice(voice_client)
                except Exception:
                    LOGGER.debug("Falha ao parar voz antes do refresh no guild %s", guild.id, exc_info=True)
                await voice_client.disconnect(force=True)
        except Exception:
            LOGGER.debug("Falha ao desconectar sessao atual no refresh guild %s", guild.id, exc_info=True)
        await asyncio.sleep(0.2)
        try:
            refreshed = await channel.connect(self_deaf=True)
            await self._wait_voice_state_sync(guild, channel, timeout_seconds=2.0)
            return refreshed
        except Exception:
            LOGGER.debug("Falha ao recriar sessao de voz no refresh guild %s", guild.id, exc_info=True)
            return guild.voice_client

    async def _recover_playback_after_reconnect(
        self,
        guild: discord.Guild,
        text_channel: discord.abc.Messageable | None,
    ) -> bool:
        self._set_player_state(guild.id, PlayerState.RECOVERING, reason="voice_reconnect")
        voice_client = guild.voice_client
        if not self._is_voice_connected(voice_client):
            return False
        if self._is_voice_playing(voice_client) or self._is_voice_paused(voice_client):
            return False

        player = await self._get_player(guild.id)
        lock = self._get_domain_lock(guild.id, "playback")
        async with lock:
            had_pending = player.current is not None or not player.queue.empty()
            if player.current is not None:
                self.queue_service.enqueue_front(player, player.current)
                player.current = None
                player.current_started_at = None
                player.pause_started_at = None
                player.paused_accumulated_seconds = 0.0
                player.suppress_after_playback = False
                await self._persist_queue_state(guild.id, player)
        if not had_pending:
            self._set_player_state(guild.id, PlayerState.IDLE, reason="recover_nothing_pending")
            return False

        if not self.feature_flags.reconnect_strategy_enabled:
            await self._start_next_if_needed(guild, text_channel)
            return True

        for attempt, delay in enumerate(self.reconnect_policy.backoff_schedule(), start=1):
            try:
                await asyncio.wait_for(self._start_next_if_needed(guild, text_channel), timeout=12.0)
                voice_client = guild.voice_client
                if self._is_voice_playing(voice_client) or self._is_voice_paused(voice_client):
                    self._set_player_state(guild.id, PlayerState.PLAYING, reason=f"recover_ok_attempt_{attempt}")
                    return True
            except Exception:
                LOGGER.debug("recover attempt failed guild=%s attempt=%s", guild.id, attempt, exc_info=True)
            if delay > 0:
                await asyncio.sleep(delay)
        self._set_player_state(guild.id, PlayerState.ERROR, reason="recover_exhausted")
        return False

    async def _start_next_if_needed(
        self,
        guild: discord.Guild,
        text_channel: discord.abc.Messageable | None = None,
    ) -> None:
        voice_client = guild.voice_client
        if not self._is_voice_connected(voice_client):
            self._cancel_playback_watchdog(guild.id)
            self._set_player_state(guild.id, PlayerState.IDLE, reason="voice_disconnected")
            await self._clear_voice_mini_panel(guild.id)
            return
        if not self._is_voice_session_usable(guild, voice_client):
            self._cancel_playback_watchdog(guild.id)
            self._set_player_state(guild.id, PlayerState.RECOVERING, reason="voice_session_unusable")
            self._mark_voice_reconnect_required(guild.id)
            try:
                await voice_client.disconnect(force=True)
            except Exception:
                LOGGER.debug("Falha ao forcar limpeza de sessao de voz inutilizavel no guild %s", guild.id, exc_info=True)
            await self._clear_voice_mini_panel(guild.id)
            return
        if text_channel is not None and hasattr(text_channel, "id"):
            self._last_text_channel_id[guild.id] = int(getattr(text_channel, "id"))

        player = await self._get_player(guild.id)
        lock = self._get_lock(guild.id)
        async with lock:
            if self._is_voice_playing(voice_client) or self._is_voice_paused(voice_client):
                return
            if player.current is not None:
                return
            if player.restored_queue_pending_activation and text_channel is None:
                self._set_player_state(guild.id, PlayerState.IDLE, reason="restored_queue_pending_activation")
                return
            if player.restored_queue_pending_activation:
                player.restored_queue_pending_activation = False
            if player.queue.empty():
                self._cancel_playback_watchdog(guild.id)
                self._set_player_state(guild.id, PlayerState.IDLE, reason="queue_empty")
                self._voice_became_idle_at[guild.id] = time.monotonic()
                self._schedule_idle_disconnect(guild, text_channel)
                return

            idle_since = self._voice_became_idle_at.pop(guild.id, None)
            if idle_since is not None and self.voice_idle_reconnect_seconds > 0 and (
                time.monotonic() - idle_since
            ) >= self.voice_idle_reconnect_seconds:
                idle_duration = time.monotonic() - idle_since
                LOGGER.info(
                    "Voice session idle for %.1fs on guild %s — refreshing before playback.",
                    idle_duration,
                    guild.id,
                )
                self._log_event("voice_idle_refresh", guild=guild.id, idle_seconds=f"{idle_duration:.1f}")
                refreshed = await self._force_voice_session_refresh(guild, voice_client)
                if refreshed is None or not self._is_voice_session_usable(guild, refreshed):
                    self._set_player_state(guild.id, PlayerState.RECOVERING, reason="idle_refresh_failed")
                    self._mark_voice_reconnect_required(guild.id)
                    return
                voice_client = refreshed

            track = await player.queue.get()
            self._set_player_state(guild.id, PlayerState.BUFFERING, reason=f"buffering:{track.title[:48]}")
            player.current = track
            player.current_started_at = None
            player.pause_started_at = None
            player.paused_accumulated_seconds = 0.0
            self._cancel_idle_timer(guild.id)
            seek_seconds = player.pending_seek_seconds
            player.pending_seek_seconds = 0
            await self._persist_queue_state(guild.id, player)

            try:
                source = await self.music.build_audio_source(
                    track,
                    volume=player.volume,
                    audio_filter=player.audio_filter,
                    start_seconds=seek_seconds,
                )
            except Exception as exc:
                self._set_player_state(guild.id, PlayerState.ERROR, reason="stream_prepare_failed")
                player.current = None
                player.current_started_at = None
                player.pause_started_at = None
                player.paused_accumulated_seconds = 0.0
                try:
                    player.queue.task_done()
                except ValueError:
                    pass
                await self._persist_queue_state(guild.id, player)
                self._metrics["playback_failures"] += 1
                LOGGER.exception("Falha ao preparar stream no guild %s", guild.id)
                if text_channel:
                    await self._send_channel(text_channel, self._error(f"Nao consegui tocar `{track.title}`: {exc}"))
                await self._start_next_if_needed(guild, text_channel)
                return

            finished = asyncio.Event()
            playback_error: Exception | None = None

            def after_playback(err: Exception | None) -> None:
                nonlocal playback_error
                playback_error = err
                self.bot.loop.call_soon_threadsafe(finished.set)

            try:
                voice_client.play(source, after=after_playback)
            except Exception as exc:
                self._set_player_state(guild.id, PlayerState.ERROR, reason="voice_play_failed")
                player.current = None
                player.current_started_at = None
                player.pause_started_at = None
                player.paused_accumulated_seconds = 0.0
                player.queue.task_done()
                await self._persist_queue_state(guild.id, player)
                self._metrics["playback_failures"] += 1
                cleanup = getattr(source, "cleanup", None)
                if callable(cleanup):
                    cleanup()
                LOGGER.exception("Falha ao iniciar playback no guild %s", guild.id)
                if text_channel:
                    await self._send_channel(text_channel, self._error(f"Nao consegui iniciar reproducao: `{exc}`"))
                await self._start_next_if_needed(guild, text_channel)
                return
            player.current_started_at = time.monotonic()
            self._schedule_prefetch_next(guild.id, player)
            await self._upsert_nowplaying_message(guild, text_channel)
            self._schedule_nowplaying_updater(guild)
            self._schedule_playback_watchdog(guild, text_channel)
            self._set_player_state(guild.id, PlayerState.PLAYING, reason="ffmpeg_playing")

            async def wait_and_advance() -> None:
                await finished.wait()
                await self._apply_track_finished_state(
                    guild,
                    player,
                    text_channel,
                    playback_error=playback_error,
                    finalize_queue_item=True,
                )

            self.bot.loop.create_task(wait_and_advance())

    async def _health_worker(self) -> None:
        while True:
            try:
                await asyncio.sleep(15)
                for guild in list(self.bot.guilds):
                    voice_client = guild.voice_client
                    if voice_client is None:
                        continue

                    player = await self._get_player(guild.id)

                    if not self._is_voice_connected(voice_client):
                        await self._persist_queue_state(guild.id, player)
                        self._cancel_prefetch(guild.id)
                        await self._clear_votes_for_guild(guild.id)
                        await self._clear_voice_mini_panel(guild.id)
                        self._cancel_playback_watchdog(guild.id)
                        self.music.remove_player(guild.id)
                        self._loaded_settings.discard(guild.id)
                        self._cancel_idle_timer(guild.id)
                        self._set_player_state(guild.id, PlayerState.IDLE, reason="health_disconnected")
                        continue

                    if player.current and not self._is_voice_playing(voice_client) and not self._is_voice_paused(voice_client):
                        if player.current_started_at and (time.monotonic() - player.current_started_at) > 10:
                            LOGGER.warning("Recuperando estado travado no guild %s", guild.id)
                            player.current = None
                            player.current_started_at = None
                            player.pause_started_at = None
                            player.paused_accumulated_seconds = 0.0
                            await self._persist_queue_state(guild.id, player)
                            self._set_player_state(guild.id, PlayerState.RECOVERING, reason="health_stuck_recovery")
                            self._mark_voice_reconnect_required(guild.id)
                            await self._start_next_if_needed(guild)

                self._health_ticks += 1
                if self._health_ticks % 4 == 0:
                    await self.store.cleanup_expired_votes(max_age_seconds=120, now_unix=int(time.time()))
                    await self.store.prune_queue_events(max_rows_per_guild=2000)
                    await self.store.prune_search_cache(
                        max_age_seconds=int(self.search_cache_ttl_seconds + self.search_cache_stale_ttl_seconds + 60),
                    )
                    # Prune expired entries from unbounded in-memory caches.
                    self._prune_expired_caches()
                if self.state_snapshot_interval_ticks > 0 and self._health_ticks % self.state_snapshot_interval_ticks == 0:
                    await self._snapshot_all_states()
                if self._health_ticks % 4 == 0:
                    snapshot = self._metrics_snapshot()
                    if snapshot.average_latency_ms >= self.health_alert_latency_ms_threshold:
                        await self._send_health_alert(
                            "high_latency",
                            "Latencia Elevada",
                            (
                                f"Latencia media dos comandos: `{snapshot.average_latency_ms:.1f} ms`.\n"
                                "Recomendo verificar rede, extracao de audio e carga local."
                            ),
                        )
                    LOGGER.info(
                        "metrics calls=%s errors=%s extract_fail=%s playback_fail=%s avg_latency_ms=%.1f",
                        snapshot.command_calls,
                        snapshot.command_errors,
                        snapshot.extraction_failures,
                        snapshot.playback_failures,
                        snapshot.average_latency_ms,
                    )

            except asyncio.CancelledError:
                return
            except Exception:
                LOGGER.exception("Erro no health worker")

    async def _retention_worker(self) -> None:
        while True:
            try:
                await asyncio.sleep(self.retention_daily_seconds)
                await self.store.cleanup_expired_votes(max_age_seconds=120, now_unix=int(time.time()))
                await self.store.prune_queue_events(max_rows_per_guild=self.retention_queue_events_max_rows)
                await self.store.prune_search_cache(max_age_seconds=self.retention_search_cache_max_age_seconds)
            except asyncio.CancelledError:
                return
            except Exception:
                LOGGER.exception("Erro no retention worker")

    async def _snapshot_all_states(self) -> None:
        players = dict(getattr(self.music, "_players", {}))
        for guild_id, player in players.items():
            try:
                await self._persist_queue_state(int(guild_id), player)
            except Exception:
                LOGGER.debug("Falha no snapshot de estado do guild %s", guild_id, exc_info=True)

    async def _send_health_alert(self, key: str, title: str, description: str) -> None:
        if self.health_alert_channel_id <= 0:
            return
        now = time.monotonic()
        last = self._last_health_alert_at.get(key, 0.0)
        if now - last < self.health_alert_cooldown_seconds:
            return
        self._last_health_alert_at[key] = now
        channel = self.bot.get_channel(self.health_alert_channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        embed = self._embed(
            f"🚨 {title}",
            description,
            color=self._theme_color("admin"),
        )
        try:
            await channel.send(embed=embed)
        except Exception:
            LOGGER.debug("Falha ao enviar health alert", exc_info=True)
