#!/bin/bash
# start.sh — Wrapper di avvio per MaziBot su Railway
# Trova libopus nel Nix store (path con hash variabile) e la aggiunge a LD_LIBRARY_PATH

# Cerca libopus.so nel Nix store
OPUS_LIB=$(find /nix/store -name 'libopus.so*' -type f 2>/dev/null | head -1)

if [ -n "$OPUS_LIB" ]; then
    OPUS_DIR=$(dirname "$OPUS_LIB")
    export LD_LIBRARY_PATH="${OPUS_DIR}:${LD_LIBRARY_PATH}"
    echo "[start.sh] libopus trovata: $OPUS_LIB"
    echo "[start.sh] LD_LIBRARY_PATH -> $LD_LIBRARY_PATH"
else
    echo "[start.sh] ⚠️  libopus NON trovata nel Nix store"
fi

exec python bot.py
