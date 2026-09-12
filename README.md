# yt-dlp GUI

![Platform](https://img.shields.io/badge/platform-macOS-black?logo=apple&logoColor=white)
![Python](https://img.shields.io/badge/python-3.9%2B-blue?logo=python&logoColor=white)
![yt-dlp](https://img.shields.io/badge/powered%20by-yt--dlp-red)

A small dark-themed desktop GUI for [yt-dlp](https://github.com/yt-dlp/yt-dlp), built with Python + [pywebview](https://pywebview.flowrl.com/). Includes a browser extension that sends the current YouTube tab straight to the app.

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

## Browser extension (Arc / Chrome)

Clicking the extension's toolbar icon on a YouTube page launches the yt-dlp GUI with that video's URL pre-filled. The icon is only enabled while you're on a `youtube.com` page.

**How it works:** the extension talks to a native messaging host (`native-host/native_host.py`) registered with the browser, which runs `python3 app.py <url>` directly — no app bundle or install step involved. It checks a few common `python3` install locations and picks the first one that actually has `pywebview` installed, since apps launched outside an interactive shell get a more minimal `PATH` than your Terminal does.

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

## Non-YouTube URLs

yt-dlp supports far more sites than YouTube, but the extension only triggers on `youtube.com`. For anything else, just run `python3 app.py "<url>"` from this folder.

## Features

- URL input, quality presets (Best / 720p / 480p / Audio-only) or a raw custom format string
- Advanced tab covering format/merge options, filenames, playlists, subtitles, thumbnails/metadata, audio extraction, network (proxy/rate-limit/retries), auth & cookies, SponsorBlock, geo-bypass, post-run commands, debug flags, and a raw extra-arguments passthrough
- Live progress bar, speed/ETA, and a separate streaming Log tab
- Cancel an in-progress download
