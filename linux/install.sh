#!/bin/bash
# Linux equivalent of native-host/install.sh — installs the SAME native
# messaging host (native-host/native_host.py) and extension, just into
# Linux's XDG config paths instead of macOS's Library paths. Written to
# Chrome's documented native messaging spec and standard XDG locations;
# not verified on an actual Linux machine, so if a path below doesn't
# match your distro/browser, check `chrome://version` -> "Profile Path"
# to confirm your browser's actual config directory.
set -e

SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

NATIVE_HOST_PATH="$PROJECT_DIR/native-host/native_host.py"
EXTENSION_ID="$(cat "$PROJECT_DIR/extension/extension_id.txt")"
HOST_NAME="com.dotcomaki.ytdlpgui"

chmod +x "$NATIVE_HOST_PATH"

MANIFEST=$(cat <<EOF
{
  "name": "$HOST_NAME",
  "description": "Sends YouTube URLs from the browser extension to the yt-dlp GUI app",
  "path": "$NATIVE_HOST_PATH",
  "type": "stdio",
  "allowed_origins": ["chrome-extension://$EXTENSION_ID/"]
}
EOF
)

CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"

TARGETS=(
  "$CONFIG_HOME/google-chrome/NativeMessagingHosts"
  "$CONFIG_HOME/google-chrome-beta/NativeMessagingHosts"
  "$CONFIG_HOME/chromium/NativeMessagingHosts"
  "$CONFIG_HOME/BraveSoftware/Brave-Browser/NativeMessagingHosts"
  "$CONFIG_HOME/microsoft-edge/NativeMessagingHosts"
  "$CONFIG_HOME/vivaldi/NativeMessagingHosts"
)

INSTALLED=0
for TARGET_DIR in "${TARGETS[@]}"; do
  BROWSER_BASE="$(dirname "$TARGET_DIR")"
  [ -d "$BROWSER_BASE" ] || continue
  mkdir -p "$TARGET_DIR"
  echo "$MANIFEST" > "$TARGET_DIR/$HOST_NAME.json"
  echo "Installed: $TARGET_DIR/$HOST_NAME.json"
  INSTALLED=$((INSTALLED + 1))
done

if [ "$INSTALLED" -eq 0 ]; then
  echo "No supported Chromium-based browser config directory found under $CONFIG_HOME."
  echo "If your browser is installed but wasn't detected (e.g. via Flatpak/Snap, which"
  echo "sandbox config to a different path), find its real config dir via"
  echo "chrome://version -> \"Profile Path\", then create:"
  echo "  <that dir>/NativeMessagingHosts/$HOST_NAME.json"
  echo "with the same content install.sh would have written (see this script)."
  exit 1
fi

echo "Done. Fully quit and relaunch your browser for the change to take effect."
