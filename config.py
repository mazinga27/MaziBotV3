"""
config.py — Configurazione e costanti di MaziBot
"""
import base64
import os
import tempfile
from dotenv import load_dotenv

load_dotenv()

# ── Token e credenziali ───────────────────────────────────────────────────────
DISCORD_TOKEN: str         = os.getenv("DISCORD_TOKEN", "")
SPOTIFY_CLIENT_ID: str     = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET: str = os.getenv("SPOTIFY_CLIENT_SECRET", "")

if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN mancante nel file .env!")

# ── Cookie YouTube (anti bot-detection) ──────────────────────────────────────
# Su Railway e altri server cloud, YouTube rifiuta le richieste senza cookie.
# Esporta i cookie in formato Netscape (.txt) con un'estensione browser,
# codifica in base64: base64 -i cookies.txt | tr -d '\n'
# e incolla il risultato nella variabile YOUTUBE_COOKIES_B64 su Railway.
_COOKIES_B64 = os.getenv("YOUTUBE_COOKIES_B64", "")
_COOKIES_FILE: str | None = None

if _COOKIES_B64:
    try:
        _tmp = tempfile.NamedTemporaryFile(
            mode="wb", suffix=".txt", prefix="yt_cookies_", delete=False
        )
        _tmp.write(base64.b64decode(_COOKIES_B64))
        _tmp.close()
        _COOKIES_FILE = _tmp.name
    except Exception as _e:
        print(f"[config] Errore decodifica YOUTUBE_COOKIES_B64: {_e}")

# ── Opzioni yt-dlp ────────────────────────────────────────────────────────────
_ydl_base: dict = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
}
if _COOKIES_FILE:
    _ydl_base["cookiefile"] = _COOKIES_FILE

YDL_OPTIONS: dict = _ydl_base

YDL_FLAT_OPTIONS: dict = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": True,
    **(  {"cookiefile": _COOKIES_FILE} if _COOKIES_FILE else {}),
}
