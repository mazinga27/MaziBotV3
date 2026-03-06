"""
bot.py — Entry point di MaziBot 🎵
"""
import asyncio
import logging
import sys

import discord
import static_ffmpeg
from discord.ext import commands

from config import DISCORD_TOKEN

# ── FFmpeg: aggiunge il binario statico al PATH ───────────────────────────────
static_ffmpeg.add_paths()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("MaziBot")

# ── Intents ───────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.voice_states = True
# message_content non è più necessario con gli slash commands


# ── Bot ───────────────────────────────────────────────────────────────────────
class MaziBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="§",         # Prefix inutilizzato (solo slash commands)
            intents=intents,
            help_command=None,
            description="🎵 MaziBot — Il tuo DJ personale su Discord",
        )

    async def setup_hook(self):
        """Carica i cog e sincronizza gli slash commands con Discord."""
        await self.load_extension("cogs.music")
        log.info("Cog 'music' caricato")

        # Sincronizza gli slash commands globalmente
        synced = await self.tree.sync()
        log.info(f"Slash commands sincronizzati: {len(synced)} comandi")

    async def on_ready(self):
        log.info(f"Bot online: {self.user} (ID: {self.user.id})")
        log.info(f"Server connessi: {len(self.guilds)}")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="MaziOnTop 🎵",
            )
        )

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.CommandNotFound):
            return
        log.error(f"Errore comando '{ctx.command}': {error}", exc_info=error)


# ── Avvio ─────────────────────────────────────────────────────────────────────
async def main():
    async with MaziBot() as bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
