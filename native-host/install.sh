#!/bin/bash
# Generates the native messaging host manifest with this machine's absolute
# path (Chrome's native messaging spec requires an absolute path — there's
# no portable/relative form) and installs it for every detected Chromium
# browser. Safe to re-run any time the project moves or gets re-cloned.
set -e

SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"

NATIVE_HOST_PATH="$SCRIPT_DIR/native_host.py"
EXTENSION_ID="$(cat "$SCRIPT_DIR/../extension/extension_id.txt")"
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

TARGETS=(
  "$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
  "$HOME/Library/Application Support/Arc/User Data/NativeMessagingHosts"
  "$HOME/Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts"
  "$HOME/Library/Application Support/Microsoft Edge/NativeMessagingHosts"
  "$HOME/Library/Application Support/Chromium/NativeMessagingHosts"
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
  echo "No supported Chromium-based browser found (Chrome, Arc, Brave, Edge, Chromium)."
  exit 1
fi

echo "Done. Fully quit and relaunch your browser for the change to take effect."
