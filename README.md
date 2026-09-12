# yt-dlp GUI

![Platform](https://img.shields.io/badge/platform-macOS-black?logo=apple&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Linux-FCC624?logo=linux&logoColor=black)
![Python](https://img.shields.io/badge/python-3.9%2B-blue?logo=python&logoColor=white)
![yt-dlp](https://img.shields.io/badge/powered%20by-yt--dlp-red)

A small dark-themed desktop GUI for [yt-dlp](https://github.com/yt-dlp/yt-dlp), built with Python + [pywebview](https://pywebview.flowrl.com/). Includes a browser extension that sends the current YouTube tab straight to the app.

**Platform:** macOS is primary and what's actually been tested; Linux support exists but is untested (written to spec) — see [`linux/README.md`](linux/README.md) for Linux-specific setup (an extra system dependency `pywebview` needs, and Linux's native-messaging paths). Every section below is written for macOS unless a Linux note is called out inline.

## Requirements

- Python 3.9+, `pywebview` (`pip install -r requirements.txt`) — **Linux only:** don't run that command as-is; `pywebview` needs a system-level GTK or Qt backend pip can't provide, and most distros now block a plain `pip install` outside a virtualenv anyway (PEP 668). See [`linux/README.md`](linux/README.md#system-dependencies) for the actual steps.
- `ffmpeg` — required to merge separate video+audio streams; without it, downloads above 720p will have no audio. macOS: `brew install ffmpeg`. Linux: `sudo apt install ffmpeg` (or your distro's equivalent)
- `yt-dlp` on your `PATH` (or, macOS only, at `/usr/local/bin/yt-dlp` or `~/Downloads/yt-dlp_macos`)

## Run from source

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

Pass a URL as an argument to pre-fill it: `python3 app.py "https://youtube.com/watch?v=..."`.

## Browser extension (Chrome/Arc/Brave/Edge/Chromium/Vivaldi on macOS; Chrome/Chromium/Brave/Edge/Vivaldi on Linux; Firefox — see below)

Clicking the extension's toolbar icon on a YouTube page launches the yt-dlp GUI with that video's URL pre-filled. The icon is only enabled while you're on a `youtube.com` page.

**How it works:** the extension talks to a native messaging host (`native-host/native_host.py`) registered with the browser, which runs `python3 app.py <url>` directly — no app bundle or install step involved. It checks a few common `python3` install locations (macOS and Linux) and picks the first one that actually has `pywebview` installed, since apps launched outside an interactive shell get a more minimal `PATH` than your Terminal does. This part of the code is shared across both platforms — only the install script below differs.

**Setup:**

1. Register the native messaging host for your browser(s) — **macOS:**
   ```bash
   ./native-host/install.sh
   ```
   **Linux:**
   ```bash
   ./linux/install.sh
   ```
   Each generates the host manifest with an absolute path to `native_host.py` on your machine (Chrome's native messaging spec requires an absolute path — there's no portable form) and installs it into every detected Chromium browser's config directory for that OS (macOS: `~/Library/Application Support/...`; Linux: `~/.config/...`). The generated file itself isn't committed to git since it's machine-specific; re-run the appropriate script any time you re-clone or move the project.
2. Fully quit and relaunch your browser
3. Go to `chrome://extensions` (this URL works in every Chromium-based browser, not just Chrome — Arc, Brave, Edge, Vivaldi too), enable **Developer mode**, click **Load unpacked**, and select the `extension/` folder
4. Pin the extension's icon to the toolbar

The extension's `manifest.json` embeds a fixed signing key so its ID is always `palmchbgajiepnoehdaapiocpkglhabf`, matching what `install.sh` writes into the host manifest's `allowed_origins` — no manual ID copying needed.

### Firefox

Firefox needs its own extension folder (`firefox-extension/`) since its manifest format and native-messaging conventions differ from Chrome's, plus it requires either Mozilla-signing or a Nightly/Developer Edition build with signature enforcement disabled to install an extension persistently — there's no equivalent to Chrome's "Load unpacked" dev mode. See [`firefox-extension/README.md`](firefox-extension/README.md) for the full setup (untested — written to Mozilla's documented spec).

## Non-YouTube URLs

yt-dlp supports far more sites than YouTube, but the extension only triggers on `youtube.com`. For anything else, just run `python3 app.py "<url>"` from this folder.

## Features

- URL input, quality presets (Best / 720p / 480p / Audio-only) or a raw custom format string
- Advanced tab covering format/merge options, filenames, playlists, subtitles, thumbnails/metadata, audio extraction, network (proxy/rate-limit/retries), auth & cookies, SponsorBlock, geo-bypass, post-run commands, debug flags, and a raw extra-arguments passthrough
- Live progress bar, speed/ETA, and a separate streaming Log tab
- Cancel an in-progress download
