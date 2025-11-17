#!/bin/bash

set -e

echo "======================================"
echo "  Tmux Web Manager - Starting..."
echo "======================================"
echo ""

# Verifica che tmux sia installato
if ! command -v tmux &> /dev/null; then
    echo "ERROR: tmux is not installed!"
    exit 1
fi

# Verifica che Python sia installato
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python3 is not installed!"
    exit 1
fi

# Crea link simbolici per tutte le directory tmux dell'host
if [ -d "/host-tmp" ]; then
    for tmux_dir in /host-tmp/tmux-*; do
        if [ -d "$tmux_dir" ]; then
            dir_name=$(basename "$tmux_dir")
            if [ ! -e "/tmp/$dir_name" ]; then
                ln -s "$tmux_dir" "/tmp/$dir_name"
                echo "✓ Linked tmux directory: $dir_name"
            fi
        fi
    done
fi

echo "✓ Tmux installed: $(tmux -V)"
echo "✓ Python installed: $(python3 --version)"
echo "✓ Listening on port 7777"
echo ""
echo "Access the application at: http://localhost:7777"
echo ""
echo "======================================"
echo ""

# Avvia l'applicazione
exec python3 /app/app.py
