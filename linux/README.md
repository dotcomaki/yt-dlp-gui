# Linux setup

> **Untested.** This is written to `pywebview`'s documented Linux backend
> requirements and Chrome's documented native messaging spec — I don't have
> a Linux machine to actually verify it on. macOS is the primary, tested
> platform (see the [root README](../README.md)); if something here doesn't
> work on your distro, that's expected until someone verifies it end to end.

## System dependencies

Unlike macOS/Windows, `pywebview` on Linux needs a real browser engine
installed at the OS level — pip alone isn't enough. Pick one:

**GTK (WebKit2GTK) — recommended:**
```bash
# Debian/Ubuntu
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1

# Fedora
sudo dnf install python3-gobject gtk3 webkit2gtk4.1

# Arch
sudo pacman -S python-gobject gtk3 webkit2gtk-4.1
```

**Qt (QtWebEngine) — alternative:**
```bash
pip install PyQt5 PyQtWebEngine
```

Then install the Python packages as usual from the project root:
```bash
python3 -m pip install -r ../requirements.txt
```

## ffmpeg and yt-dlp

```bash
sudo apt install ffmpeg      # or dnf/pacman equivalent
python3 -m pip install --user yt-dlp   # or your distro's package
```
`app.py` finds both automatically via `PATH`, so no extra config needed once they're installed.

## Running the app

Same as macOS — from the project root:
```bash
python3 app.py
python3 app.py "https://youtube.com/watch?v=..."   # pre-filled
```

## Browser extension

The extension itself (`extension/`) is plain Chrome-extension JS and needs no changes. Only the native messaging *installation* differs by OS, since Chrome resolves the host manifest from different directories per platform.

1. Register the native messaging host:
   ```bash
   ./install.sh
   ```
   This writes the host manifest into every detected Chromium-based browser's config directory under `~/.config` (Chrome, Chromium, Brave, Edge, Vivaldi) — the Linux equivalent of `native-host/install.sh`'s macOS `~/Library/Application Support` paths. It reuses the same `native-host/native_host.py` and `extension/` — nothing is duplicated, just the install target paths differ.
2. Fully quit and relaunch your browser
3. Go to `chrome://extensions`, enable **Developer mode**, click **Load unpacked**, and select the `extension/` folder
4. Pin the extension's icon to the toolbar

If your browser is a Flatpak or Snap build, its config directory is sandboxed to a different, non-standard path and won't be auto-detected — `install.sh` will tell you to check `chrome://version` → "Profile Path" and create the manifest there manually.
