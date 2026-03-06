#!/bin/bash
# start.sh — Script di avvio MaziBot per Railway
# Usato dal Procfile come: bash start.sh

echo "[MaziBot] Avvio in corso..."
echo "[MaziBot] Python: $(python --version)"
echo "[MaziBot] Ambiente: ${RAILWAY_ENVIRONMENT:-locale}"

exec python bot.py
