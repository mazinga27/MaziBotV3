#!/bin/bash
# start.sh — Script di avvio MaziBot per Railway

echo "[MaziBot] Avvio in corso..."
echo "[MaziBot] Python: $(python --version)"
echo "[MaziBot] Ambiente: ${RAILWAY_ENVIRONMENT:-locale}"

# Aggiorna yt-dlp all'ultima versione ad ogni deploy.
# YouTube cambia la bot-detection frequentemente; yt-dlp rilascia fix in ore.
echo "[MaziBot] Aggiornamento yt-dlp..."
pip install -U yt-dlp -q && echo "[MaziBot] yt-dlp: $(yt-dlp --version)"

exec python bot.py
