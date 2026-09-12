#!/bin/bash
# Registers the native messaging host for Firefox specifically — Firefox
# reads a different directory than Chrome-family browsers on both macOS
# and Linux, and uses "allowed_extensions" (a gecko extension ID) instead
# of Chrome's "allowed_origins" (a chrome-extension:// URL). Reuses the
# same native-host/native_host.py; only the manifest destination and
# shape differ. Untested on Linux — written to Mozilla's documented path.
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
GECKO_ID="ytdlp-gui@dotcomaki.dev"
HOST_NAME="com.dotcomaki.ytdlpgui"

chmod +x "$NATIVE_HOST_PATH"

MANIFEST=$(cat <<EOF
{
  "name": "$HOST_NAME",
  "description": "Sends YouTube URLs from the browser extension to the yt-dlp GUI app",
  "path": "$NATIVE_HOST_PATH",
  "type": "stdio",
  "allowed_extensions": ["$GECKO_ID"]
}
EOF
)

case "$(uname -s)" in
  Darwin)
    TARGET_DIR="$HOME/Library/Application Support/Mozilla/NativeMessagingHosts"
    ;;
  Linux)
    TARGET_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/mozilla/native-messaging-hosts"
    # Mozilla's own documented Linux location (not under XDG_CONFIG_HOME)
    ALT_TARGET_DIR="$HOME/.mozilla/native-messaging-hosts"
    ;;
  *)
    echo "Unsupported OS: $(uname -s). This script covers macOS and Linux only."
    exit 1
    ;;
esac

mkdir -p "$TARGET_DIR"
echo "$MANIFEST" > "$TARGET_DIR/$HOST_NAME.json"
echo "Installed: $TARGET_DIR/$HOST_NAME.json"

if [ -n "$ALT_TARGET_DIR" ]; then
  mkdir -p "$ALT_TARGET_DIR"
  echo "$MANIFEST" > "$ALT_TARGET_DIR/$HOST_NAME.json"
  echo "Installed: $ALT_TARGET_DIR/$HOST_NAME.json"
fi

echo "Done. Fully quit and relaunch Firefox for the change to take effect."
