# 🎵 MaziBot — Discord Music Bot

**MaziBot** è un bot Discord per riprodurre musica in voice channel. Supporta YouTube (link o ricerca testo), playlist Spotify, controllo volume e molti altri comandi.

---

## 📋 Comandi

| Comando | Alias | Descrizione |
|---|---|---|
| `!play <testo/URL>` | `!p` | Riproduci da YouTube (testo o link) |
| `!search <testo>` | — | Cerca su YouTube (mostra 5 risultati) |
| `!spotify <URL>` | `!sp` | Carica playlist/album/traccia Spotify |
| `!skip` | `!s` | Salta la canzone corrente |
| `!stop` | — | Ferma la riproduzione e svuota la coda |
| `!pause` | — | Mette in pausa |
| `!resume` | `!r` | Riprende la riproduzione |
| `!queue` | `!q` | Mostra la coda |
| `!nowplaying` | `!np` | Mostra il brano corrente |
| `!volume <0-100>` | `!vol` | Imposta il volume |
| `!volup` | `!vu` | Aumenta volume del 10% |
| `!voldown` | `!vd` | Abbassa volume del 10% |
| `!shuffle` | — | Mescola la coda |
| `!clear` | — | Svuota la coda |
| `!loop` | — | Attiva/disattiva ripetizione |
| `!leave` | `!dc` | Disconnette il bot |
| `!help` | `!h` | Mostra la lista comandi |

---

## 🚀 Setup Locale

### 1. Requisiti di sistema
- Python 3.10+
- **FFmpeg** installato e nel PATH

**Installare FFmpeg:**
- **Mac:** `brew install ffmpeg`
- **Ubuntu/Debian:** `sudo apt install ffmpeg`
- **Windows:** [Scarica da ffmpeg.org](https://ffmpeg.org/download.html)

### 2. Installa le dipendenze Python
```bash
pip install -r requirements.txt
```

### 3. Crea il file `.env`
```bash
cp .env.example .env
```
Apri `.env` e inserisci i tuoi token:
```env
DISCORD_TOKEN=il_tuo_token
SPOTIFY_CLIENT_ID=il_tuo_client_id
SPOTIFY_CLIENT_SECRET=il_tuo_client_secret
```

### 4. Avvia il bot
```bash
python bot.py
```

---

## 🔑 Ottenere i Token

### Discord Bot Token
1. Vai su [discord.com/developers/applications](https://discord.com/developers/applications)
2. Crea una **New Application** → sezione **Bot** → clicca **Reset Token**
3. Copia il token nel `.env`
4. Abilita **Message Content Intent** nelle impostazioni del Bot
5. Vai su **OAuth2 → URL Generator**:
   - Scopes: `bot`
   - Bot Permissions: `Connect`, `Speak`, `Send Messages`, `Read Messages/View Channels`, `Embed Links`
6. Usa l'URL generato per aggiungere il bot al tuo server

### Spotify API
1. Vai su [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Crea una **New App** (nome a piacere, Redirect URI: `http://localhost`)
3. Copia **Client ID** e **Client Secret** nel `.env`

> ⚠️ Spotify non permette il streaming diretto: MaziBot legge i metadati della playlist e cerca ogni brano su YouTube. Questo è il comportamento standard di tutti i music bot.

---

## ☁️ Hosting Gratuito su Railway

1. Fai il push del codice su **GitHub** (senza il file `.env`!)
2. Registrati su [railway.app](https://railway.app)
3. **New Project → Deploy from GitHub repo**
4. Vai in **Variables** e aggiungi:
   - `DISCORD_TOKEN`
   - `SPOTIFY_CLIENT_ID`
   - `SPOTIFY_CLIENT_SECRET`
5. Aggiungi anche il plugin **FFmpeg** oppure usa il buildpack `apt` con `ffmpeg` in `nixpacks.toml`
6. Il bot partirà automaticamente come **worker** (non web server)

### nixpacks.toml (per FFmpeg su Railway)
Crea un file `nixpacks.toml` nella root del progetto:
```toml
[phases.setup]
nixPkgs = ["ffmpeg"]
```

---

## 🗂️ Struttura del Progetto

```
MaziBotV3/
├── bot.py              # Entry point
├── config.py           # Variabili d'ambiente
├── cogs/
│   └── music.py        # Tutti i comandi musicali
├── .env                # Token (NON committare!)
├── .env.example        # Template
├── requirements.txt    # Dipendenze
├── Procfile            # Per Railway/Render
├── nixpacks.toml       # FFmpeg su Railway
└── README.md
```

---

## 📝 Note
- Il bot si connette automaticamente al canale vocale dell'utente che esegue il comando
- Il volume di default è **50%**
- Le playlist Spotify con molti brani impiegano qualche secondo ad essere caricate (ricerca su YouTube per ogni brano)
