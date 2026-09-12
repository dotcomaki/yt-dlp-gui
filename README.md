# yt-dlp GUI

![Platform](https://img.shields.io/badge/platform-macOS-black?logo=apple&logoColor=white)
![Python](https://img.shields.io/badge/python-3.9%2B-blue?logo=python&logoColor=white)
![yt-dlp](https://img.shields.io/badge/powered%20by-yt--dlp-red)

A small dark-themed desktop GUI for [yt-dlp](https://github.com/yt-dlp/yt-dlp), built with Python + [pywebview](https://pywebview.flowrl.com/). Includes a macOS app wrapper and a browser extension that sends the current YouTube tab straight to the app.

## Requirements

- Python 3.9+, `pywebview` (`pip install -r requirements.txt`)
- `ffmpeg` (`brew install ffmpeg`) — required to merge separate video+audio streams; without it, downloads above 720p will have no audio
- `yt-dlp` available at one of: `yt-dlp` on your `PATH`, `/usr/local/bin/yt-dlp`, or `~/Downloads/yt-dlp_macos`

## Run from source

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

Pass a URL as an argument to pre-fill it: `python3 app.py "https://youtube.com/watch?v=..."`.

## The .app

A pre-built `yt-dlp.app` bundle lives at the project root. It's a self-locating shell script wrapper around `python3 app.py` — it resolves its own path (following symlinks) to find this project folder, so there's no hardcoded path baked in and no separate build step needed after edits.

You can run it straight from here, no install step needed:

```bash
open yt-dlp.app
open yt-dlp.app --args "https://youtube.com/watch?v=..."   # pre-filled
```

Want it in the Dock? Just drag `yt-dlp.app` from this folder into the Dock — it doesn't need to live in `/Applications` for that.

If your `python3` is a Homebrew/python.org install rather than Apple's Command Line Tools stub, the launcher checks a few common install locations and picks the first one that actually has `pywebview` installed — this matters because apps launched via `open` (Dock, Spotlight, the browser extension) get a different, more minimal `PATH` than an interactive Terminal shell does.

## Browser extension (Arc / Chrome)

Clicking the extension's toolbar icon on a YouTube page opens the yt-dlp app with that video's URL pre-filled. The icon is only enabled while you're on a `youtube.com` page.

**How it works:** the extension talks to a native messaging host (`native-host/native_host.py`) registered with the browser. The host script locates `yt-dlp.app` relative to itself (a sibling in this project folder) and runs `open -a <path-to-yt-dlp.app> --args <url>` — no `/Applications` install needed.

**Setup:**

1. Register the native messaging host for your browser(s):
   ```bash
   ./native-host/install.sh
   ```
   This generates the host manifest with an absolute path to `native_host.py` on your machine (Chrome's native messaging spec requires an absolute path — there's no portable form) and installs it for every detected Chromium browser (Chrome, Arc, Brave, Edge, Chromium). The generated file itself isn't committed to git since it's machine-specific; re-run this script any time you re-clone or move the project.
2. Fully quit and relaunch your browser
3. Go to `chrome://extensions` (works in Arc too), enable **Developer mode**, click **Load unpacked**, and select the `extension/` folder
4. Pin the extension's icon to the toolbar

The extension's `manifest.json` embeds a fixed signing key so its ID is always `palmchbgajiepnoehdaapiocpkglhabf`, matching what `install.sh` writes into the host manifest's `allowed_origins` — no manual ID copying needed.

## Non-YouTube URLs (Spotlight)

yt-dlp supports far more sites than YouTube, but the extension only triggers on `youtube.com`. `yt-dlp.app` is Spotlight-searchable from wherever this project lives — just launch it blank and paste any URL. If you want a keyboard shortcut or Siri phrase for that, add a Shortcuts.app "Open App" action pointing at yt-dlp.

## Features

- URL input, quality presets (Best / 720p / 480p / Audio-only) or a raw custom format string
- Advanced tab covering format/merge options, filenames, playlists, subtitles, thumbnails/metadata, audio extraction, network (proxy/rate-limit/retries), auth & cookies, SponsorBlock, geo-bypass, post-run commands, debug flags, and a raw extra-arguments passthrough
- Live progress bar, speed/ETA, and a separate streaming Log tab
- Cancel an in-progress download
