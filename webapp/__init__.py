"""
webapp/app.py — FastAPI dashboard per MaziBot
Autenticazione via Discord OAuth2, API REST per controllare il bot.
"""
from __future__ import annotations

import asyncio
import os
import secrets
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlencode

import aiohttp
from fastapi import Cookie, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeSerializer

if TYPE_CHECKING:
    from discord.ext import commands

# ── Costanti OAuth2 ───────────────────────────────────────────────────────────
DISCORD_CLIENT_ID     = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DASHBOARD_URL         = os.getenv("DASHBOARD_URL", "http://localhost:8080")
SECRET_KEY            = os.getenv("SECRET_KEY", secrets.token_hex(32))

DISCORD_API    = "https://discord.com/api/v10"
REDIRECT_URI   = f"{DASHBOARD_URL}/auth/callback"
OAUTH2_SCOPES  = "identify guilds"

OAUTH2_URL = (
    "https://discord.com/api/oauth2/authorize?"
    + urlencode({
        "client_id":    DISCORD_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": OAUTH2_SCOPES,
    })
)

signer = URLSafeSerializer(SECRET_KEY, salt="mazibot-session")


# ── Helpers sessione ──────────────────────────────────────────────────────────
def _sign(data: dict) -> str:
    return signer.dumps(data)

def _unsign(token: str) -> Optional[dict]:
    try:
        return signer.loads(token)
    except BadSignature:
        return None

def _set_session(resp: Response, data: dict) -> None:
    resp.set_cookie("session", _sign(data), httponly=True, max_age=86400 * 7)

def _get_session(session: str = Cookie(default=None)) -> Optional[dict]:
    return _unsign(session) if session else None


# ── Factory ───────────────────────────────────────────────────────────────────
def create_app(bot) -> FastAPI:
    """Crea e configura l'applicazione FastAPI con riferimento al bot."""

    app = FastAPI(title="MaziBot Dashboard", docs_url=None, redoc_url=None)

    # Serve i file statici (index.html, ecc.)
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # ── Helpers interni ───────────────────────────────────────────────────────

    def _music_cog():
        return bot.cogs.get("Music")

    def _guild_state(guild_id: int):
        cog = _music_cog()
        if cog is None:
            return None
        return cog._states.get(guild_id)

    def _require_session(request: Request) -> dict:
        token = request.cookies.get("session")
        data = _unsign(token) if token else None
        if not data:
            raise HTTPException(status_code=401, detail="Non autenticato")
        return data

    def _require_guild_access(guild_id: int, session: dict):
        """Verifica che l'utente sia in un server in cui il bot è presente."""
        user_guild_ids = {int(g) for g in session.get("guild_ids", [])}
        bot_guild_ids  = {g.id for g in bot.guilds}
        allowed = user_guild_ids & bot_guild_ids
        if guild_id not in allowed:
            raise HTTPException(status_code=403, detail="Accesso negato")

    # ── Pagine ────────────────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def root(request: Request):
        token = request.cookies.get("session")
        if token and _unsign(token):
            return RedirectResponse("/dashboard")
        return RedirectResponse("/auth/login")

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request):
        session = _require_session(request)
        with open(os.path.join(static_dir, "index.html"), encoding="utf-8") as f:
            return HTMLResponse(f.read())

    # ── OAuth2 ────────────────────────────────────────────────────────────────

    @app.get("/auth/login")
    async def auth_login():
        if not DISCORD_CLIENT_ID:
            return HTMLResponse(
                "<h2 style='font-family:sans-serif;color:#fff;background:#1e1e2e;min-height:100vh;display:grid;place-items:center;margin:0;'>"
                "DISCORD_CLIENT_ID non configurato nel .env</h2>",
                status_code=500,
            )
        return RedirectResponse(OAUTH2_URL)

    @app.get("/auth/callback")
    async def auth_callback(code: str, response: Response):
        async with aiohttp.ClientSession() as session:
            # Scambia il code per un access token
            token_resp = await session.post(
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
            if token_resp.status != 200:
                raise HTTPException(400, "OAuth2 fallito")
            tokens = await token_resp.json()
            access_token = tokens["access_token"]

            # Recupera info utente
            headers = {"Authorization": f"Bearer {access_token}"}
            user_resp = await session.get(f"{DISCORD_API}/users/@me", headers=headers)
            user = await user_resp.json()

            # Recupera guild dell'utente
            guilds_resp = await session.get(f"{DISCORD_API}/users/@me/guilds", headers=headers)
            guilds = await guilds_resp.json()

        session_data = {
            "user_id":   user["id"],
            "username":  user["username"],
            "avatar":    user.get("avatar"),
            "guild_ids": [str(g["id"]) for g in guilds],
        }

        redirect = RedirectResponse("/dashboard")
        _set_session(redirect, session_data)
        return redirect

    @app.get("/auth/logout")
    async def auth_logout():
        resp = RedirectResponse("/auth/login")
        resp.delete_cookie("session")
        return resp

    # ── API ───────────────────────────────────────────────────────────────────

    @app.get("/api/me")
    async def api_me(request: Request):
        session = _require_session(request)
        user_guild_ids = {int(g) for g in session.get("guild_ids", [])}
        bot_guild_ids  = {g.id for g in bot.guilds}
        common = [
            {
                "id":   str(g.id),
                "name": g.name,
                "icon": f"https://cdn.discordapp.com/icons/{g.id}/{g.icon}.png"
                        if g.icon else None,
            }
            for g in bot.guilds if g.id in user_guild_ids
        ]
        return {
            "user": {
                "id":       session["user_id"],
                "username": session["username"],
                "avatar":   f"https://cdn.discordapp.com/avatars/{session['user_id']}/{session['avatar']}.png"
                            if session.get("avatar") else None,
            },
            "guilds": common,
        }

    @app.get("/api/guild/{guild_id}/state")
    async def api_state(guild_id: int, request: Request):
        session = _require_session(request)
        _require_guild_access(guild_id, session)
        state = _guild_state(guild_id)
        if state is None:
            return {"playing": False, "current": None, "queue": [], "volume": 50, "loop": False}

        current = None
        if state.current:
            c = state.current
            current = {
                "title":       c.title,
                "webpage_url": c.webpage_url,
                "duration":    c.duration_str,
                "thumbnail":   c.thumbnail,
                "requester":   c.requester.display_name if c.requester else None,
            }

        queue = [
            {
                "title":       s.title,
                "webpage_url": s.webpage_url,
                "duration":    s.duration_str,
                "thumbnail":   s.thumbnail,
            }
            for s in list(state.queue)
        ]

        return {
            "playing":  state.is_playing(),
            "paused":   state.is_paused(),
            "current":  current,
            "queue":    queue,
            "volume":   int(state.volume * 100),
            "loop":     state.loop,
        }

    @app.post("/api/guild/{guild_id}/skip")
    async def api_skip(guild_id: int, request: Request):
        session = _require_session(request)
        _require_guild_access(guild_id, session)
        state = _guild_state(guild_id)
        if state and state.is_active():
            state.loop = False
            state.voice_client.stop()
        return {"ok": True}

    @app.post("/api/guild/{guild_id}/stop")
    async def api_stop(guild_id: int, request: Request):
        session = _require_session(request)
        _require_guild_access(guild_id, session)
        state = _guild_state(guild_id)
        if state:
            state.queue.clear()
            state.current = None
            state.loop = False
            if state.voice_client:
                state.voice_client.stop()
        return {"ok": True}

    @app.post("/api/guild/{guild_id}/pause")
    async def api_pause(guild_id: int, request: Request):
        session = _require_session(request)
        _require_guild_access(guild_id, session)
        state = _guild_state(guild_id)
        if state and state.is_playing():
            state.voice_client.pause()
        return {"ok": True}

    @app.post("/api/guild/{guild_id}/resume")
    async def api_resume(guild_id: int, request: Request):
        session = _require_session(request)
        _require_guild_access(guild_id, session)
        state = _guild_state(guild_id)
        if state and state.is_paused():
            state.voice_client.resume()
        return {"ok": True}

    @app.post("/api/guild/{guild_id}/volume")
    async def api_volume(guild_id: int, request: Request):
        session = _require_session(request)
        _require_guild_access(guild_id, session)
        body = await request.json()
        vol = int(body.get("volume", 50))
        vol = max(0, min(100, vol))
        state = _guild_state(guild_id)
        if state:
            state.volume = vol / 100.0
        return {"ok": True, "volume": vol}

    @app.post("/api/guild/{guild_id}/loop")
    async def api_loop(guild_id: int, request: Request):
        session = _require_session(request)
        _require_guild_access(guild_id, session)
        state = _guild_state(guild_id)
        if state:
            state.loop = not state.loop
            return {"ok": True, "loop": state.loop}
        return {"ok": False}

    @app.delete("/api/guild/{guild_id}/queue/{index}")
    async def api_remove_song(guild_id: int, index: int, request: Request):
        session = _require_session(request)
        _require_guild_access(guild_id, session)
        state = _guild_state(guild_id)
        if state and 0 <= index < len(state.queue):
            q = list(state.queue)
            q.pop(index)
            from collections import deque
            state.queue = deque(q)
            return {"ok": True}
        return {"ok": False}

    return app
