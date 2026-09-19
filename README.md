# yt-dlp GUI

![Platform](https://img.shields.io/badge/platform-macOS-black?logo=apple&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Linux-FCC624?logo=linux&logoColor=black)
![Python](https://img.shields.io/badge/python-3.9%2B-blue?logo=python&logoColor=white)
![yt-dlp](https://img.shields.io/badge/powered%20by-yt--dlp-red)

A small dark-themed desktop GUI for [yt-dlp](https://github.com/yt-dlp/yt-dlp), built with Python + [pywebview](https://pywebview.flowrl.com/). Includes a browser extension that sends the current tab — or any right-clicked link — straight to the app.

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

- Python 3.9+, `pywebview` + `certifi` (`pip install -r requirements.txt`; `certifi` is what lets the update check reach GitHub over HTTPS from python.org's macOS Python, whose bundled OpenSSL ships with an empty trust store) — **Linux only:** don't run that command as-is; `pywebview` needs a system-level GTK or Qt backend pip can't provide, and most distros now block a plain `pip install` outside a virtualenv anyway (PEP 668). See [`linux/README.md`](linux/README.md#system-dependencies) for the actual steps.
- `ffmpeg` — required to merge separate video+audio streams; without it, downloads above 720p will have no audio. macOS: `brew install ffmpeg`. Linux: `sudo apt install ffmpeg` (or your distro's equivalent)
- A JavaScript runtime — YouTube now requires one (yt-dlp runs the player's challenge-solving JS through it); without one yt-dlp warns on every YouTube download and some formats are missing. `deno` is what yt-dlp recommends (`brew install deno`, `sudo apt install deno`, or `curl -fsSL https://deno.land/install.sh | sh`); `node` works too (`brew install node`, `sudo apt install nodejs`, or an nvm install). The app looks on your `PATH`, in the Homebrew/`/usr/local`/`/usr/bin` locations, `~/.deno/bin`, `~/.bun/bin` and the newest `~/.nvm/versions/node/*`, and passes what it finds to yt-dlp as `--js-runtimes` — same as it passes `--ffmpeg-location` — because apps launched from the browser extension get a minimal `PATH` that yt-dlp's own search doesn't cope with. The sidebar shows which one is in use.
- `yt-dlp` on your `PATH` (or, macOS only, at `/usr/local/bin/yt-dlp` or `~/Downloads/yt-dlp_macos`)

## Run from source

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

Pass a URL as an argument to pre-fill it: `python3 app.py "https://youtube.com/watch?v=..."`.

## Browser extension (Chrome/Arc/Brave/Edge/Chromium/Vivaldi on macOS; Chrome/Chromium/Brave/Edge/Vivaldi on Linux; Firefox — see below)

Clicking the extension's toolbar icon sends the current tab's URL to the yt-dlp GUI (launching it if it isn't open). It works on any `http(s)` page — yt-dlp supports around 1,800 sites plus a generic extractor for pages with a media file on them, so the button is greyed out only on the browser's own pages (`chrome://`, `about:`, `file:`). Right-click a link, a video element, or the page for **Download with yt-dlp**, which sends the link's target rather than the page you're on — handy on a search-results or playlist page. **Alt+Shift+Y** does the same as clicking the icon (change it under `chrome://extensions/shortcuts`).

**How it works:** the extension talks to a native messaging host (`native-host/native_host.py`) registered with the browser. If the app is already open, the host hands the URL to it over a local socket (`~/.config/ytdlp-gui/app.sock`, or under `$XDG_RUNTIME_DIR` on Linux) — the URL lands in the box with a preview and the window comes to the front; no second window, ever. The extension's icon flashes ✓ when the URL was delivered and ! when it wasn't. Only when nothing is listening does the host launch the app:
- **macOS:** launches via `open -a yt-dlp.app --args <url>` — a small self-locating app bundle checked into the repo (no `/Applications` install needed). This matters, not just for convenience: spawning `python3` as a *direct child* of the native messaging host inherits the browser's process ancestry for macOS's Gatekeeper "responsible launcher" tracking, which can trigger a false-positive "is damaged, move to Trash" dialog blaming the browser for a file it never touched — even for a correctly-signed, unquarantined interpreter. `open -a` hands the launch to LaunchServices as an independent process, breaking that ancestry chain.
- **Linux:** runs `python3 app.py <url>` directly (no such Gatekeeper-equivalent issue exists there). Checks the project's own `venv/` first, then a few common `python3` install locations, and uses the first one that exists — it deliberately doesn't execute candidates to probe them — since apps launched outside an interactive shell get a more minimal `PATH` than your Terminal does.

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

## URLs without the extension

`python3 app.py "<url>"` from this folder pre-fills the URL (or hands it to the app if it's already open).

## Features

- Paste any number of URLs (one per line) — they queue up and download one after another, each with its own status, progress bar and cancel. Add more while things are running; a failed one doesn't stop the rest. Titles fill in as yt-dlp resolves them. When one fails for a reason the app recognises — YouTube demanding a signed-in session, a format that doesn't exist, a 403/extractor error that usually means "update yt-dlp", a private or removed video — the row says so in plain words with a button that goes straight to the fix (browser cookies, the format list, Update / Clear cache). Failed and cancelled rows get a **Retry** button that re-queues them with the same settings; finished rows get **Reveal**. **Pause** holds the queue (whatever's running finishes) and the header shows what's downloading, the combined speed, and what's waiting; the window title says "yt-dlp — 2 downloading". Anything unfinished when you quit is picked up again next launch — paused, with a note, so nothing starts unasked. **Simultaneous downloads** (Advanced → Network, default 2) run several queue items at once; the rate limit is treated as the *total* and split across the downloads actually running, and the Log tab tags lines by job only while more than one is. That's separate from **concurrent fragments** (`-N`, same panel), which fetches pieces of *one* video in parallel — the big speed-up for YouTube — alongside a throttled-rate trigger, fragment retries, and sleep-between-downloads/requests for polite bulk runs.
- Preview before downloading: paste a URL and a card shows the title, uploader, duration and thumbnail (or "Playlist · N videos") once yt-dlp has looked it up in the background. **Formats** opens the actual format table for that video — resolution, fps, codecs, size, bitrate — and clicking a row sets it as the custom format (video-only streams get `+bestaudio` merged in). Uses your cookies/proxy/geo settings, same as the real download.
- **Clips and chapters**: under a single video's preview, a **Clip** row takes a start and end (`1:23`, `1:23:45`, or seconds; leave one empty for "from the start" / "to the end") and downloads just that range (`--download-sections`, ffmpeg required). *Exact cuts* re-encodes around the cut points so the clip starts precisely where asked instead of at the previous keyframe — slower. If the video has chapters they're listed with checkboxes: tick some and each becomes its own queue row and file (`Title - Chapter.mp4`), or choose *split into one file per chapter* for a single download that ffmpeg cuts into chapter files afterwards (faster, and keeps the full video). Clips and chapters show up in History with their range, so *Again* re-downloads the same piece.
- **Playlist picker**: when the URL is a playlist or channel, the preview lists every video with a checkbox (all on by default) — untick the ones you don't want, or use **All**. Download expands the ticked videos into individual queue rows, each with its own title, progress and cancel, and they share the parallel-download slots like anything else. If you hit Download before the lookup finishes, the playlist URL goes through as a single job and yt-dlp handles it whole, same as before.
- Quality presets — Best, 4K, 1440p, 1080p, 720p, 480p, **Compatible** (prefers H.264 + AAC in an mp4, which QuickTime, TVs and phones play without complaint; "Best" on YouTube is usually VP9/AV1 + Opus), Audio only — or a raw custom format string. Advanced → Format has both **remux** (lossless container change) and **recode** (re-encode).
- Advanced tab covering format/merge options, filenames, playlists, subtitles, thumbnails/metadata, audio extraction, network (proxy/rate-limit/retries), auth & cookies, SponsorBlock, geo-bypass, post-run commands, debug flags, and a raw extra-arguments passthrough
- Settings persist across launches (`~/.config/ytdlp-gui/settings.json`, password field never saved to disk) — **Import…**/**Export…** in the Advanced tab move a whole configuration between machines or back one up, same password exclusion applied
- **Profiles** (Download tab): save the whole current configuration — every Advanced-tab option plus the destination folder — under a name like "Podcast" or "Archive", and switch between them from a dropdown. The dropdown shows "(modified)" once you've changed anything since applying one; **Save…** with the same name updates it. Stored in `profiles.json` beside the settings, same password exclusion.
- **Skip what's already downloaded** (Advanced → Playlist): re-running a channel or playlist then only fetches what's new. The skip list is yt-dlp's `--download-archive`, built from the History tab — remove an entry there (or clear history) and that video is downloadable again. The preview marks already-downloaded videos and unticks them in the playlist picker; a skipped one shows "Already in History — skipped" in the queue rather than pretending it downloaded. Optionally stop a playlist at the first already-downloaded video (`--break-on-existing`), the channel-subscription pattern.
- **History** tab: every finished download (success or failure — cancellations aren't kept) with its title, time, quality, and the final file path as yt-dlp reported it after merging/extraction. **Reveal** shows the file in Finder (or opens its folder on Linux), **Again** re-queues it with the exact settings it was downloaded with, and there's per-row remove and Clear history. Capped at the newest 500 entries in `history.json`.
- yt-dlp update check on launch (quietly skipped if offline) — the sidebar status turns yellow with an **Update to …** button when a newer release exists. Standalone-binary installs update in-app via `yt-dlp -U`, Homebrew via `brew upgrade yt-dlp`, pip installs via the script's own interpreter's `pip`; distro-package installs get the right package-manager command printed instead. Click the yt-dlp status line to re-check any time. **Clear cache** next to it runs `yt-dlp --rm-cache-dir`, the standard first step for 403s and signature errors. yt-dlp's extractors break often as sites change, and "update yt-dlp" is almost always the fix, so this is worth keeping green.
- Live per-item progress, speed/ETA, and a separate streaming Log tab (Copy / Clear; capped at the newest 5,000 lines; passwords and proxy credentials are masked in the echoed command)
- URLs sent from the browser extension while the app is open are added to the box (Advanced → Notifications → *Browser extension* to have them start downloading immediately instead)
- Desktop notification when the queue finishes (Advanced → Notifications, on by default) — one per batch with finished/failed counts, or the title when it's a single download. macOS via Notification Center; Linux needs `notify-send`.

## Running the tests

Covers `build_args()` (the settings-dict-to-yt-dlp-argv translator — the highest-value target, since every Advanced-tab option flows through it), the `find_ytdlp`/`find_ffmpeg`/`find_js_runtime` candidate-list detection, the download queue, preview, history, profiles, notifications and update checker, and the frontend's settings helpers (`ui/utils.js`). Tests point `XDG_CONFIG_HOME` at a temp dir (`tests/conftest.py`), so they never touch your real `~/.config/ytdlp-gui`. Deliberately out of scope: anything needing a real browser extension load or an actual GUI window — those stay manual, same as the rest of this README.

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest tests/ -v

node --test tests/test_utils.js
```

Both run in CI (`.github/workflows/tests.yml`) on macOS and Linux for the Python suite, Linux for the JS one.
