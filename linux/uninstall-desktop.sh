#!/usr/bin/env bash
# Removes the applications-menu entry that linux/install-desktop.sh added.
set -euo pipefail

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
rm -f "$DATA_HOME/applications/ytdlp-gui.desktop"
rm -f "$DATA_HOME/icons/hicolor/256x256/apps/ytdlp-gui.png"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DATA_HOME/applications" 2>/dev/null || true
echo "Removed the yt-dlp GUI menu entry."
