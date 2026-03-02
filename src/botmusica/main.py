from __future__ import annotations

import ctypes.util
from dataclasses import fields
import logging
import os

import discord
from discord.ext import commands

from botmusica.config import Settings, load_settings

LOGGER = logging.getLogger("botmusica")


def configure_opus() -> None:
    if discord.opus.is_loaded():
        return

    candidates = [
        os.getenv("OPUS_LIBRARY", "").strip(),
        ctypes.util.find_library("opus") or "",
        "/opt/homebrew/opt/opus/lib/libopus.0.dylib",
        "/usr/local/opt/opus/lib/libopus.0.dylib",
        "libopus.0.dylib",
        "libopus.dylib",
        "libopus.so.0",
        "libopus.so",
    ]

    for candidate in candidates:
        if not candidate:
            continue
        try:
            discord.opus.load_opus(candidate)
            if discord.opus.is_loaded():
                LOGGER.info("Libopus carregada: %s", candidate)
                return
        except OSError:
            continue

    LOGGER.warning(
        "Nao foi possivel carregar libopus automaticamente. "
        "Instale opus no sistema e/ou defina OPUS_LIBRARY."
    )


class MusicaBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self._guild_command_cleanup_done = False
        for field in fields(settings):
            setattr(self, field.name, getattr(settings, field.name))

    async def setup_hook(self) -> None:
        await self.load_extension("botmusica.music.cog")

        if self.test_guild_id:
            guild_obj = discord.Object(id=self.test_guild_id)
            self.tree.copy_global_to(guild=guild_obj)
            await self.tree.sync(guild=guild_obj)
            LOGGER.info("Comandos sincronizados no guild de teste %s (modo guild-only)", self.test_guild_id)
            return
        await self.tree.sync()
        LOGGER.info("Comandos globais sincronizados (modo global-only)")

    async def on_ready(self) -> None:
        if not self.test_guild_id and not self._guild_command_cleanup_done:
            cleaned = 0
            for guild in self.guilds:
                try:
                    self.tree.clear_commands(guild=guild)
                    await self.tree.sync(guild=guild)
                    cleaned += 1
                except Exception:
                    LOGGER.warning("Falha limpando comandos por guild em %s", guild.id, exc_info=True)
            if cleaned:
                LOGGER.info("Limpeza de comandos por guild concluida em %s servidor(es)", cleaned)
            self._guild_command_cleanup_done = True
        LOGGER.info("Bot conectado como %s (%s)", self.user, self.user.id if self.user else "n/a")


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    configure_opus()
    settings = load_settings()
    bot = MusicaBot(settings=settings)
    bot.run(settings.discord_token, reconnect=True)


if __name__ == "__main__":
    run()
