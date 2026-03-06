"""
bot.py — Entry point di MaziBot 🎵
"""
import discord
from discord.ext import commands
import logging
import asyncio
import sys
import static_ffmpeg

# ── FFmpeg — aggiunge automaticamente il binario al PATH (funziona su Railway e qualsiasi OS)
static_ffmpeg.add_paths()

from config import DISCORD_TOKEN, BOT_PREFIX

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("MaziBot")

# ── Intents ──────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True


# ── Bot ───────────────────────────────────────────────────────────────────────
class MaziBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=BOT_PREFIX,
            intents=intents,
            help_command=None,          # Usiamo il nostro !help personalizzato
            description="🎵 MaziBot — Il tuo DJ personale su Discord",
        )

    async def setup_hook(self):
        """Carica i cog all'avvio."""
        await self.load_extension("cogs.music")
        log.info("✅ Cog 'music' caricato")

    async def on_ready(self):
        log.info(f"🤖 MaziBot connesso come {self.user} (ID: {self.user.id})")
        await self.change_presence(
            activity=discord.Game(name="MaziOnTop 🎵")
        )

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                embed=discord.Embed(
                    description=f"❌ Mancano degli argomenti. Usa `{BOT_PREFIX}help` per vedere i comandi.",
                    color=discord.Color.red(),
                )
            )
            return
        # Logga errori non gestiti
        log.error(f"Errore nel comando '{ctx.command}': {error}", exc_info=error)


# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    async with MaziBot() as bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
