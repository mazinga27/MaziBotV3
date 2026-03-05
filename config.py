"""
config.py — Gestione variabili d'ambiente per MaziBot
"""
import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
SPOTIFY_CLIENT_ID: str = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET: str = os.getenv("SPOTIFY_CLIENT_SECRET", "")
BOT_PREFIX: str = os.getenv("BOT_PREFIX", "!")

# Validazione token obbligatori
if not DISCORD_TOKEN:
    raise ValueError("❌ DISCORD_TOKEN non trovato nel file .env!")

# Impostazioni audio
FFMPEG_OPTIONS: dict = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn -filter:a volume=1.0",
}

YDL_OPTIONS: dict = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "extract_flat": False,
    "skip_download": True,
    "postprocessors": [{
        "key": "FFmpegExtractAudio",
        "preferredcodec": "opus",
    }],
}

YDL_OPTIONS_FLAT: dict = {
    "format": "bestaudio/best",
    "noplaylist": False,
    "quiet": True,
    "no_warnings": True,
    "extract_flat": True,
}
