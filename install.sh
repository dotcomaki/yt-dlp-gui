#!/bin/bash
# One-shot setup: creates the venv, installs pywebview + ffmpeg + yt-dlp,
# and registers the native messaging host for every detected browser.
# Safe to re-run any time — every step below is idempotent, same as the
# individual native-host/install.sh and linux/install.sh scripts this
# orchestrates rather than duplicates.
#
# Usage:
#   ./install.sh              Chrome-family browsers only (the common case)
#   ./install.sh --firefox    Also register the Firefox extension
set -e

SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
PROJECT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
cd "$PROJECT_DIR"

WITH_FIREFOX=0
for arg in "$@"; do
  case "$arg" in
    --firefox) WITH_FIREFOX=1 ;;
  esac
done

OS="$(uname -s)"

echo "=== yt-dlp GUI setup ($OS) ==="
echo

# --- system dependencies -----------------------------------------------
if [ "$OS" = "Darwin" ]; then
  if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew is required and wasn't found."
    echo "Install it from https://brew.sh, then re-run this script:"
    echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    exit 1
  fi

  if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "Installing ffmpeg..."
    brew install ffmpeg
  else
    echo "ffmpeg already installed: $(command -v ffmpeg)"
  fi

  if ! command -v yt-dlp >/dev/null 2>&1; then
    echo "Installing yt-dlp..."
    brew install yt-dlp
  else
    echo "yt-dlp already installed: $(command -v yt-dlp)"
  fi

elif [ "$OS" = "Linux" ]; then
  if command -v apt-get >/dev/null 2>&1; then
    PKG_INSTALL="sudo apt-get install -y"
    GTK_PKGS="python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1"
  elif command -v dnf >/dev/null 2>&1; then
    PKG_INSTALL="sudo dnf install -y"
    GTK_PKGS="python3-gobject gtk3 webkit2gtk4.1"
  elif command -v pacman >/dev/null 2>&1; then
    PKG_INSTALL="sudo pacman -S --noconfirm"
    GTK_PKGS="python-gobject gtk3 webkit2gtk-4.1"
  else
    echo "No supported package manager found (apt, dnf, pacman)."
    echo "Install pywebview's GTK backend, ffmpeg, and yt-dlp manually — see linux/README.md."
    exit 1
  fi

  echo "Installing system dependencies (pywebview's GTK backend, ffmpeg, yt-dlp)..."
  $PKG_INSTALL $GTK_PKGS ffmpeg yt-dlp

else
  echo "Unsupported OS: $OS. This script covers macOS and Linux only."
  exit 1
fi

echo

# --- python venv ---------------------------------------------------------
if [ ! -x "$PROJECT_DIR/venv/bin/python3" ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
fi
echo "Installing pywebview..."
"$PROJECT_DIR/venv/bin/pip" install --quiet -r requirements.txt
echo "Done — native-host/native_host.py checks venv/ first, so the browser"
echo "extension will use this same environment automatically."
echo

# --- native messaging host ------------------------------------------------
if [ "$OS" = "Darwin" ]; then
  ./native-host/install.sh
else
  ./linux/install.sh
fi
echo

# --- firefox (opt-in) ------------------------------------------------------
if [ "$WITH_FIREFOX" -eq 1 ]; then
  echo "=== Firefox ==="
  ./firefox-extension/install.sh
  ./firefox-extension/build.sh
  echo
  echo "Firefox needs a couple of manual steps beyond this — see"
  echo "firefox-extension/README.md (Nightly/Developer Edition, and disabling"
  echo "signature enforcement in about:config)."
  echo
fi

# --- make it launchable like an app ----------------------------------------
if [ "$(uname -s)" = "Darwin" ] && [ -d "$PROJECT_DIR/yt-dlp.app" ]; then
  echo "=== Applications ==="
  mkdir -p "$HOME/Applications"
  LINK="$HOME/Applications/yt-dlp GUI.app"
  # A symlink, not a copy: the bundle locates the project relative to
  # itself, and copying it would break that.
  if [ -L "$LINK" ] || [ ! -e "$LINK" ]; then
    ln -sfn "$PROJECT_DIR/yt-dlp.app" "$LINK"
    echo "Linked: $LINK"
    echo "It'll show up in Spotlight and Launchpad; drag it to the Dock to keep it there."
  else
    echo "Skipped: $LINK already exists and isn't a symlink."
  fi
  echo
else
  "$PROJECT_DIR/linux/install-desktop.sh" 2>/dev/null || true
fi

# --- final manual step -----------------------------------------------------
echo "=== Almost done ==="
echo
echo "One step this script can't do for you — browsers don't allow installing"
echo "an unpacked extension from the command line:"
echo
echo "  1. Open chrome://extensions in your browser (works in any"
echo "     Chromium-based browser: Chrome, Arc, Brave, Edge, Vivaldi)"
echo "  2. Enable Developer mode"
echo "  3. Click \"Load unpacked\" and select:"
echo "       $PROJECT_DIR/extension"
echo "  4. Pin the extension's icon to the toolbar"
echo
if [ "$WITH_FIREFOX" -eq 1 ]; then
  echo "For Firefox, see firefox-extension/README.md for the equivalent steps."
  echo
fi
echo "Or just run the app directly any time:"
echo "  $PROJECT_DIR/venv/bin/python3 app.py"
if [ "$(uname -s)" = "Darwin" ]; then
  echo "...or open \"yt-dlp GUI\" from Spotlight."
else
  echo "...or launch \"yt-dlp GUI\" from your applications menu."
fi
