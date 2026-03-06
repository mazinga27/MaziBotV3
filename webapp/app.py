"""
webapp/app.py — FastAPI dashboard per MaziBot
Autenticazione via Discord OAuth2, API REST per controllare il bot.
"""
from __future__ import annotations

import asyncio
import os
import secrets
from collections import deque
from typing import Optional
from urllib.parse import urlencode

import aiohttp
from fastapi import Cookie, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeSerializer

import discord
from cogs.music import _build_song, _extract_info, Song

# ── Configurazione OAuth2 ─────────────────────────────────────────────────────
DISCORD_CLIENT_ID     = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DASHBOARD_URL         = os.getenv("DASHBOARD_URL", "http://localhost:8080")
SECRET_KEY            = os.getenv("SECRET_KEY", secrets.token_hex(32))

# IDs Discord degli utenti autorizzati (separati da virgola).
# Se vuoto, chiunque sia nel server può accedere.
# Esempio: DASHBOARD_OWNER_IDS=123456789,987654321
_raw_owners = os.getenv("DASHBOARD_OWNER_IDS", "")
OWNER_IDS: set[str] = {x.strip() for x in _raw_owners.split(",") if x.strip()}

DISCORD_API   = "https://discord.com/api/v10"
REDIRECT_URI  = f"{DASHBOARD_URL}/auth/callback"
OAUTH2_URL    = (
    "https://discord.com/api/oauth2/authorize?"
    + urlencode({
        "client_id":     DISCORD_CLIENT_ID,
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",
        "scope":         "identify guilds",
    })
)

signer = URLSafeSerializer(SECRET_KEY, salt="mazibot-session")


# ── Helpers sessione cookie ───────────────────────────────────────────────────
def _sign(data: dict) -> str:
    return signer.dumps(data)

def _unsign(token: str) -> Optional[dict]:
    try:
        return signer.loads(token)
    except (BadSignature, Exception):
        return None

def _set_session(resp: Response, data: dict) -> None:
    resp.set_cookie("session", _sign(data), httponly=True, max_age=86400 * 7, samesite="lax")

def _get_session(request: Request) -> Optional[dict]:
    token = request.cookies.get("session")
    return _unsign(token) if token else None

def _require_session(request: Request) -> dict:
    data = _get_session(request)
    if not data:
        raise HTTPException(status_code=401, detail="Non autenticato")
    # Controllo owner: se DASHBOARD_OWNER_IDS è configurato, solo quegli utenti entrano
    if OWNER_IDS and data.get("user_id") not in OWNER_IDS:
        raise HTTPException(status_code=403, detail="Accesso riservato al proprietario del bot")
    return data

def _require_guild_access(guild_id: int, session: dict, bot) -> None:
    user_guild_ids = {int(g) for g in session.get("guild_ids", [])}
    bot_guild_ids  = {g.id for g in bot.guilds}
    if guild_id not in (user_guild_ids & bot_guild_ids):
        raise HTTPException(status_code=403, detail="Accesso negato a questo server")


# ── Factory app ───────────────────────────────────────────────────────────────
def create_app(bot) -> FastAPI:
    """Crea l'app FastAPI con riferimento diretto al bot discord.py."""

    app = FastAPI(title="MaziBot Dashboard", docs_url=None, redoc_url=None)
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # ── Shortcuts per accedere allo stato del bot ─────────────────────────────
    def _cog():
        return bot.cogs.get("Music")

    def _state(guild_id: int):
        cog = _cog()
        return cog._states.get(guild_id) if cog else None

    # ── Route pagine ──────────────────────────────────────────────────────────

    @app.get("/", response_class=RedirectResponse)
    async def root(request: Request):
        return "/dashboard" if _get_session(request) else "/auth/login"

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request):
        _require_session(request)
        with open(os.path.join(static_dir, "index.html"), encoding="utf-8") as f:
            return HTMLResponse(f.read())

    # ── OAuth2 Discord ────────────────────────────────────────────────────────

    @app.get("/auth/login")
    async def auth_login():
        if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET:
            return HTMLResponse(
                "<body style='background:#1e1e2e;color:#fff;font-family:sans-serif;"
                "display:grid;place-items:center;min-height:100vh;margin:0'>"
                "<div><h2>⚠️ Dashboard non configurata</h2>"
                "<p>Aggiungi <code>DISCORD_CLIENT_ID</code>, <code>DISCORD_CLIENT_SECRET</code>, "
                "<code>SECRET_KEY</code> e <code>DASHBOARD_URL</code> alle variabili d'ambiente.</p></div></body>",
                status_code=500,
            )
        return RedirectResponse(OAUTH2_URL)

    @app.get("/auth/callback")
    async def auth_callback(code: str, request: Request):
        async with aiohttp.ClientSession() as http:
            # 1. Scambia il code con il token
            tok = await http.post(
                f"{DISCORD_API}/oauth2/token",
                data={
                    "client_id":     DISCORD_CLIENT_ID,
                    "client_secret": DISCORD_CLIENT_SECRET,
                    "grant_type":    "authorization_code",
                    "code":          code,
                    "redirect_uri":  REDIRECT_URI,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if tok.status != 200:
                raise HTTPException(400, "Errore OAuth2 Discord")
            tokens       = await tok.json()
            access_token = tokens["access_token"]

            # 2. Info utente
            hdrs = {"Authorization": f"Bearer {access_token}"}
            user   = await (await http.get(f"{DISCORD_API}/users/@me",        headers=hdrs)).json()
            guilds = await (await http.get(f"{DISCORD_API}/users/@me/guilds",  headers=hdrs)).json()

        session_data = {
            "user_id":   str(user["id"]),
            "username":  user["username"],
            "avatar":    user.get("avatar"),
            "guild_ids": [str(g["id"]) for g in guilds],
        }
        resp = RedirectResponse("/dashboard", status_code=302)
        _set_session(resp, session_data)
        return resp

    @app.get("/auth/logout")
    async def auth_logout():
        resp = RedirectResponse("/auth/login")
        resp.delete_cookie("session")
        return resp

    # ── API /me ───────────────────────────────────────────────────────────────

    @app.get("/api/me")
    async def api_me(request: Request):
        session = _require_session(request)
        av = session.get("avatar")
        uid = session["user_id"]
        common_guilds = []
        user_ids = {int(g) for g in session.get("guild_ids", [])}
        for g in bot.guilds:
            if g.id in user_ids:
                common_guilds.append({
                    "id":   str(g.id),
                    "name": g.name,
                    # g.icon è un oggetto Asset in discord.py v2: usare .url
                    "icon": g.icon.url if g.icon else None,
                })
        av = session.get("avatar")
        uid = session["user_id"]
        return {
            "user": {
                "id":       uid,
                "username": session["username"],
                "avatar":   f"https://cdn.discordapp.com/avatars/{uid}/{av}.png?size=128" if av else
                            f"https://cdn.discordapp.com/embed/avatars/{int(uid) % 5}.png",
            },
            "guilds": common_guilds,
        }

    # ── API stato ─────────────────────────────────────────────────────────────

    @app.get("/api/guild/{guild_id}/state")
    async def api_state(guild_id: int, request: Request):
        session = _require_session(request)
        _require_guild_access(guild_id, session, bot)
        st = _state(guild_id)
        if st is None:
            return {"playing": False, "paused": False, "current": None,
                    "queue": [], "volume": 50, "loop": False}
        current = None
        if st.current:
            c = st.current
            current = {
                "title":       c.title,
                "webpage_url": c.webpage_url,
                "duration":    c.duration_str,
                "thumbnail":   c.thumbnail,
                "requester":   c.requester.display_name if c.requester else None,
            }
        return {
            "playing":  st.is_playing(),
            "paused":   st.is_paused(),
            "current":  current,
            "queue":    [{"title": s.title, "webpage_url": s.webpage_url,
                          "duration": s.duration_str, "thumbnail": s.thumbnail}
                         for s in list(st.queue)],
            "volume":   int(st.volume * 100),
            "loop":     st.loop,
        }

    # ── API comandi ───────────────────────────────────────────────────────────

    @app.post("/api/guild/{guild_id}/skip")
    async def api_skip(guild_id: int, request: Request):
        session = _require_session(request)
        _require_guild_access(guild_id, session, bot)
        st = _state(guild_id)
        if st and st.is_active():
            st.loop = False
            st.voice_client.stop()
        return {"ok": True}

    @app.post("/api/guild/{guild_id}/stop")
    async def api_stop(guild_id: int, request: Request):
        session = _require_session(request)
        _require_guild_access(guild_id, session, bot)
        st = _state(guild_id)
        if st:
            st.queue.clear()
            st.current = None
            st.loop = False
            if st.voice_client:
                st.voice_client.stop()
        return {"ok": True}

    @app.post("/api/guild/{guild_id}/pause")
    async def api_pause(guild_id: int, request: Request):
        session = _require_session(request)
        _require_guild_access(guild_id, session, bot)
        st = _state(guild_id)
        if st and st.is_playing():
            st.voice_client.pause()
        return {"ok": True}

    @app.post("/api/guild/{guild_id}/resume")
    async def api_resume(guild_id: int, request: Request):
        session = _require_session(request)
        _require_guild_access(guild_id, session, bot)
        st = _state(guild_id)
        if st and st.is_paused():
            st.voice_client.resume()
        return {"ok": True}

    @app.post("/api/guild/{guild_id}/volume")
    async def api_volume(guild_id: int, request: Request):
        session = _require_session(request)
        _require_guild_access(guild_id, session, bot)
        body = await request.json()
        vol = max(0, min(100, int(body.get("volume", 50))))
        st  = _state(guild_id)
        if not st:
            return {"ok": False}
        st.volume = vol / 100.0
        # FFmpegOpusAudio non supporta volume in real-time: riavvia lo stream
        # con il nuovo filtro -filter:a volume=X per applicare subito il cambio.
        if st.is_active() and st.current:
            cog = _cog()
            guild = bot.get_guild(guild_id)
            channel = st.voice_client.channel.guild.get_channel(
                st.voice_client.channel.id
            )
            # Cerca il primo canale testuale dove inviare l'embed
            text_channel = next(
                (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages),
                None,
            )
            if text_channel and cog:
                st.voice_client.stop()  # il callback _play_next riavvia con il volume aggiornato
        return {"ok": True, "volume": vol}

    @app.post("/api/guild/{guild_id}/loop")
    async def api_loop(guild_id: int, request: Request):
        session = _require_session(request)
        _require_guild_access(guild_id, session, bot)
        st = _state(guild_id)
        if st:
            st.loop = not st.loop
            return {"ok": True, "loop": st.loop}
        return {"ok": False}

    @app.delete("/api/guild/{guild_id}/queue/{index}")
    async def api_remove(guild_id: int, index: int, request: Request):
        session = _require_session(request)
        _require_guild_access(guild_id, session, bot)
        st = _state(guild_id)
        if st and 0 <= index < len(st.queue):
            q = list(st.queue)
            q.pop(index)
            st.queue = deque(q)
            return {"ok": True}
        return {"ok": False}

    @app.post("/api/guild/{guild_id}/play")
    async def api_play(guild_id: int, request: Request):
        """Aggiunge un brano alla coda (o lo avvia) dalla dashboard.
        Il bot deve essere già in un canale vocale.
        """
        session = _require_session(request)
        _require_guild_access(guild_id, session, bot)
        body = await request.json()
        query = body.get("query", "").strip()
        if not query:
            raise HTTPException(400, "Campo 'query' mancante")

        st = _state(guild_id)
        if not st or not (st.voice_client and st.voice_client.is_connected()):
            raise HTTPException(400, "Il bot non è in nessun canale vocale. Usa /play su Discord prima.")

        # Cerca il brano in background
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, _extract_info, query)
        if info is None:
            raise HTTPException(404, "Nessun brano trovato")

        # Usa il membro Discord come requester se disponibile
        guild    = bot.get_guild(guild_id)
        requester = guild.get_member(int(session["user_id"]))
        song = _build_song(info, requester)

        cog = _cog()
        # Trova un canale testuale per gli embed del bot
        text_ch = next(
            (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages),
            None,
        )

        if st.is_active():
            # Aggiunge in coda
            st.queue.append(song)
            return {"ok": True, "action": "queued", "title": song.title, "position": len(st.queue)}
        else:
            # Avvia subito
            st.current = song
            if cog and text_ch:
                asyncio.get_event_loop().create_task(
                    cog._stream(text_ch, st, song, guild.name)
                )
            return {"ok": True, "action": "playing", "title": song.title}

    return app
