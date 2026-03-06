"""
config.py — Configurazione e costanti di MaziBot
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Token e credenziali ───────────────────────────────────────────────────────
DISCORD_TOKEN: str         = os.getenv("DISCORD_TOKEN", "")
SPOTIFY_CLIENT_ID: str     = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET: str = os.getenv("SPOTIFY_CLIENT_SECRET", "")

if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN mancante nel file .env!")

# ── Opzioni yt-dlp ────────────────────────────────────────────────────────────
YDL_OPTIONS: dict = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
}

YDL_FLAT_OPTIONS: dict = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": True,
}
