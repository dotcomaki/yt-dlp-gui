# yt-dlp GUI

![Platform](https://img.shields.io/badge/platform-macOS-black?logo=apple&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Linux-FCC624?logo=linux&logoColor=black)
![Python](https://img.shields.io/badge/python-3.9%2B-blue?logo=python&logoColor=white)
![yt-dlp](https://img.shields.io/badge/powered%20by-yt--dlp-red)

A small dark-themed desktop GUI for [yt-dlp](https://github.com/yt-dlp/yt-dlp), built with Python + [pywebview](https://pywebview.flowrl.com/). Includes a browser extension that sends the current YouTube tab straight to the app.

**Platform:** macOS is primary and what's actually been tested; Linux support exists but is untested (written to spec) — see [`linux/README.md`](linux/README.md) for Linux-specific setup (an extra system dependency `pywebview` needs, and Linux's native-messaging paths). Every section below is written for macOS unless a Linux note is called out inline.

## Quick setup

Download the [latest release](../../releases/latest), extract it, and from inside that folder run:

```bash
./install.sh
```

or, on macOS, just double-click `install.command` in Finder — no Terminal needed.

This installs everything scriptable in one pass: system dependencies (ffmpeg, yt-dlp, and on Linux the GTK backend `pywebview` needs), a project-local virtualenv with `pywebview` installed into it, and the native messaging host for whichever browsers it detects. Pass `--firefox` to also set up the Firefox extension (a few extra manual steps are unavoidable there — see [`firefox-extension/README.md`](firefox-extension/README.md)).

One step genuinely can't be scripted — browsers don't allow installing an unpacked extension from the command line — so the script finishes by printing exactly what to click (`chrome://extensions` → Developer mode → Load unpacked → the `extension/` folder). Safe to re-run any time.

The sections below are what `install.sh` is actually doing under the hood, useful if you want to understand or customize a step, or if you'd rather not run a setup script and do it by hand.

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

**How it works:** the extension talks to a native messaging host (`native-host/native_host.py`) registered with the browser.
- **macOS:** launches via `open -a yt-dlp.app --args <url>` — a small self-locating app bundle checked into the repo (no `/Applications` install needed). This matters, not just for convenience: spawning `python3` as a *direct child* of the native messaging host inherits the browser's process ancestry for macOS's Gatekeeper "responsible launcher" tracking, which can trigger a false-positive "is damaged, move to Trash" dialog blaming the browser for a file it never touched — even for a correctly-signed, unquarantined interpreter. `open -a` hands the launch to LaunchServices as an independent process, breaking that ancestry chain.
- **Linux:** runs `python3 app.py <url>` directly (no such Gatekeeper-equivalent issue exists there). Checks a few common `python3` install locations and picks the first one that actually has `pywebview` installed, since apps launched outside an interactive shell get a more minimal `PATH` than your Terminal does.

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
