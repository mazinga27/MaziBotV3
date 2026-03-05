"""
cogs/music.py — MaziBot Music Cog 🎵
Gestisce: riproduzione YouTube, playlist Spotify, coda, volume e tutti i comandi musicali.
"""
from __future__ import annotations

import asyncio
import logging
import random
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import discord
import spotipy
import yt_dlp
from discord.ext import commands
from spotipy.oauth2 import SpotifyClientCredentials

from config import (
    BOT_PREFIX,
    FFMPEG_OPTIONS,
    SPOTIFY_CLIENT_ID,
    SPOTIFY_CLIENT_SECRET,
    YDL_OPTIONS,
)

log = logging.getLogger("MaziBot.Music")

# ──────────────────────────────────────────────────────────────────────────────
# Dataclass per un brano in coda
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Song:
    title: str
    url: str                       # URL stream diretto
    webpage_url: str               # URL della pagina YouTube
    duration: int = 0              # secondi
    thumbnail: str = ""
    requester: discord.Member = field(default=None)

    @property
    def duration_str(self) -> str:
        m, s = divmod(self.duration, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"


# ──────────────────────────────────────────────────────────────────────────────
# Stato per ogni guild
# ──────────────────────────────────────────────────────────────────────────────
class GuildState:
    def __init__(self):
        self.queue: deque[Song] = deque()
        self.current: Optional[Song] = None
        self.volume: float = 0.5        # 50% di default
        self.loop: bool = False
        self.voice_client: Optional[discord.VoiceClient] = None
        self._lock = asyncio.Lock()

    def is_playing(self) -> bool:
        return self.voice_client is not None and self.voice_client.is_playing()

    def is_paused(self) -> bool:
        return self.voice_client is not None and self.voice_client.is_paused()


# ──────────────────────────────────────────────────────────────────────────────
# Helpers per yt-dlp
# ──────────────────────────────────────────────────────────────────────────────
def _extract_info(query: str) -> Optional[dict]:
    """Esegue l'estrazione sincrona con yt-dlp (da chiamare in executor)."""
    if not query.startswith("http"):
        query = f"ytsearch:{query}"
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        try:
            data = ydl.extract_info(query, download=False)
        except yt_dlp.utils.DownloadError as e:
            log.error(f"yt-dlp DownloadError: {e}")
            return None

    if data is None:
        return None

    # ytsearch restituisce una lista
    if "entries" in data:
        entries = [e for e in data["entries"] if e]
        return entries[0] if entries else None
    return data


def _build_song(info: dict, requester: discord.Member) -> Song:
    """Crea un oggetto Song dal dict restituito da yt-dlp."""
    # Cerca il miglior stream audio
    url = info.get("url") or info.get("webpage_url", "")
    # Alcuni formati hanno una lista di 'formats'
    if not url and "formats" in info:
        for fmt in reversed(info["formats"]):
            if fmt.get("acodec") != "none":
                url = fmt.get("url", "")
                break

    return Song(
        title=info.get("title", "Sconosciuto"),
        url=url,
        webpage_url=info.get("webpage_url", ""),
        duration=info.get("duration", 0) or 0,
        thumbnail=info.get("thumbnail", ""),
        requester=requester,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Helpers per Spotify
# ──────────────────────────────────────────────────────────────────────────────
def _get_spotify_client() -> Optional[spotipy.Spotify]:
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        return None
    return spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
        )
    )


def _get_spotify_tracks(url: str) -> list[str]:
    """Estrae i nomi dei brani da una playlist/album/track di Spotify."""
    sp = _get_spotify_client()
    if sp is None:
        return []

    tracks: list[str] = []

    if "playlist" in url:
        results = sp.playlist_tracks(url)
        while results:
            for item in results.get("items", []):
                track = item.get("track")
                if track:
                    name = track.get("name", "")
                    artists = ", ".join(a["name"] for a in track.get("artists", []))
                    tracks.append(f"{name} {artists}")
            results = sp.next(results) if results.get("next") else None

    elif "album" in url:
        results = sp.album_tracks(url)
        while results:
            for item in results.get("items", []):
                name = item.get("name", "")
                artists = ", ".join(a["name"] for a in item.get("artists", []))
                tracks.append(f"{name} {artists}")
            results = sp.next(results) if results.get("next") else None

    elif "track" in url:
        track = sp.track(url)
        name = track.get("name", "")
        artists = ", ".join(a["name"] for a in track.get("artists", []))
        tracks.append(f"{name} {artists}")

    return tracks


# ──────────────────────────────────────────────────────────────────────────────
# Palette colori
# ──────────────────────────────────────────────────────────────────────────────
COLOR_PLAYING   = 0x1DB954   # verde → in riproduzione
COLOR_QUEUE     = 0x5865F2   # blurple Discord → coda
COLOR_ACTION    = 0xF5A623   # arancione → azioni (skip, stop, shuffle…)
COLOR_SUCCESS   = 0x2ECC71   # verde chiaro → successo
COLOR_ERROR     = 0xED4245   # rosso Discord → errori
COLOR_INFO      = 0x3498DB   # blu → info generali
COLOR_SPOTIFY   = 0x1DB954   # verde Spotify

# Alias per compatibilità
ACCENT_COLOR = COLOR_PLAYING

BOT_ICON = "https://cdn.discordapp.com/emojis/1234567890.png"  # placeholder


def _footer(embed: discord.Embed, requester: discord.Member = None) -> discord.Embed:
    """Aggiunge footer con timestamp e, opzionalmente, l'utente richiedente."""
    text = "MaziBot 🎵"
    if requester:
        text = f"Richiesto da {requester.display_name}  •  MaziBot 🎵"
        embed.set_footer(text=text, icon_url=requester.display_avatar.url)
    else:
        embed.set_footer(text=text)
    embed.timestamp = discord.utils.utcnow()
    return embed


def _embed(title: str, description: str = "", color: int = COLOR_INFO) -> discord.Embed:
    e = discord.Embed(title=title, description=description, color=color)
    _footer(e)
    return e


def _song_embed(song: Song, label: str = "▶️  In riproduzione", color: int = COLOR_PLAYING) -> discord.Embed:
    e = discord.Embed(
        description=f"### [{song.title}]({song.webpage_url})",
        color=color,
    )
    e.set_author(name=label)
    e.add_field(name="⏱️  Durata",  value=f"`{song.duration_str}`", inline=True)
    e.add_field(name="�  Link",    value=f"[YouTube]({song.webpage_url})",  inline=True)
    if song.thumbnail:
        e.set_image(url=song.thumbnail)
    _footer(e, song.requester)
    return e


# ──────────────────────────────────────────────────────────────────────────────
# Il Cog
# ──────────────────────────────────────────────────────────────────────────────
class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._states: dict[int, GuildState] = {}

    # ── Stato per guild ───────────────────────────────────────────────────────
    def _get_state(self, guild: discord.Guild) -> GuildState:
        if guild.id not in self._states:
            self._states[guild.id] = GuildState()
        return self._states[guild.id]

    # ── Join al canale dell'utente ────────────────────────────────────────────
    async def _ensure_voice(self, ctx: commands.Context) -> bool:
        """Connette il bot al canale vocale dell'utente. Ritorna False se non possibile."""
        if ctx.author.voice is None:
            await ctx.send(embed=_embed("❌ Errore", "Devi essere in un canale vocale!", color=0xe74c3c))
            return False

        state = self._get_state(ctx.guild)
        channel = ctx.author.voice.channel

        if state.voice_client is None or not state.voice_client.is_connected():
            state.voice_client = await channel.connect()
        elif state.voice_client.channel != channel:
            await state.voice_client.move_to(channel)

        return True

    # ── Riproduzione coda ─────────────────────────────────────────────────────
    def _play_next(self, ctx: commands.Context, state: GuildState):
        """Callback chiamato quando una canzone finisce. Avvia la prossima."""
        if state.loop and state.current:
            # Rimette la canzone corrente all'inizio
            state.queue.appendleft(state.current)

        if not state.queue:
            state.current = None
            asyncio.run_coroutine_threadsafe(
                ctx.send(embed=_embed("📭  Coda terminata", "Non ci sono altri brani in coda.\nUsa `!play` per aggiungerne uno!", color=COLOR_INFO)),
                self.bot.loop,
            )
            return

        next_song = state.queue.popleft()
        state.current = next_song

        asyncio.run_coroutine_threadsafe(
            self._stream(ctx, state, next_song),
            self.bot.loop,
        )

    async def _stream(self, ctx: commands.Context, state: GuildState, song: Song):
        """Avvia effettivamente il playback di un Song."""
        if state.voice_client is None or not state.voice_client.is_connected():
            return

        try:
            source = discord.FFmpegPCMAudio(song.url, **FFMPEG_OPTIONS)
            volume_source = discord.PCMVolumeTransformer(source, volume=state.volume)
            state.voice_client.play(
                volume_source,
                after=lambda e: self._play_next(ctx, state) if not e else log.error(f"Errore playback: {e}"),
            )
            await ctx.send(embed=_song_embed(song))
        except Exception as e:
            log.error(f"Errore stream: {e}")
            await ctx.send(embed=_embed("❌ Errore", f"Impossibile riprodurre il brano: `{e}`", color=0xe74c3c))
            self._play_next(ctx, state)

    # ═══════════════════════════════════════════════════════════════════════════
    # COMANDI
    # ═══════════════════════════════════════════════════════════════════════════

    # ── !play ─────────────────────────────────────────────────────────────────
    @commands.command(name="play", aliases=["p"], help="Riproduci o aggiungi in coda: URL YouTube o testo di ricerca.")
    async def play(self, ctx: commands.Context, *, query: str):
        if not await self._ensure_voice(ctx):
            return

        state = self._get_state(ctx.guild)
        async with ctx.typing():
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, _extract_info, query)

        if info is None:
            await ctx.send(embed=_embed("❌ Non trovato", f"Nessun risultato per: `{query}`", color=0xe74c3c))
            return

        song = _build_song(info, ctx.author)

        if state.is_playing() or state.is_paused():
            state.queue.append(song)
            e = discord.Embed(
                description=f"### [{song.title}]({song.webpage_url})",
                color=COLOR_QUEUE,
            )
            e.set_author(name="➕  Aggiunto in coda")
            e.add_field(name="⏱️  Durata",   value=f"`{song.duration_str}`", inline=True)
            e.add_field(name="📋  Posizione", value=f"`#{len(state.queue)}`",  inline=True)
            if song.thumbnail:
                e.set_thumbnail(url=song.thumbnail)
            _footer(e, ctx.author)
            await ctx.send(embed=e)
        else:
            state.current = song
            await self._stream(ctx, state, song)

    # ── !search ───────────────────────────────────────────────────────────────
    @commands.command(name="search", help="Cerca un brano su YouTube e mostra i risultati.")
    async def search(self, ctx: commands.Context, *, query: str):
        async with ctx.typing():
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True}) as ydl:
                loop = asyncio.get_event_loop()
                data = await loop.run_in_executor(
                    None,
                    lambda: ydl.extract_info(f"ytsearch5:{query}", download=False),
                )

        if not data or not data.get("entries"):
            await ctx.send(embed=_embed("❌ Nessun risultato", f"Nessun brano trovato per: `{query}`", color=0xe74c3c))
            return

        entries = [e for e in data["entries"] if e][:5]
        desc = "\n".join(
            f"`{i+1}.` [{e.get('title','?')}](https://www.youtube.com/watch?v={e.get('id','')}) "
            f"— `{e.get('duration_string','?')}`"
            for i, e in enumerate(entries)
        )
        e = _embed("🔍 Risultati ricerca", desc)
        e.set_footer(text=f"Usa {BOT_PREFIX}play <testo> per riprodurre | MaziBot 🎵")
        await ctx.send(embed=e)

    # ── !spotify ──────────────────────────────────────────────────────────────
    @commands.command(name="spotify", aliases=["sp"], help="Carica una playlist/album/traccia Spotify in coda.")
    async def spotify(self, ctx: commands.Context, url: str):
        if not await self._ensure_voice(ctx):
            return

        if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
            await ctx.send(
                embed=_embed(
                    "❌ Spotify non configurato",
                    "Aggiungi `SPOTIFY_CLIENT_ID` e `SPOTIFY_CLIENT_SECRET` al file `.env`.",
                    color=0xe74c3c,
                )
            )
            return

        async with ctx.typing():
            loop = asyncio.get_event_loop()
            track_names = await loop.run_in_executor(None, _get_spotify_tracks, url)

        if not track_names:
            await ctx.send(embed=_embed("❌ Errore", "Impossibile leggere la playlist Spotify. Controlla l'URL.", color=0xe74c3c))
            return

        state = self._get_state(ctx.guild)
        sp_load = discord.Embed(
            description=f"Sto cercando **{len(track_names)}** brani su YouTube…\n*Questo può richiedere qualche secondo.*",
            color=COLOR_SPOTIFY,
        )
        sp_load.set_author(name="Spotify  ·  Caricamento playlist")
        _footer(sp_load, ctx.author)
        loading_msg = await ctx.send(embed=sp_load)

        # Aggiungi il primo brano subito, il resto come query
        added = 0
        for i, name in enumerate(track_names):
            info = await loop.run_in_executor(None, _extract_info, name)
            if info is None:
                continue
            song = _build_song(info, ctx.author)

            if i == 0 and not state.is_playing() and not state.is_paused():
                state.current = song
                await self._stream(ctx, state, song)
            else:
                state.queue.append(song)
            added += 1

        sp_done = discord.Embed(
            description=f"**{added}** brani aggiunti in coda con successo!",
            color=COLOR_SUCCESS,
        )
        sp_done.set_author(name="✅  Playlist Spotify caricata")
        _footer(sp_done, ctx.author)
        await loading_msg.edit(embed=sp_done)

    # ── !skip ─────────────────────────────────────────────────────────────────
    @commands.command(name="skip", aliases=["s"], help="Salta la canzone corrente.")
    async def skip(self, ctx: commands.Context):
        state = self._get_state(ctx.guild)
        if not state.is_playing() and not state.is_paused():
            await ctx.send(embed=_embed("❌  Niente da skippare", "Non c'è nessuna canzone in riproduzione.", color=COLOR_ERROR))
            return
        state.loop = False   # Disabilita loop se si skippa manualmente
        state.voice_client.stop()
        e = _embed("⏭️  Skippato!", f"Brano saltato da **{ctx.author.display_name}**.", color=COLOR_ACTION)
        await ctx.send(embed=e)

    # ── !stop ─────────────────────────────────────────────────────────────────
    @commands.command(name="stop", help="Ferma la riproduzione e svuota la coda.")
    async def stop(self, ctx: commands.Context):
        state = self._get_state(ctx.guild)
        state.queue.clear()
        state.current = None
        state.loop = False
        if state.voice_client:
            state.voice_client.stop()
        await ctx.send(embed=_embed("⏹️  Fermato", "Riproduzione fermata e coda svuotata.", color=COLOR_ACTION))

    # ── !pause ────────────────────────────────────────────────────────────────
    @commands.command(name="pause", help="Mette in pausa la riproduzione.")
    async def pause(self, ctx: commands.Context):
        state = self._get_state(ctx.guild)
        if state.is_playing():
            state.voice_client.pause()
            await ctx.send(embed=_embed("⏸️  In pausa", "Usa `!resume` per riprendere.", color=COLOR_ACTION))
        else:
            await ctx.send(embed=_embed("❌  Errore", "Non c'è niente in riproduzione.", color=COLOR_ERROR))

    # ── !resume ───────────────────────────────────────────────────────────────
    @commands.command(name="resume", aliases=["r"], help="Riprende la riproduzione.")
    async def resume(self, ctx: commands.Context):
        state = self._get_state(ctx.guild)
        if state.is_paused():
            state.voice_client.resume()
            await ctx.send(embed=_embed("▶️  Ripresa!", "Riproduzione ripresa con successo.", color=COLOR_SUCCESS))
        else:
            await ctx.send(embed=_embed("❌  Errore", "Non c'è niente in pausa.", color=COLOR_ERROR))

    # ── !queue ────────────────────────────────────────────────────────────────
    @commands.command(name="queue", aliases=["q"], help="Mostra la coda di riproduzione.")
    async def queue(self, ctx: commands.Context):
        state = self._get_state(ctx.guild)

        if not state.current and not state.queue:
            await ctx.send(embed=_embed("📭  Coda vuota", "Non ci sono brani in coda.\nUsa `!play` per aggiungerne uno!", color=COLOR_INFO))
            return

        e = discord.Embed(color=COLOR_QUEUE)
        e.set_author(name="🎶  Coda di riproduzione")

        if state.current:
            loop_icon = "  🔁" if state.loop else ""
            e.add_field(
                name=f"▶️  In riproduzione{loop_icon}",
                value=f"> [{state.current.title}]({state.current.webpage_url})\n> `{state.current.duration_str}`",
                inline=False,
            )
            if state.current.thumbnail:
                e.set_thumbnail(url=state.current.thumbnail)

        if state.queue:
            lines = []
            total_sec = 0
            for i, song in enumerate(list(state.queue)[:10], 1):
                lines.append(f"`{i:02d}.` [{song.title}]({song.webpage_url}) — `{song.duration_str}`")
                total_sec += song.duration
            if len(state.queue) > 10:
                lines.append(f"\n*… e altri **{len(state.queue) - 10}** brani*")

            m, s = divmod(total_sec, 60)
            h, m = divmod(m, 60)
            total_str = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

            e.add_field(
                name=f"📋  Prossimi — {len(state.queue)} brani  ({total_str})",
                value="\n".join(lines),
                inline=False,
            )

        _footer(e)
        await ctx.send(embed=e)

    # ── !nowplaying ───────────────────────────────────────────────────────────
    @commands.command(name="nowplaying", aliases=["np"], help="Mostra la canzone in riproduzione.")
    async def nowplaying(self, ctx: commands.Context):
        state = self._get_state(ctx.guild)
        if state.current is None:
            await ctx.send(embed=_embed("❌ Niente in riproduzione", "Non c'è nessuna canzone in riproduzione.", color=0xe74c3c))
            return
        await ctx.send(embed=_song_embed(state.current))

    # ── !volume ───────────────────────────────────────────────────────────────
    @commands.command(name="volume", aliases=["vol"], help="Imposta il volume (0-100).")
    async def volume(self, ctx: commands.Context, vol: int):
        state = self._get_state(ctx.guild)

        if not 0 <= vol <= 100:
            await ctx.send(embed=_embed("❌ Valore non valido", "Inserisci un valore tra **0** e **100**.", color=0xe74c3c))
            return

        state.volume = vol / 100.0

        if state.voice_client and state.voice_client.source:
            if isinstance(state.voice_client.source, discord.PCMVolumeTransformer):
                state.voice_client.source.volume = state.volume

        bar = _volume_bar(vol)
        emoji = "🔇" if vol == 0 else ("🔉" if vol < 50 else "🔊")
        e = _embed(f"{emoji}  Volume impostato", f"{bar}  **{vol}%**", color=COLOR_INFO)
        await ctx.send(embed=e)

    # ── !volup ────────────────────────────────────────────────────────────────
    @commands.command(name="volup", aliases=["vu"], help="Aumenta il volume del 10%.")
    async def volup(self, ctx: commands.Context):
        state = self._get_state(ctx.guild)
        new_vol = min(100, int(state.volume * 100) + 10)
        await ctx.invoke(self.volume, vol=new_vol)

    # ── !voldown ──────────────────────────────────────────────────────────────
    @commands.command(name="voldown", aliases=["vd"], help="Abbassa il volume del 10%.")
    async def voldown(self, ctx: commands.Context):
        state = self._get_state(ctx.guild)
        new_vol = max(0, int(state.volume * 100) - 10)
        await ctx.invoke(self.volume, vol=new_vol)

    # ── !shuffle ──────────────────────────────────────────────────────────────
    @commands.command(name="shuffle", help="Mescola la coda in modo casuale.")
    async def shuffle(self, ctx: commands.Context):
        state = self._get_state(ctx.guild)
        if not state.queue:
            await ctx.send(embed=_embed("❌ Coda vuota", "Non ci sono brani in coda da mescolare.", color=0xe74c3c))
            return
        q_list = list(state.queue)
        random.shuffle(q_list)
        state.queue = deque(q_list)
        await ctx.send(embed=_embed("🔀  Coda mischiata!", f"**{len(state.queue)}** brani mescolati casualmente. Buona fortuna! 🎲", color=COLOR_ACTION))

    # ── !clear ────────────────────────────────────────────────────────────────
    @commands.command(name="clear", help="Svuota la coda (non ferma la canzone corrente).")
    async def clear(self, ctx: commands.Context):
        state = self._get_state(ctx.guild)
        state.queue.clear()
        await ctx.send(embed=_embed("🗑️  Coda svuotata", "La coda è stata cancellata con successo.", color=COLOR_ACTION))

    # ── !loop ─────────────────────────────────────────────────────────────────
    @commands.command(name="loop", help="Attiva/disattiva la ripetizione della canzone corrente.")
    async def loop(self, ctx: commands.Context):
        state = self._get_state(ctx.guild)
        state.loop = not state.loop
        if state.loop:
            await ctx.send(embed=_embed("🔁  Loop attivato", "La canzone corrente verrà ripetuta all'infinito.", color=COLOR_SUCCESS))
        else:
            await ctx.send(embed=_embed("➡️  Loop disattivato", "La coda riprenderà normalmente.", color=COLOR_ACTION))

    # ── !leave ────────────────────────────────────────────────────────────────
    @commands.command(name="leave", aliases=["disconnect", "dc"], help="Disconnette il bot dal canale vocale.")
    async def leave(self, ctx: commands.Context):
        state = self._get_state(ctx.guild)
        if state.voice_client and state.voice_client.is_connected():
            state.queue.clear()
            state.current = None
            state.loop = False
            await state.voice_client.disconnect()
            state.voice_client = None
            await ctx.send(embed=_embed("👋  Ciao ciao!", "Disconnesso dal canale vocale. A presto! 🎵", color=COLOR_INFO))
        else:
            await ctx.send(embed=_embed("❌  Errore", "Non sono connesso a nessun canale.", color=COLOR_ERROR))

    # ── !help ─────────────────────────────────────────────────────────────────
    @commands.command(name="help", aliases=["h"], help="Mostra questo messaggio di aiuto.")
    async def help(self, ctx: commands.Context):
        p = BOT_PREFIX
        e = discord.Embed(
            description="Il tuo **DJ personale** su Discord. Musica da YouTube e Spotify, sempre con voi! 🎧",
            color=COLOR_PLAYING,
        )
        e.set_author(name="🎵  MaziBot — Lista comandi")
        e.add_field(
            name="▶️  Riproduzione",
            value=(
                f"`{p}play <testo/URL>` — YouTube: cerca o link diretto\n"
                f"`{p}search <testo>` — Mostra 5 risultati YouTube\n"
                f"`{p}spotify <URL>` — Playlist / album / singolo Spotify\n"
                f"`{p}pause` · `{p}resume` — Pausa / riprendi\n"
                f"`{p}skip` — Salta il brano corrente\n"
                f"`{p}stop` — Ferma tutto e svuota la coda\n"
                f"`{p}leave` — Disconnetti il bot"
            ),
            inline=False,
        )
        e.add_field(
            name="📋  Coda",
            value=(
                f"`{p}queue` — Visualizza la coda\n"
                f"`{p}nowplaying` — Brano corrente con dettagli\n"
                f"`{p}shuffle` — Mescola la coda casualmente\n"
                f"`{p}clear` — Svuota la coda\n"
                f"`{p}loop` — Attiva / disattiva ripetizione"
            ),
            inline=False,
        )
        e.add_field(
            name="🔊  Volume",
            value=(
                f"`{p}volume <0–100>` — Imposta il volume\n"
                f"`{p}volup` (+10%)  ·  `{p}voldown` (-10%)"
            ),
            inline=False,
        )
        e.add_field(
            name="⚡  Alias rapidi",
            value="`!p` `!s` `!q` `!np` `!r` `!vol` `!vu` `!vd` `!sp` `!dc`",
            inline=False,
        )
        _footer(e, ctx.author)
        await ctx.send(embed=e)


# ──────────────────────────────────────────────────────────────────────────────
# Utility
# ──────────────────────────────────────────────────────────────────────────────
def _volume_bar(vol: int, length: int = 10) -> str:
    filled = round(vol / 100 * length)
    return "█" * filled + "░" * (length - filled)


# ──────────────────────────────────────────────────────────────────────────────
# Setup
# ──────────────────────────────────────────────────────────────────────────────
async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
