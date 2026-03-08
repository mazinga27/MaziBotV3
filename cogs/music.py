"""
cogs/music.py — MaziBot Music Cog 🎵
Slash commands per riproduzione YouTube + Spotify, coda, volume e altro.
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
from discord import app_commands
from discord.ext import commands
from spotipy.oauth2 import SpotifyClientCredentials

from config import (
    SPOTIFY_CLIENT_ID,
    SPOTIFY_CLIENT_SECRET,
    YDL_FLAT_OPTIONS,
    YDL_OPTIONS,
)

log = logging.getLogger("MaziBot.Music")

# ── Palette colori embed ──────────────────────────────────────────────────────
COLOR_PLAYING = 0x1DB954
COLOR_QUEUE   = 0x5865F2
COLOR_ACTION  = 0xF5A623
COLOR_SUCCESS = 0x2ECC71
COLOR_ERROR   = 0xED4245
COLOR_INFO    = 0x3498DB
COLOR_SPOTIFY = 0x1DB954

# ── Auto-cancellazione messaggi (secondi) ─────────────────────────────────────
DEL_SHORT  = 5    # conferme rapide (skip, stop, pause, loop…)
DEL_MEDIUM = 15   # info (aggiunto in coda, errori, volume…)
DEL_LONG   = 25   # embed ricchi (coda, now playing, Spotify)


# ── Modello canzone ───────────────────────────────────────────────────────────
@dataclass
class Song:
    title: str
    url: str                        # URL stream audio diretto
    webpage_url: str                # URL pagina YouTube
    duration: int = 0
    thumbnail: str = ""
    requester: discord.Member = field(default=None)

    @property
    def duration_str(self) -> str:
        m, s = divmod(self.duration, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ── Stato per guild ───────────────────────────────────────────────────────────
class GuildState:
    def __init__(self):
        self.queue: deque[Song] = deque()
        self.current: Optional[Song] = None
        self.volume: float = 0.5        # 50% di default (0.0–1.0)
        self.loop: bool = False
        self.voice_client: Optional[discord.VoiceClient] = None

    def is_playing(self) -> bool:
        return self.voice_client is not None and self.voice_client.is_playing()

    def is_paused(self) -> bool:
        return self.voice_client is not None and self.voice_client.is_paused()

    def is_active(self) -> bool:
        return self.is_playing() or self.is_paused()


# ── Helpers yt-dlp ────────────────────────────────────────────────────────────
def _extract_info(query: str) -> Optional[dict]:
    """Estrae info audio da YouTube con retry su formati progressivamente più permissivi."""
    if not query.startswith("http"):
        query = f"ytsearch:{query}"

    # Catena di formati: dal più selettivo al più permissivo
    format_fallbacks = [
        None,           # usa YDL_OPTIONS invariato (bestaudio/best con estensioni)
        "bestaudio/best",            # senza vincoli di estensione
        "best",                      # qualsiasi formato disponibile
    ]

    for fmt in format_fallbacks:
        opts = dict(YDL_OPTIONS)
        if fmt is not None:
            opts["format"] = fmt
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                data = ydl.extract_info(query, download=False)
                if data is None:
                    return None
                if "entries" in data:
                    entries = [e for e in data["entries"] if e]
                    return entries[0] if entries else None
                return data
            except yt_dlp.utils.DownloadError as exc:
                err = str(exc)
                if "Requested format is not available" in err:
                    log.debug(f"yt-dlp formato '{opts.get('format')}' non disponibile, retry...")
                    continue  # prova il formato successivo
                # Errore non legato al formato — abbandona
                log.warning(f"yt-dlp: impossibile trovare '{query}' — {exc}")
                return None

    log.warning(f"yt-dlp: nessun formato disponibile per '{query}'")
    return None


def _build_song(info: dict, requester: discord.Member) -> Song:
    url = info.get("url", "")
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


# ── Helpers Spotify ───────────────────────────────────────────────────────────
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
    sp = _get_spotify_client()
    if sp is None:
        return []
    tracks: list[str] = []

    def _query(t: dict) -> str:
        artists = ", ".join(a["name"] for a in t.get("artists", []))
        return f"{t.get('name', '')} {artists}".strip()

    if "playlist" in url:
        results = sp.playlist_tracks(url)
        while results:
            for item in results.get("items", []):
                if track := item.get("track"):
                    tracks.append(_query(track))
            results = sp.next(results) if results.get("next") else None
    elif "album" in url:
        results = sp.album_tracks(url)
        while results:
            for item in results.get("items", []):
                tracks.append(_query(item))
            results = sp.next(results) if results.get("next") else None
    elif "track" in url:
        tracks.append(_query(sp.track(url)))
    return tracks


# ── Helpers embed ─────────────────────────────────────────────────────────────
def _footer(embed: discord.Embed, requester: discord.Member = None) -> discord.Embed:
    if requester:
        embed.set_footer(
            text=f"Richiesto da {requester.display_name}  •  MaziBot 🎵",
            icon_url=requester.display_avatar.url,
        )
    else:
        embed.set_footer(text="MaziBot 🎵")
    embed.timestamp = discord.utils.utcnow()
    return embed


async def _auto_delete(msg: discord.Message, delay: float) -> None:
    """Cancella un messaggio dopo 'delay' secondi, ignorando errori di permesso."""
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except (discord.NotFound, discord.Forbidden):
        pass


async def _followup_send(
    interaction: discord.Interaction,
    embed: discord.Embed,
    delete_after: float | None = None,
    ephemeral: bool = False,
) -> discord.Message:
    """Invia un followup e schedula la cancellazione automatica.
    Necessario perché Webhook.send() non supporta delete_after nativamente.
    """
    msg = await interaction.followup.send(embed=embed, wait=True, ephemeral=ephemeral)
    if delete_after is not None and not ephemeral:
        asyncio.get_event_loop().create_task(_auto_delete(msg, delete_after))
    return msg


def _embed(title: str, description: str = "", color: int = COLOR_INFO) -> discord.Embed:
    return _footer(discord.Embed(title=title, description=description, color=color))


def _song_embed(song: Song, label: str = "▶️  In riproduzione", color: int = COLOR_PLAYING) -> discord.Embed:
    e = discord.Embed(description=f"### [{song.title}]({song.webpage_url})", color=color)
    e.set_author(name=label)
    e.add_field(name="⏱️  Durata", value=f"`{song.duration_str}`", inline=True)
    e.add_field(name="🔗  Link",   value=f"[YouTube]({song.webpage_url})", inline=True)
    if song.thumbnail:
        e.set_image(url=song.thumbnail)
    return _footer(e, song.requester)


def _volume_bar(vol: int, length: int = 10) -> str:
    filled = round(vol / 100 * length)
    return "█" * filled + "░" * (length - filled)


# ── Music Cog ─────────────────────────────────────────────────────────────────
class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._states: dict[int, GuildState] = {}

    def _state(self, guild: discord.Guild) -> GuildState:
        if guild.id not in self._states:
            self._states[guild.id] = GuildState()
        return self._states[guild.id]

    async def _ensure_voice(self, interaction: discord.Interaction) -> bool:
        """Connette al voice channel dell'utente. Deve essere chiamato dopo defer()."""
        if interaction.user.voice is None:
            await interaction.followup.send(
                embed=_embed("❌  Errore", "Devi essere in un canale vocale!", color=COLOR_ERROR),
                ephemeral=True,
            )
            return False
        state = self._state(interaction.guild)
        channel = interaction.user.voice.channel
        if state.voice_client is None or not state.voice_client.is_connected():
            state.voice_client = await channel.connect()
            log.info(f"[{interaction.guild.name}] Connesso a '{channel.name}'")
        elif state.voice_client.channel != channel:
            await state.voice_client.move_to(channel)
            log.info(f"[{interaction.guild.name}] Spostato in '{channel.name}'")
        return True

    def _play_next(self, channel: discord.TextChannel, state: GuildState, guild_name: str):
        """Callback post-brano: avvia il prossimo o notifica coda vuota."""
        if state.loop and state.current:
            state.queue.appendleft(state.current)

        if not state.queue:
            state.current = None
            asyncio.run_coroutine_threadsafe(
                channel.send(
                    embed=_embed("📭  Coda terminata",
                        "Non ci sono altri brani.\nUsa `/play` per aggiungerne uno!", color=COLOR_INFO),
                    delete_after=DEL_MEDIUM,
                ),
                self.bot.loop,
            )
            return

        next_song = state.queue.popleft()
        state.current = next_song
        asyncio.run_coroutine_threadsafe(
            self._stream(channel, state, next_song, guild_name),
            self.bot.loop,
        )

    async def _stream(self, channel: discord.TextChannel, state: GuildState, song: Song, guild_name: str):
        """Avvia la riproduzione di un brano con URL fresco da YouTube."""
        if state.voice_client is None or not state.voice_client.is_connected():
            return
        try:
            # Ri-estrae sempre un URL fresco: gli URL YouTube scadono in pochi minuti
            source_url = song.url
            if song.webpage_url:
                fresh = await asyncio.get_event_loop().run_in_executor(None, _extract_info, song.webpage_url)
                if fresh and (fresh_url := fresh.get("url", "")):
                    source_url = fresh_url

            # FFmpegOpusAudio: FFmpeg gestisce l'encoding Opus — niente libopus di sistema.
            # Il volume è iniettato come filtro FFmpeg.
            source = discord.FFmpegOpusAudio(
                source_url,
                before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                options=f"-vn -filter:a volume={state.volume:.2f}",
            )
            state.voice_client.play(
                source,
                after=lambda err: (
                    log.error(f"[{guild_name}] Errore playback: {err}")
                    if err else self._play_next(channel, state, guild_name)
                ),
            )
            log.info(f"[{guild_name}] ▶ {song.title} ({song.duration_str})")
            await channel.send(embed=_song_embed(song), delete_after=DEL_LONG)

        except Exception as exc:
            log.error(f"[{guild_name}] Errore stream: {type(exc).__name__}: {exc}", exc_info=True)
            msg = str(exc) if str(exc) else type(exc).__name__
            await channel.send(
                embed=_embed("❌  Errore stream", f"`{msg}`\nRiprova con `/play`.", color=COLOR_ERROR),
                delete_after=DEL_MEDIUM,
            )
            self._play_next(channel, state, guild_name)

    # ═══════════════════════════════════════════════════════════════════════════
    # SLASH COMMANDS
    # ═══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="play", description="Riproduci un brano da YouTube: testo di ricerca o URL diretto.")
    @app_commands.describe(query="Testo da cercare o URL YouTube / playlist")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        if not await self._ensure_voice(interaction):
            return

        state = self._state(interaction.guild)
        info = await asyncio.get_event_loop().run_in_executor(None, _extract_info, query)

        if info is None:
            await _followup_send(interaction,
                embed=_embed("❌  Non trovato", f"Nessun risultato per: `{query}`", color=COLOR_ERROR),
                delete_after=DEL_MEDIUM,
            )
            return

        song = _build_song(info, interaction.user)

        if state.is_active():
            state.queue.append(song)
            e = discord.Embed(description=f"### [{song.title}]({song.webpage_url})", color=COLOR_QUEUE)
            e.set_author(name="➕  Aggiunto in coda")
            e.add_field(name="⏱️  Durata",    value=f"`{song.duration_str}`", inline=True)
            e.add_field(name="📋  Posizione", value=f"`#{len(state.queue)}`",  inline=True)
            if song.thumbnail:
                e.set_thumbnail(url=song.thumbnail)
            await _followup_send(interaction, embed=_footer(e, interaction.user), delete_after=DEL_MEDIUM)
        else:
            state.current = song
            await _followup_send(interaction,
                embed=_embed("🔍  Trovato!", f"Avvio **{song.title}**…", color=COLOR_INFO),
                delete_after=DEL_SHORT,
            )
            await self._stream(interaction.channel, state, song, interaction.guild.name)

    @app_commands.command(name="search", description="Cerca un brano su YouTube e mostra i 5 migliori risultati.")
    @app_commands.describe(query="Testo da cercare su YouTube")
    async def search(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        with yt_dlp.YoutubeDL(YDL_FLAT_OPTIONS) as ydl:
            data = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ydl.extract_info(f"ytsearch5:{query}", download=False)
            )

        if not data or not data.get("entries"):
            await _followup_send(interaction,
                embed=_embed("❌  Nessun risultato", f"Nessun brano trovato per: `{query}`", color=COLOR_ERROR),
                delete_after=DEL_MEDIUM,
            )
            return

        entries = [e for e in data["entries"] if e][:5]
        lines = "\n".join(
            f"`{i+1}.` [{e.get('title','?')}](https://www.youtube.com/watch?v={e.get('id','')}) — `{e.get('duration_string','?')}`"
            for i, e in enumerate(entries)
        )
        e = discord.Embed(title="🔍  Risultati ricerca", description=lines, color=COLOR_INFO)
        e.set_footer(text="Usa /play <testo> per riprodurre  •  MaziBot 🎵")
        e.timestamp = discord.utils.utcnow()
        await _followup_send(interaction, embed=e, delete_after=DEL_LONG)

    @app_commands.command(name="spotify", description="Carica una playlist, album o singolo da Spotify.")
    @app_commands.describe(url="URL Spotify di playlist, album o singolo")
    async def spotify(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer()
        if not await self._ensure_voice(interaction):
            return
        if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
            await _followup_send(interaction,
                embed=_embed("❌  Spotify non configurato",
                    "Aggiungi `SPOTIFY_CLIENT_ID` e `SPOTIFY_CLIENT_SECRET` nel file `.env`.", color=COLOR_ERROR),
                delete_after=DEL_MEDIUM,
            )
            return

        track_names = await asyncio.get_event_loop().run_in_executor(None, _get_spotify_tracks, url)
        if not track_names:
            await _followup_send(interaction,
                embed=_embed("❌  Errore Spotify",
                    "Impossibile leggere l'URL. Controlla che sia una playlist/album/traccia pubblica.", color=COLOR_ERROR),
                delete_after=DEL_MEDIUM,
            )
            return

        state = self._state(interaction.guild)
        loading = discord.Embed(
            description=f"Ricerca di **{len(track_names)}** brani su YouTube…\n*Questo può richiedere qualche secondo.*",
            color=COLOR_SPOTIFY,
        )
        loading.set_author(name="Spotify  ·  Caricamento playlist")
        loading_msg = await interaction.followup.send(embed=_footer(loading, interaction.user), wait=True)

        added = 0
        loop = asyncio.get_event_loop()
        for i, name in enumerate(track_names):
            info = await loop.run_in_executor(None, _extract_info, name)
            if info is None:
                continue
            song = _build_song(info, interaction.user)
            if i == 0 and not state.is_active():
                state.current = song
                await self._stream(interaction.channel, state, song, interaction.guild.name)
            else:
                state.queue.append(song)
            added += 1

        log.info(f"[{interaction.guild.name}] Spotify: {added}/{len(track_names)} brani caricati")
        done = discord.Embed(description=f"**{added}** brani aggiunti in coda con successo!", color=COLOR_SUCCESS)
        done.set_author(name="✅  Playlist Spotify caricata")
        await loading_msg.edit(embed=_footer(done, interaction.user))
        asyncio.get_event_loop().create_task(_auto_delete(loading_msg, DEL_LONG))

    @app_commands.command(name="skip", description="Salta il brano corrente e passa al prossimo.")
    async def skip(self, interaction: discord.Interaction):
        state = self._state(interaction.guild)
        if not state.is_active():
            await interaction.response.send_message(
                embed=_embed("❌  Niente da skippare", "Non c'è nessun brano in riproduzione.", color=COLOR_ERROR),
                ephemeral=True,
            )
            return
        state.loop = False
        state.voice_client.stop()
        log.info(f"[{interaction.guild.name}] Skip da {interaction.user.display_name}")
        await interaction.response.send_message(
            embed=_embed("⏭️  Skippato", f"Brano saltato da **{interaction.user.display_name}**.", color=COLOR_ACTION),
            delete_after=DEL_SHORT,
        )

    @app_commands.command(name="stop", description="Ferma la riproduzione e svuota tutta la coda.")
    async def stop(self, interaction: discord.Interaction):
        state = self._state(interaction.guild)
        state.queue.clear()
        state.current = None
        state.loop = False
        if state.voice_client:
            state.voice_client.stop()
        log.info(f"[{interaction.guild.name}] Stop da {interaction.user.display_name}")
        await interaction.response.send_message(
            embed=_embed("⏹️  Fermato", "Riproduzione fermata e coda svuotata.", color=COLOR_ACTION),
            delete_after=DEL_SHORT,
        )

    @app_commands.command(name="pause", description="Mette in pausa la riproduzione.")
    async def pause(self, interaction: discord.Interaction):
        state = self._state(interaction.guild)
        if state.is_playing():
            state.voice_client.pause()
            await interaction.response.send_message(
                embed=_embed("⏸️  In pausa", "Usa `/resume` per riprendere.", color=COLOR_ACTION),
                delete_after=DEL_SHORT,
            )
        else:
            await interaction.response.send_message(
                embed=_embed("❌  Errore", "Non c'è niente in riproduzione.", color=COLOR_ERROR), ephemeral=True
            )

    @app_commands.command(name="resume", description="Riprende la riproduzione dopo una pausa.")
    async def resume(self, interaction: discord.Interaction):
        state = self._state(interaction.guild)
        if state.is_paused():
            state.voice_client.resume()
            await interaction.response.send_message(
                embed=_embed("▶️  Ripresa!", "Riproduzione ripresa con successo.", color=COLOR_SUCCESS),
                delete_after=DEL_SHORT,
            )
        else:
            await interaction.response.send_message(
                embed=_embed("❌  Errore", "Non c'è niente in pausa.", color=COLOR_ERROR), ephemeral=True
            )

    @app_commands.command(name="queue", description="Mostra la coda di riproduzione attuale.")
    async def queue(self, interaction: discord.Interaction):
        state = self._state(interaction.guild)
        if not state.current and not state.queue:
            await interaction.response.send_message(
                embed=_embed("📭  Coda vuota", "Usa `/play` per aggiungere un brano!", color=COLOR_INFO),
                ephemeral=True,
            )
            return

        e = discord.Embed(color=COLOR_QUEUE)
        e.set_author(name="🎶  Coda di riproduzione")

        if state.current:
            loop_tag = "  🔁" if state.loop else ""
            e.add_field(
                name=f"▶️  In riproduzione{loop_tag}",
                value=f"> [{state.current.title}]({state.current.webpage_url})\n> `{state.current.duration_str}`",
                inline=False,
            )
            if state.current.thumbnail:
                e.set_thumbnail(url=state.current.thumbnail)

        if state.queue:
            total_sec = sum(s.duration for s in state.queue)
            lines = [
                f"`{i:02d}.` [{s.title}]({s.webpage_url}) — `{s.duration_str}`"
                for i, s in enumerate(list(state.queue)[:10], 1)
            ]
            if len(state.queue) > 10:
                lines.append(f"\n*… e altri **{len(state.queue) - 10}** brani*")
            h, rem = divmod(total_sec, 3600)
            m, s_r = divmod(rem, 60)
            total_str = f"{h}h {m}m {s_r}s" if h else f"{m}m {s_r}s"
            e.add_field(
                name=f"📋  Prossimi — {len(state.queue)} brani  ({total_str})",
                value="\n".join(lines),
                inline=False,
            )

        await interaction.response.send_message(embed=_footer(e), delete_after=DEL_LONG)

    @app_commands.command(name="nowplaying", description="Mostra il brano attualmente in riproduzione.")
    async def nowplaying(self, interaction: discord.Interaction):
        state = self._state(interaction.guild)
        if state.current is None:
            await interaction.response.send_message(
                embed=_embed("❌  Niente in riproduzione", "Usa `/play` per avviare un brano.", color=COLOR_ERROR),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(embed=_song_embed(state.current), delete_after=DEL_LONG)

    @app_commands.command(name="volume", description="Imposta il volume della riproduzione (0–100).")
    @app_commands.describe(livello="Volume da impostare (0 = muto, 100 = massimo)")
    async def volume(self, interaction: discord.Interaction, livello: app_commands.Range[int, 0, 100]):
        state = self._state(interaction.guild)
        state.volume = livello / 100.0
        bar = _volume_bar(livello)
        emoji = "🔇" if livello == 0 else ("🔉" if livello < 50 else "🔊")
        await interaction.response.send_message(
            embed=_embed(f"{emoji}  Volume impostato",
                f"{bar}  **{livello}%**\n*Attivo dal prossimo brano.*", color=COLOR_INFO),
            delete_after=DEL_MEDIUM,
        )

    @app_commands.command(name="volup", description="Aumenta il volume del 10%.")
    async def volup(self, interaction: discord.Interaction):
        state = self._state(interaction.guild)
        new_vol = min(100, int(state.volume * 100) + 10)
        state.volume = new_vol / 100.0
        bar = _volume_bar(new_vol)
        emoji = "🔉" if new_vol < 50 else "🔊"
        await interaction.response.send_message(
            embed=_embed(f"{emoji}  Volume aumentato",
                f"{bar}  **{new_vol}%**\n*Attivo dal prossimo brano.*", color=COLOR_INFO),
            delete_after=DEL_MEDIUM,
        )

    @app_commands.command(name="voldown", description="Abbassa il volume del 10%.")
    async def voldown(self, interaction: discord.Interaction):
        state = self._state(interaction.guild)
        new_vol = max(0, int(state.volume * 100) - 10)
        state.volume = new_vol / 100.0
        bar = _volume_bar(new_vol)
        emoji = "🔇" if new_vol == 0 else ("🔉" if new_vol < 50 else "🔊")
        await interaction.response.send_message(
            embed=_embed(f"{emoji}  Volume abbassato",
                f"{bar}  **{new_vol}%**\n*Attivo dal prossimo brano.*", color=COLOR_INFO),
            delete_after=DEL_MEDIUM,
        )

    @app_commands.command(name="shuffle", description="Mescola casualmente i brani in coda.")
    async def shuffle(self, interaction: discord.Interaction):
        state = self._state(interaction.guild)
        if not state.queue:
            await interaction.response.send_message(
                embed=_embed("❌  Coda vuota", "Non ci sono brani da mescolare.", color=COLOR_ERROR),
                ephemeral=True,
            )
            return
        q_list = list(state.queue)
        random.shuffle(q_list)
        state.queue = deque(q_list)
        await interaction.response.send_message(
            embed=_embed("🔀  Coda mischiata!", f"**{len(state.queue)}** brani mescolati casualmente. 🎲",
                color=COLOR_ACTION),
            delete_after=DEL_SHORT,
        )

    @app_commands.command(name="clear", description="Rimuove tutti i brani dalla coda (il brano corrente continua).")
    async def clear(self, interaction: discord.Interaction):
        state = self._state(interaction.guild)
        state.queue.clear()
        await interaction.response.send_message(
            embed=_embed("🗑️  Coda svuotata", "Tutti i brani in coda sono stati rimossi.", color=COLOR_ACTION),
            delete_after=DEL_SHORT,
        )

    @app_commands.command(name="loop", description="Attiva o disattiva la ripetizione del brano corrente.")
    async def loop(self, interaction: discord.Interaction):
        state = self._state(interaction.guild)
        state.loop = not state.loop
        if state.loop:
            await interaction.response.send_message(
                embed=_embed("🔁  Loop attivato", "Il brano corrente verrà ripetuto all'infinito.", color=COLOR_SUCCESS),
                delete_after=DEL_SHORT,
            )
        else:
            await interaction.response.send_message(
                embed=_embed("➡️  Loop disattivato", "La coda riprenderà normalmente.", color=COLOR_ACTION),
                delete_after=DEL_SHORT,
            )

    @app_commands.command(name="leave", description="Disconnette il bot dal canale vocale.")
    async def leave(self, interaction: discord.Interaction):
        state = self._state(interaction.guild)
        if state.voice_client and state.voice_client.is_connected():
            state.queue.clear()
            state.current = None
            state.loop = False
            await state.voice_client.disconnect()
            state.voice_client = None
            log.info(f"[{interaction.guild.name}] Disconnesso da {interaction.user.display_name}")
            await interaction.response.send_message(
                embed=_embed("👋  Ciao ciao!", "Disconnesso dal canale vocale. A presto! 🎵", color=COLOR_INFO),
                delete_after=DEL_SHORT,
            )
        else:
            await interaction.response.send_message(
                embed=_embed("❌  Errore", "Non sono connesso a nessun canale vocale.", color=COLOR_ERROR),
                ephemeral=True,
            )

    @app_commands.command(name="help", description="Mostra la lista di tutti i comandi di MaziBot.")
    async def help(self, interaction: discord.Interaction):
        e = discord.Embed(
            description="Il tuo **DJ personale** su Discord. Musica da YouTube e Spotify, sempre con voi! 🎧",
            color=COLOR_PLAYING,
        )
        e.set_author(name="🎵  MaziBot — Lista comandi")
        e.add_field(
            name="▶️  Riproduzione",
            value=(
                "`/play <testo/URL>` — YouTube: cerca o link diretto\n"
                "`/search <testo>` — Mostra 5 risultati YouTube\n"
                "`/spotify <URL>` — Playlist / album / singolo Spotify\n"
                "`/pause` · `/resume` — Pausa / riprendi\n"
                "`/skip` — Salta il brano corrente\n"
                "`/stop` — Ferma tutto e svuota la coda\n"
                "`/leave` — Disconnetti il bot"
            ),
            inline=False,
        )
        e.add_field(
            name="📋  Coda",
            value=(
                "`/queue` — Visualizza la coda\n"
                "`/nowplaying` — Brano corrente con dettagli\n"
                "`/shuffle` — Mescola la coda casualmente\n"
                "`/clear` — Svuota la coda\n"
                "`/loop` — Attiva / disattiva ripetizione"
            ),
            inline=False,
        )
        e.add_field(
            name="🔊  Volume",
            value=(
                "`/volume <0–100>` — Imposta il volume\n"
                "`/volup` (+10%)  ·  `/voldown` (-10%)"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=_footer(e, interaction.user))


# ── Setup ─────────────────────────────────────────────────────────────────────
async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
