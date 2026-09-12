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

**Qt (QtWebEngine) — alternative:** install `PyQt5 PyQtWebEngine` inside the venv below, alongside `pywebview`, instead of the GTK packages above.

Then install `pywebview` from the project root — **use a virtualenv**, not a plain `pip install`:

```bash
cd ..   # project root
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Almost every current Linux distro's system Python enforces [PEP 668](https://peps.python.org/pep-0668/) and refuses a plain `pip install` outside a virtualenv (`error: externally-managed-environment`) — a venv is the standard, distro-blessed way around that, not a workaround specific to this project. **The browser extension auto-detects a `venv/` or `.venv/` folder in the project root**, so once it exists there's nothing extra to configure — the native messaging host picks it up automatically.

## ffmpeg and yt-dlp

These are separate CLI tools, not Python packages, so they don't need the venv — install via your distro's package manager:
```bash
sudo apt install ffmpeg yt-dlp      # or dnf/pacman equivalent
```
`app.py` looks for both on `PATH` plus a couple of common install locations (`/usr/bin`, `~/.local/bin` for a `pip install --user yt-dlp`), so either install method works.

## Running the app

From the project root, with the venv active (`source venv/bin/activate`, if not already):
```bash
python3 app.py
python3 app.py "https://youtube.com/watch?v=..."   # pre-filled
```
No need to activate anything for the browser extension's launches — `native-host/native_host.py` finds the `venv/` interpreter on its own.

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
