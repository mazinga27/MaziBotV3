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
        print(f"[config] ✅ Cookie YouTube caricati da YOUTUBE_COOKIES_B64 → {_COOKIES_FILE}")
    except Exception as _e:
        print(f"[config] ❌ Errore decodifica YOUTUBE_COOKIES_B64: {_e}")
else:
    print("[config] ⚠️  YOUTUBE_COOKIES_B64 non configurata — YouTube potrebbe bloccare le richieste")

# ── Opzioni yt-dlp ────────────────────────────────────────────────────────────
# I player_client android_music/ios/web sono stati bloccati da YouTube sui
# server cloud. Si usa ora un User-Agent da browser desktop reale + cookie.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

_ydl_base: dict = {
    "format": "bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "http_headers": {"User-Agent": _USER_AGENT},
}
if _COOKIES_FILE:
    _ydl_base["cookiefile"] = _COOKIES_FILE

YDL_OPTIONS: dict = _ydl_base

YDL_FLAT_OPTIONS: dict = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": True,
    "http_headers": {"User-Agent": _USER_AGENT},
    **({"cookiefile": _COOKIES_FILE} if _COOKIES_FILE else {}),
}
