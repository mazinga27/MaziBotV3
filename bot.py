"""
bot.py — Entry point di MaziBot 🎵
Avvia il bot Discord e il web server (dashboard) nello stesso processo asyncio.
"""
import asyncio
import logging
import os
import sys

import discord
import static_ffmpeg
import uvicorn
from discord.ext import commands

from config import DISCORD_TOKEN
from webapp.app import create_app

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


# ── Bot ───────────────────────────────────────────────────────────────────────
class MaziBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="§",         # Prefix inutilizzato: si usano slash commands
            intents=intents,
            help_command=None,
            description="🎵 MaziBot — Il tuo DJ personale su Discord",
        )

    async def setup_hook(self):
        await self.load_extension("cogs.music")
        log.info("Cog 'music' caricato")
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
    bot = MaziBot()

    # FastAPI web server (dashboard)
    web_app = create_app(bot)
    port = int(os.getenv("PORT", 8080))
    config = uvicorn.Config(
        web_app,
        host="0.0.0.0",
        port=port,
        log_level="warning",    # evita log duplicati con il logger del bot
    )
    server = uvicorn.Server(config)
    log.info(f"Dashboard web avviata su http://0.0.0.0:{port}")

    # Bot Discord e web server girano nello stesso loop asyncio
    async with bot:
        await asyncio.gather(
            bot.start(DISCORD_TOKEN),
            server.serve(),
        )


if __name__ == "__main__":
    asyncio.run(main())
