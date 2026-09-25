#!/usr/bin/env bash
# Adds a "yt-dlp GUI" entry to the applications menu, so the app can be
# launched like any other rather than only from a terminal or the browser
# extension. Safe to re-run; run linux/uninstall-desktop.sh to remove it.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APPS_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/256x256/apps"
DESKTOP_FILE="$APPS_DIR/ytdlp-gui.desktop"

# The same interpreter the native messaging host would pick: the project
# venv if there is one, otherwise whatever python3 is on PATH.
PYTHON="$PROJECT_DIR/venv/bin/python3"
[ -x "$PYTHON" ] || PYTHON="$PROJECT_DIR/.venv/bin/python3"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3 || echo python3)"

mkdir -p "$APPS_DIR" "$ICON_DIR"
cp "$PROJECT_DIR/assets/icon-256.png" "$ICON_DIR/ytdlp-gui.png"

# Exec is parsed by the desktop spec's own rules, not the shell: anything
# with a space needs double quotes, and " ` $ \ inside must be escaped.
desktop_quote() {
  printf '"%s"' "$(printf '%s' "$1" | sed 's/[\\"`$]/\\&/g')"
}
EXEC_PYTHON="$(desktop_quote "$PYTHON")"
EXEC_SCRIPT="$(desktop_quote "$PROJECT_DIR/app.py")"

cat > "$DESKTOP_FILE" <<DESKTOP
[Desktop Entry]
Type=Application
Name=yt-dlp GUI
GenericName=Video Downloader
Comment=Download video and audio with yt-dlp
Exec=$EXEC_PYTHON $EXEC_SCRIPT %u
Path=$PROJECT_DIR
Icon=ytdlp-gui
Terminal=false
Categories=AudioVideo;Network;Utility;
Keywords=youtube;video;download;yt-dlp;
StartupWMClass=app.py
DESKTOP

chmod +x "$DESKTOP_FILE"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS_DIR" 2>/dev/null || true

echo "Installed: $DESKTOP_FILE"
echo "\"yt-dlp GUI\" should now appear in your applications menu."
echo "Re-run this after moving the project folder — the entry holds an absolute path."
