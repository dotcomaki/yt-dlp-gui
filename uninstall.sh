#!/usr/bin/env bash
# Undoes what install.sh did: the native messaging host manifests in every
# browser it knows about, the project virtualenv, and the app entry in
# ~/Applications (macOS) or the applications menu (Linux).
#
#   ./uninstall.sh            # leave settings, history and profiles alone
#   ./uninstall.sh --purge    # remove ~/.config/ytdlp-gui as well
#
# It does not touch yt-dlp, ffmpeg or the browser extension itself —
# remove those the way you installed them (the extension from your
# browser's extensions page).
set -euo pipefail

usage() {
  cat <<'USAGE'
Undoes what install.sh did: native messaging host manifests, the project
virtualenv, and the app entry in ~/Applications or the applications menu.

  ./uninstall.sh            leave settings, history and profiles alone
  ./uninstall.sh --purge    remove ~/.config/ytdlp-gui as well

yt-dlp, ffmpeg and the browser extension itself are left alone — remove
those the way you installed them (the extension from your browser's
extensions page).
USAGE
}

PURGE=0
for arg in "$@"; do
  case "$arg" in
    --purge) PURGE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
PROJECT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"

HOST_NAME="com.dotcomaki.ytdlpgui"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
REMOVED=0

remove() {
  if [ -e "$1" ] || [ -L "$1" ]; then
    rm -rf "$1"
    echo "Removed: $1"
    REMOVED=$((REMOVED + 1))
  fi
}

echo "=== Native messaging hosts ==="
# Every directory install.sh, linux/install.sh and firefox-extension/install.sh
# can write to, on either OS — harmless to look for all of them anywhere.
HOST_DIRS=(
  "$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
  "$HOME/Library/Application Support/Arc/User Data/NativeMessagingHosts"
  "$HOME/Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts"
  "$HOME/Library/Application Support/Microsoft Edge/NativeMessagingHosts"
  "$HOME/Library/Application Support/Chromium/NativeMessagingHosts"
  "$HOME/Library/Application Support/Vivaldi/NativeMessagingHosts"
  "$HOME/Library/Application Support/Mozilla/NativeMessagingHosts"
  "$CONFIG_HOME/google-chrome/NativeMessagingHosts"
  "$CONFIG_HOME/google-chrome-beta/NativeMessagingHosts"
  "$CONFIG_HOME/chromium/NativeMessagingHosts"
  "$CONFIG_HOME/BraveSoftware/Brave-Browser/NativeMessagingHosts"
  "$CONFIG_HOME/microsoft-edge/NativeMessagingHosts"
  "$CONFIG_HOME/vivaldi/NativeMessagingHosts"
  "$HOME/.mozilla/native-messaging-hosts"
)
for DIR in "${HOST_DIRS[@]}"; do
  remove "$DIR/$HOST_NAME.json"
done

echo
echo "=== App entry ==="
remove "$HOME/Applications/yt-dlp GUI.app"
if [ -x "$PROJECT_DIR/linux/uninstall-desktop.sh" ]; then
  "$PROJECT_DIR/linux/uninstall-desktop.sh" >/dev/null 2>&1 && echo "Removed: applications-menu entry (if there was one)"
fi

echo
echo "=== Project files ==="
remove "$PROJECT_DIR/venv"
remove "$PROJECT_DIR/.venv"
remove "$PROJECT_DIR/native-host/$HOST_NAME.json"
for XPI in "$PROJECT_DIR"/firefox-extension/*.xpi; do
  [ -e "$XPI" ] && remove "$XPI"
done

echo
if [ "$PURGE" -eq 1 ]; then
  echo "=== Settings ==="
  remove "$CONFIG_HOME/ytdlp-gui"
else
  if [ -d "$CONFIG_HOME/ytdlp-gui" ]; then
    echo "Kept your settings, history and profiles in $CONFIG_HOME/ytdlp-gui"
    echo "(re-run with --purge to remove those too)."
  fi
fi

echo
if [ "$REMOVED" -eq 0 ]; then
  echo "Nothing to remove — it looks like this was never installed here."
else
  echo "Done. Remove the extension itself from your browser's extensions page,"
  echo "and delete this folder whenever you like."
fi
