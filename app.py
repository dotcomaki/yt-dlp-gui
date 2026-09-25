import datetime
import json
import os
import shlex
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import re
import urllib.parse
import urllib.request

import webview

YTDLP_CANDIDATES = [
    shutil.which("yt-dlp"),
    "/usr/local/bin/yt-dlp",
    os.path.expanduser("~/Downloads/yt-dlp_macos"),   # macOS manual download
    "/usr/bin/yt-dlp",                                 # Linux distro package
    os.path.expanduser("~/.local/bin/yt-dlp"),         # Linux `pip install --user`
]

FFMPEG_CANDIDATES = [
    shutil.which("ffmpeg"),
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    "/usr/bin/ffmpeg",
]


def _nvm_node_candidates():
    """Every ~/.nvm/versions/node/vX.Y.Z/bin/node, newest version first.
    nvm doesn't put node on the PATH of anything that isn't an interactive
    shell, so the app has to find it by hand. The version is parsed
    numerically: string order would rank v9 above v22."""
    root = os.path.expanduser("~/.nvm/versions/node")
    try:
        names = os.listdir(root)
    except OSError:
        return []
    versions = {}
    for name in names:
        m = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", name)
        if m:
            versions[name] = tuple(int(x) for x in m.groups())
    return [os.path.join(root, name, "bin", "node")
            for name in sorted(versions, key=versions.get, reverse=True)]


def _runtime_candidates(name, *extra):
    return [shutil.which(name), f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}",
            f"/usr/bin/{name}", *extra]


# In yt-dlp's own priority order (deno, node, quickjs, bun — see
# `yt-dlp --help`, --js-runtimes). Only deno is enabled by default; the
# others must be named explicitly.
JS_RUNTIME_CANDIDATES = [
    ("deno", _runtime_candidates("deno", os.path.expanduser("~/.deno/bin/deno"))),
    ("node", _runtime_candidates("node", *_nvm_node_candidates())),
    ("quickjs", _runtime_candidates("quickjs")),
    ("bun", _runtime_candidates("bun", os.path.expanduser("~/.bun/bin/bun"))),
]

# yt-dlp's --newline progress lines come in three shapes, and the app has
# to read all of them (verified against yt-dlp 2026.08.19):
#   [download]  71.4% of ~  21.00KiB at    1.19KiB/s ETA Unknown (frag 0/3)
#   [download]   31.00KiB at   15.19MiB/s (00:00:00)      <- total unknown: live, chunked HTTP
#   [download] 100% of  113.71KiB in 00:00:00 at 143.44KiB/s
# Note the spaces after "~" (an estimated total) — requiring a digit there
# meant fragmented and HLS downloads showed no progress at all.
_SIZE = r"[\d.]+\s*[KMGT]?i?B"
_RATE = r"(?:[\d.]+\s*[KMGT]?i?B/s|Unknown\s*B/s)"

PROGRESS_RE = re.compile(
    rf"\[download\]\s+(?P<pct>[\d.]+)%\s+of\s+~?\s*(?P<size>{_SIZE})"
    rf"(?:\s+in\s+(?P<elapsed>[\d:]+))?"
    rf"(?:\s+at\s+(?P<speed>{_RATE}))?"
    rf"(?:\s+ETA\s+(?P<eta>\S+))?"
)

# Total unknown: downloaded size, rate, elapsed — and no percentage at all.
PROGRESS_SIZE_RE = re.compile(
    rf"\[download\]\s+(?P<size>{_SIZE})\s+at\s+(?P<speed>{_RATE})"
    rf"(?:\s+\((?P<elapsed>[\d:]+)\))?"
)


def parse_progress(line):
    """{"pct", "size", "speed", "eta", "elapsed"} for a progress line, or
    None. pct is None when yt-dlp doesn't know the total — the UI then
    shows an indeterminate bar rather than a stuck percentage."""
    m = PROGRESS_RE.search(line)
    if not m:
        m = PROGRESS_SIZE_RE.search(line)
        if not m:
            return None
    groups = m.groupdict()
    pct = groups.get("pct")
    return {
        "pct": float(pct) if pct is not None else None,
        "size": _tidy(groups.get("size")),
        "speed": "" if (groups.get("speed") or "").lower().startswith("unknown") else _tidy(groups.get("speed")),
        "eta": "" if (groups.get("eta") or "").lower() == "unknown" else (groups.get("eta") or ""),
        "elapsed": groups.get("elapsed") or "",
    }


def _tidy(text):
    """yt-dlp pads its numbers ("~   1.00KiB"); collapse that for display."""
    return re.sub(r"\s+", "", text or "")

# Per `yt-dlp --help`: valid for --sponsorblock-mark but not --sponsorblock-remove.
SPONSORBLOCK_MARK_ONLY = {"poi_highlight", "chapter"}

def _capped(height):
    return f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"


QUALITY_FORMATS = {
    "best": "bestvideo+bestaudio/best",
    "2160p": _capped(2160),
    "1440p": _capped(1440),
    "1080p": _capped(1080),
    "720p": _capped(720),
    "480p": _capped(480),
    # "Compatible": prefer H.264 video and AAC audio in an mp4 — what
    # QuickTime, TVs and phones play without complaint, instead of the
    # VP9/AV1+Opus that "best" picks on YouTube. The -S sort does the
    # preferring; the format string stays the plain best-of-each.
    "compat": "bestvideo+bestaudio/best",
    "audio": "bestaudio/best",
}
COMPAT_SORT = "vcodec:h264,res,acodec:m4a"

# What the presets degrade to when ffmpeg is missing: a single stream that
# already contains both video and audio, so nothing needs merging.
NO_FFMPEG_FORMATS = {
    "best": "best[vcodec!=none][acodec!=none]/best",
    "compat": "best[vcodec^=avc1][acodec^=mp4a]/best[ext=mp4]/best",
    **{f"{h}p": f"best[height<={h}][vcodec!=none][acodec!=none]/best[height<={h}]" for h in (2160, 1440, 1080, 720, 480)},
}


def _first_executable(candidates):
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def find_ytdlp():
    return _first_executable(YTDLP_CANDIDATES)


def find_ffmpeg():
    return _first_executable(FFMPEG_CANDIDATES)


def find_js_runtime():
    """(name, path) of the highest-priority JavaScript runtime installed, or
    None. YouTube extraction needs one (its EJS challenge solver) — without
    it yt-dlp warns and some formats go missing."""
    for name, candidates in JS_RUNTIME_CANDIDATES:
        path = _first_executable(candidates)
        if path:
            return name, path
    return None


def config_path(name):
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    config_dir = os.path.join(config_home, "ytdlp-gui")
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, name)


def write_config_file(path_fn, data):
    """{"ok": True} or {"ok": False, "error": "..."} — the UI shows the
    error in the sidebar, since silently not persisting is the worst
    outcome. path_fn is called here so a failure to create the config
    dir is reported the same way as a failure to write the file."""
    try:
        with open(path_fn(), "w") as f:
            json.dump(data, f, indent=2)
        return {"ok": True}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def settings_path():
    return config_path("settings.json")


def profiles_path():
    return config_path("profiles.json")


def history_path():
    return config_path("history.json")


# yt-dlp publishes its channels as separate repositories; the update check
# has to look at the one the user actually follows, or every nightly build
# looks "newer" than stable and vice versa.
RELEASE_APIS = {
    "stable": "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest",
    "nightly": "https://api.github.com/repos/yt-dlp/yt-dlp-nightly-builds/releases/latest",
    "master": "https://api.github.com/repos/yt-dlp/yt-dlp-master-builds/releases/latest",
}


def update_channel(settings):
    channel = ((settings or {}).get("debug") or {}).get("updateChannel") or "stable"
    return channel if channel in RELEASE_APIS else "stable"


def ytdlp_version(path):
    out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
    return out.stdout.strip()


def parse_version(text):
    """yt-dlp versions are dates: '2026.08.19', or '2026.08.19.123456' on
    the nightly channel. Anything else (git hashes, garbage) -> None."""
    parts = []
    for piece in (text or "").strip().split("."):
        if not piece.isdigit():
            return None
        parts.append(int(piece))
    return tuple(parts) or None


def is_newer(latest, current):
    a, b = parse_version(latest), parse_version(current)
    if a is None or b is None:
        return False
    return a > b


def _ssl_context():
    # python.org's macOS Python ships its own OpenSSL with an empty trust
    # store (unless the user ran its "Install Certificates.command"), so
    # plain urlopen fails every HTTPS request with CERTIFICATE_VERIFY_FAILED.
    # certifi's bundle is exactly what that command installs — use it
    # directly when available; Linux/Homebrew pythons work either way.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def fetch_latest_version(timeout=5, channel="stable"):
    req = urllib.request.Request(
        RELEASE_APIS.get(channel, RELEASE_APIS["stable"]),
        headers={"User-Agent": "yt-dlp-gui", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        return json.load(resp).get("tag_name")


def detect_install_method(path):
    """How this yt-dlp got installed decides how it can be updated:
    `yt-dlp -U` only self-updates the standalone binary; pip/Homebrew
    installs refuse it and need their own package manager instead.

    Returns (method, interpreter): method is one of 'homebrew', 'package',
    'pip', 'standalone'; interpreter is the shebang python for 'pip'."""
    real = os.path.realpath(path)
    # Check both spellings: the path as given and where it resolves to.
    # Symlinks can point out of a recognizable location, and macOS
    # firmlinks rewrite prefixes (/home/... -> /System/Volumes/Data/home/...).
    spellings = (path, real)
    if any("/Cellar/" in p or "/.linuxbrew/" in p or p.startswith("/opt/homebrew/") for p in spellings):
        return "homebrew", None
    # Distro packages land in /usr/bin as a python script too, but their
    # system python blocks `pip install` (PEP 668) — treat as package-managed.
    if any(p.startswith(("/usr/bin/", "/usr/lib/", "/usr/lib64/")) for p in spellings):
        return "package", None
    try:
        with open(real, "rb") as f:
            head = f.readline(256)
    except OSError:
        return "standalone", None
    if not head.startswith(b"#!"):
        return "standalone", None
    tokens = head[2:].decode("utf-8", "replace").split()
    interpreter = None
    if tokens:
        interpreter = tokens[0]
        if interpreter.endswith("/env") and len(tokens) > 1:
            interpreter = shutil.which(tokens[1])
    return "pip", interpreter


def update_command(method, path, interpreter=None, channel="stable"):
    """argv that updates this install, or None if it has to be done by hand.
    Only the standalone binary can switch channels — a Homebrew or pip
    install follows whatever its packager ships."""
    if method == "standalone":
        return [path, "-U"] if channel == "stable" else [path, "--update-to", f"{channel}@latest"]
    if method == "homebrew":
        brew = shutil.which("brew") or _first_executable([
            "/opt/homebrew/bin/brew",
            "/usr/local/bin/brew",
            "/home/linuxbrew/.linuxbrew/bin/brew",
        ])
        return [brew, "upgrade", "yt-dlp"] if brew else None
    if method == "pip" and interpreter:
        return [interpreter, "-m", "pip", "install", "--upgrade", "yt-dlp"]
    return None


MANUAL_UPDATE_HINTS = {
    "standalone": "yt-dlp -U",
    "homebrew": "brew upgrade yt-dlp",
    "pip": "pip install --upgrade yt-dlp",
    "package": "use your distro's package manager, e.g. sudo apt install --only-upgrade yt-dlp",
}


RATE_RE = re.compile(r"^\s*(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>[kKmMgGtT])?(?:i?[bB])?\s*$")
RATE_UNITS = {"k": 1024, "m": 1024 ** 2, "g": 1024 ** 3, "t": 1024 ** 4}


def parse_rate_limit(text):
    """'50K' / '4.2M' / '1048576' -> bytes per second, as yt-dlp reads
    --limit-rate. None if it isn't something yt-dlp would accept either."""
    m = RATE_RE.match(text or "")
    if not m:
        return None
    mult = RATE_UNITS[m.group("unit").lower()] if m.group("unit") else 1
    return int(float(m.group("num")) * mult)


def per_process_rate_limit(text, parallel):
    """The --limit-rate to give each of `parallel` concurrent yt-dlp
    processes so the *total* stays at the user's limit. Unparseable input
    is passed through untouched (yt-dlp will complain about it itself)."""
    total = parse_rate_limit(text)
    if total is None or parallel <= 1:
        return text
    return str(max(1, total // parallel))


def parallel_from_settings(settings):
    try:
        return max(1, int((settings.get("network") or {}).get("parallel") or 1))
    except (TypeError, ValueError):
        return 1


def notifications_enabled(settings):
    # Default on — settings files from before this option exist have no key.
    return bool((settings.get("notifications") or {}).get("enabled", True))


def sanitize_settings_payload(payload):
    """Never let the password field reach disk in plaintext, whether that's
    the regular auto-save location or an explicit export elsewhere."""
    settings = payload.get("settings", {})
    auth = settings.get("auth")
    if isinstance(auth, dict):
        auth = dict(auth)
        auth["password"] = ""
        settings = dict(settings, auth=auth)
        payload = dict(payload, settings=settings)
    return payload


SECRET_FLAGS = {"-p", "--password", "--video-password", "--ap-password", "--twofactor", "-2"}
PROXY_FLAGS = {"--proxy", "--geo-verification-proxy"}


def redact_args(args):
    """The argv as it's safe to show in the Log: password values masked,
    userinfo stripped from proxy URLs. The real argv still carries them —
    only the echo is scrubbed (settings.json never had them: see
    sanitize_settings_payload)."""
    out = []
    hide_next = False
    strip_userinfo_next = False
    for a in args:
        if hide_next:
            out.append("••••••")
            hide_next = False
        elif strip_userinfo_next:
            out.append(re.sub(r"^([a-z0-9+.-]+://)[^@/]*@", r"\1••••••@", a, flags=re.I))
            strip_userinfo_next = False
        else:
            out.append(a)
            hide_next = a in SECRET_FLAGS
            strip_userinfo_next = a in PROXY_FLAGS
    return out


# --- sections (clips and chapters) -------------------------------------------------
# A job may download part of a video: {"start", "end", "title"} (end None =
# to the end; title set when it came from a chapter) or {"splitChapters":
# True}. yt-dlp's --download-sections takes "*START-END"; every section
# then goes through the same output template, so two sections of one
# video would overwrite each other unless the name carries the section.

def format_seconds(sec):
    """1m30s / 1h02m03s / 45s — filename-safe, no colons."""
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def _num(sec):
    return str(int(sec)) if float(sec).is_integer() else f"{sec:.3f}".rstrip("0")


def section_label(section):
    if section.get("title"):
        return section["title"]
    end = section.get("end")
    return f"{format_seconds(section.get('start') or 0)}-{format_seconds(end) if end is not None else 'end'}"


FILENAME_UNSAFE_RE = re.compile(r"[\\/\x00-\x1f]+")


def template_with_suffix(template, suffix):
    """Insert ` - suffix` before the extension of an output template, so a
    section's file doesn't collide with the whole video's. The suffix is
    literal text inside a template: %% escapes it, path separators go."""
    safe = FILENAME_UNSAFE_RE.sub(" ", suffix).replace("%", "%%").strip()
    safe = " ".join(safe.split())[:80]
    tail = ".%(ext)s"
    if template.endswith(tail):
        return f"{template[:-len(tail)]} - {safe}{tail}"
    return f"{template} - {safe}"


# yt-dlp's default name for split chapter files, spelled out so the
# destination applies to them too.
CHAPTER_TEMPLATE = "%(title)s - %(section_number)03d %(section_title)s [%(id)s].%(ext)s"


def section_args(section, dest):
    if section.get("splitChapters"):
        # Relative, like the main template: the "chapter" path type falls
        # back to home, which -P has already pointed at the destination.
        return ["--split-chapters", "-o", "chapter:" + CHAPTER_TEMPLATE]
    start = section.get("start") or 0
    end = section.get("end")
    return ["--download-sections", f"*{_num(start)}-{_num(end) if end is not None else 'inf'}"]


def split_lines(text):
    """One value per line, blanks dropped — for options yt-dlp accepts
    repeatedly (--add-headers, --extractor-args)."""
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def cookies_from_browser(auth):
    """BROWSER[+KEYRING][:PROFILE][::CONTAINER] — the select gives the
    browser, the two optional fields the rest. Multi-profile Chrome users
    get the wrong account without this."""
    spec = auth["cookiesFromBrowser"]
    profile = (auth.get("cookiesProfile") or "").strip()
    container = (auth.get("cookiesContainer") or "").strip()
    if profile:
        spec += ":" + profile
    if container:
        spec += "::" + container
    return spec


def build_args(binary, settings, dest, section=None, slots=None):
    """Translate the settings dict from the UI into a yt-dlp argv list.
    `section` restricts the download to part of the video (see above);
    `slots` is how many jobs will actually share the rate limit (the queue
    knows; defaults to the parallel setting)."""
    preset = settings.get("preset", "best")
    fmt = settings.get("format", {})
    filename = settings.get("filename", {})
    playlist = settings.get("playlist", {})
    live = settings.get("live", {})
    subs = settings.get("subtitles", {})
    thumb = settings.get("thumbnail", {})
    audio = settings.get("audio", {})
    net = settings.get("network", {})
    auth = settings.get("auth", {})
    sb = settings.get("sponsorblock", {})
    geo = settings.get("geo", {})
    postrun = settings.get("postrun", {})
    debug = settings.get("debug", {})
    extra = settings.get("extraArgs", "")

    args = [binary, "--newline"]

    # yt-dlp does its own PATH search for ffmpeg at postprocessing time —
    # it doesn't share find_ffmpeg()'s result just because we found it.
    # Under the browser extension, the inherited PATH is minimal enough
    # that yt-dlp's own search fails even when ours succeeds (e.g. ffmpeg
    # installed via Homebrew at /opt/homebrew/bin, which isn't on that
    # minimal PATH), so tell it explicitly where ffmpeg lives.
    ffmpeg_path = find_ffmpeg()
    if ffmpeg_path:
        args += ["--ffmpeg-location", ffmpeg_path]

    # Same story for the JavaScript runtime YouTube extraction needs: yt-dlp
    # only enables deno by default and only looks for it on PATH, so an
    # nvm-installed node (or a Homebrew deno under that minimal PATH) is
    # invisible to it. Name the runtime and say where it is.
    js_runtime = find_js_runtime()
    if js_runtime:
        name, path = js_runtime
        args += ["--js-runtimes", f"{name}:{path}"]

    # --- filename / output template ---
    # The destination is a base path (-P), not part of the template. Joining
    # it into -o instead would make the template absolute, and yt-dlp then
    # applies --trim-filenames to the whole path — observed truncating
    # "/long/dest/dir/Title.mp4" to 40 characters of *directory*, writing
    # the file outside the chosen folder. It also makes -P inert, which is
    # what a temp-download directory would need.
    template = (filename.get("template") or "%(title)s.%(ext)s").strip()
    if section and not section.get("splitChapters"):
        template = template_with_suffix(template, section_label(section))
    args += ["-P", "home:" + dest, "-o", template]
    if section:
        args += section_args(section, dest)
        if fmt.get("forceKeyframesAtCuts"):
            args.append("--force-keyframes-at-cuts")
    if filename.get("restrict"):
        args.append("--restrict-filenames")
    if filename.get("noOverwrites"):
        args.append("--no-overwrites")
    if filename.get("windowsFilenames"):
        args.append("--windows-filenames")
    if filename.get("trim"):
        args += ["--trim-filenames", str(filename["trim"]).strip()]

    # --- format / quality ---
    extract_audio = bool(audio.get("extractAudio")) or preset == "audio"
    custom_format = fmt.get("customFormat") if preset == "custom" else None

    if extract_audio:
        args += ["-f", custom_format or "bestaudio/best"]
        args.append("-x")
        args += ["--audio-format", audio.get("audioFormat") or "mp3"]
        if audio.get("audioQuality"):
            args += ["--audio-quality", str(audio["audioQuality"])]
    elif not ffmpeg_path and not custom_format:
        # Without ffmpeg there is nothing to merge separate video+audio
        # streams with — yt-dlp would download two files and leave them.
        # Ask for the best single pre-merged stream instead (720p at most
        # on YouTube) rather than silently producing a silent video.
        args += ["-f", NO_FFMPEG_FORMATS.get(preset, NO_FFMPEG_FORMATS["best"])]
    else:
        args += ["-f", custom_format or QUALITY_FORMATS.get(preset, QUALITY_FORMATS["best"])]
        if preset == "compat" and not custom_format:
            args += ["-S", COMPAT_SORT]
        merge_fmt = fmt.get("mergeOutputFormat") or "mp4"
        if preset == "compat":
            merge_fmt = "mp4"   # the whole point of the preset
        if merge_fmt != "none":
            args += ["--merge-output-format", merge_fmt]

    if fmt.get("preferFreeFormats"):
        args.append("--prefer-free-formats")
    # Remux is a lossless container change; recode re-encodes. Both set
    # would be contradictory — yt-dlp itself refuses the pair — so remux wins.
    if fmt.get("remuxVideo") and fmt["remuxVideo"] != "none":
        args += ["--remux-video", fmt["remuxVideo"]]
    elif fmt.get("recodeVideo") and fmt["recodeVideo"] != "none":
        args += ["--recode-video", fmt["recodeVideo"]]
    if audio.get("keepVideo"):
        args.append("--keep-video")

    # --- playlist ---
    if playlist.get("items"):
        args += ["--playlist-items", playlist["items"]]
    if playlist.get("noPlaylist"):
        args.append("--no-playlist")
    if playlist.get("maxDownloads"):
        args += ["--max-downloads", str(playlist["maxDownloads"])]
    if live.get("fromStart"):
        args.append("--live-from-start")
    if live.get("waitForVideo"):
        args += ["--wait-for-video", str(live["waitForVideo"]).strip()]
    if playlist.get("skipDownloaded"):
        args += ["--download-archive", archive_path()]
        if playlist.get("breakOnExisting"):
            args.append("--break-on-existing")

    # --- subtitles ---
    if subs.get("write"):
        args.append("--write-subs")
    if subs.get("writeAuto"):
        args.append("--write-auto-subs")
    if subs.get("langs"):
        args += ["--sub-langs", subs["langs"]]
    if subs.get("embed"):
        args.append("--embed-subs")
    if subs.get("format"):
        args += ["--sub-format", str(subs["format"]).strip()]
    if subs.get("convert") and subs["convert"] != "none":
        args += ["--convert-subs", subs["convert"]]

    # --- thumbnail / metadata ---
    if thumb.get("write"):
        args.append("--write-thumbnail")
    if thumb.get("embed"):
        args.append("--embed-thumbnail")
    if thumb.get("addMetadata"):
        args.append("--add-metadata")
    if thumb.get("embedChapters"):
        args.append("--embed-chapters")
    if thumb.get("convert") and thumb["convert"] != "none":
        args += ["--convert-thumbnails", thumb["convert"]]
    if thumb.get("writeDescription"):
        args.append("--write-description")
    if thumb.get("writeInfoJson"):
        args.append("--write-info-json")
    if thumb.get("writeComments"):
        args.append("--write-comments")
    if thumb.get("embedInfoJson"):
        args.append("--embed-info-json")

    # --- network ---
    if net.get("proxy"):
        args += ["--proxy", net["proxy"]]
    if net.get("rateLimit"):
        # The setting is the total; split it across the jobs sharing it.
        parallel = slots or parallel_from_settings(settings)
        args += ["--limit-rate", per_process_rate_limit(net["rateLimit"], parallel)]
    if net.get("throttledRate"):
        args += ["--throttled-rate", str(net["throttledRate"]).strip()]
    if net.get("concurrentFragments"):
        args += ["-N", str(net["concurrentFragments"]).strip()]
    if net.get("retries"):
        args += ["--retries", str(net["retries"])]
    if net.get("fragmentRetries"):
        args += ["--fragment-retries", str(net["fragmentRetries"]).strip()]
    if net.get("sleepInterval"):
        args += ["--sleep-interval", str(net["sleepInterval"]).strip()]
        if net.get("maxSleepInterval"):
            args += ["--max-sleep-interval", str(net["maxSleepInterval"]).strip()]
    if net.get("sleepRequests"):
        args += ["--sleep-requests", str(net["sleepRequests"]).strip()]
    if net.get("socketTimeout"):
        args += ["--socket-timeout", str(net["socketTimeout"])]
    if net.get("userAgent"):
        args += ["--user-agent", net["userAgent"].strip()]
    if net.get("referer"):
        args += ["--referer", net["referer"].strip()]
    for header in split_lines(net.get("headers")):
        args += ["--add-headers", header]
    if net.get("impersonate"):
        args += ["--impersonate", net["impersonate"].strip()]
    if net.get("forceIpv4"):
        args.append("-4")
    if net.get("forceIpv6"):
        args.append("-6")

    # --- auth / cookies ---
    if auth.get("username"):
        args += ["-u", auth["username"]]
    if auth.get("password"):
        args += ["-p", auth["password"]]
    if auth.get("cookiesFile"):
        args += ["--cookies", auth["cookiesFile"]]
    if auth.get("cookiesFromBrowser") and auth["cookiesFromBrowser"] != "none":
        args += ["--cookies-from-browser", cookies_from_browser(auth)]
    if auth.get("videoPassword"):
        args += ["--video-password", auth["videoPassword"]]
    if auth.get("twofactor"):
        args += ["--twofactor", str(auth["twofactor"]).strip()]
    if auth.get("netrc"):
        args.append("--netrc")

    # --- sponsorblock ---
    # No fallback to "all" here — the settings default already is "all",
    # so an empty value only happens when the user deliberately cleared
    # every category, which should mean "don't mark/remove anything",
    # not silently act on every category anyway.
    categories = sb.get("categories") or ""
    if isinstance(categories, (list, tuple)):
        categories = ",".join(c for c in categories if c)
    # Settings saved by the old free-text field may have spaces ("intro, outro").
    categories = ",".join(c.strip() for c in categories.split(",") if c.strip())
    if sb.get("mark") and categories:
        args += ["--sponsorblock-mark", categories]
    if sb.get("remove"):
        # yt-dlp rejects poi_highlight/chapter for --sponsorblock-remove
        # (they're mark-only), and one shared category list feeds both
        # flags — so drop them here rather than fail the whole download.
        removable = ",".join(
            c for c in categories.split(",") if c and c not in SPONSORBLOCK_MARK_ONLY
        )
        if removable:
            args += ["--sponsorblock-remove", removable]

    # --- geo-restriction ---
    # --geo-bypass / --geo-bypass-country are deprecated aliases (gone from
    # --help); --xff is the option now. yt-dlp's own default ("default":
    # fake the header only where known to help) needs no flag, so only the
    # two real choices are sent: a specific country/CIDR, or never.
    if geo.get("disable"):
        args += ["--xff", "never"]
    elif (geo.get("bypassCountry") or "").strip():
        args += ["--xff", geo["bypassCountry"].strip()]

    # --- post-run command ---
    if postrun.get("exec"):
        args += ["--exec", postrun["exec"]]

    # --- yt-dlp's own config files ---
    # Off by default: a config file silently merging with, or doubling,
    # what the panels say makes the GUI lie about what it runs.
    if not debug.get("useConfigFile"):
        args.append("--ignore-config")

    # --- debug / verbosity ---
    if debug.get("verbose"):
        args.append("--verbose")
    if debug.get("simulate"):
        args.append("--simulate")
    if debug.get("ignoreErrors"):
        args.append("--ignore-errors")

    # --- extractor arguments (one "IE_KEY:ARGS" per line) ---
    for spec in split_lines(settings.get("extractorArgs")):
        args += ["--extractor-args", spec]

    # --- raw extra arguments (escape hatch for anything not exposed above) ---
    if extra and extra.strip():
        args += shlex.split(extra)

    return args


DESTINATION_RE = re.compile(r"^\[(?:download|ExtractAudio|Merger)\]\s+(?:Destination:|Merging formats into)\s+\"?(?P<path>.+?)\"?$")
# yt-dlp names intermediate per-format streams "Title.f137.mp4" before merging.
FORMAT_SUFFIX_RE = re.compile(r"\.f\d+$")
# With --write-subs the first Destination line is the subtitle file
# ("Title.en.vtt"), which would leave a stray ".en" on the title — skip those
# and take the title from the media file that follows.
SUBTITLE_EXTS = {".vtt", ".srt", ".ass", ".ssa", ".lrc", ".ttml", ".tt", ".dfxp", ".sbv", ".json3", ".srv1", ".srv2", ".srv3"}

TERMINAL_STATUSES = ("done", "failed", "cancelled")


def title_from_log_line(line):
    """The display title, lifted from yt-dlp's own '[download] Destination:'
    line — no extra network call. None if the line isn't one (or is a
    subtitle download)."""
    m = DESTINATION_RE.match(line)
    if not m:
        return None
    name, ext = os.path.splitext(os.path.basename(m.group("path")))
    if ext.lower() in SUBTITLE_EXTS:
        return None
    return FORMAT_SUFFIX_RE.sub("", name)


class DownloadQueue:
    """Sequential download queue. Knows nothing about pywebview: `emit`
    reports events to the UI and `runner` actually performs one job, so
    both are injectable in tests. One worker thread at a time; a failed
    or cancelled job never stops the ones behind it."""

    def __init__(self, emit, runner, max_concurrent=1):
        self._emit = emit
        self._runner = runner
        self._jobs = []
        self._lock = threading.Lock()
        self._max_concurrent = max(1, int(max_concurrent))
        self._next_id = 1
        self._paused = False
        self._inflight = 0     # _run_one calls in progress, incl. their post-status hooks
        self.persist = None   # persist(pending_items) after every change, if set

    # --- public API -------------------------------------------------------

    def enqueue(self, urls, settings, dest):
        """`urls` items are plain strings, or {"url", "title"} dicts when the
        caller already knows the title (playlist picker) so the row doesn't
        have to show the URL until yt-dlp prints a Destination line."""
        ids = []
        with self._lock:
            for item in urls:
                title = section = None
                job_settings = settings
                if isinstance(item, dict):
                    title = (item.get("title") or "").strip() or None
                    section = item.get("section") if isinstance(item.get("section"), dict) else None
                    # An item may bring its own settings — the playlist picker
                    # uses this to queue one job with its own --playlist-items.
                    if isinstance(item.get("settings"), dict):
                        job_settings = item["settings"]
                    item = item.get("url")
                url = (item or "").strip()
                if not url:
                    continue
                job = {
                    "id": self._next_id,
                    "url": url,
                    "dest": dest,
                    "settings": json.loads(json.dumps(job_settings)),  # snapshot
                    "status": "queued",
                    "title": title,
                    "pct": 0,
                    "code": None,
                    "files": [],       # final output paths, from --print after_move
                    "archive": [],     # "<extractor> <id>" per finished video, same source
                    "tail": [],        # last TAIL_LINES of output, for error_hint on failure
                    "hint": None,
                    "section": section,
                    "proc": None,
                    "cancel": False,
                    "reported": False,
                }
                self._next_id += 1
                self._jobs.append(job)
                ids.append(job["id"])
        if ids:
            self._emit_queue()
            self._dispatch()
        return ids

    def set_max_concurrent(self, n):
        """How many jobs may run at once. Raising it mid-queue starts more
        immediately; lowering it just stops new ones starting until the
        running count drops — nothing in flight is interrupted."""
        with self._lock:
            self._max_concurrent = max(1, int(n or 1))
        self._dispatch()

    def cancel(self, job_id):
        with self._lock:
            job = self._find(job_id)
            if not job:
                return False
            self._cancel_locked(job)
        self._emit_queue()
        return True

    def cancel_all(self):
        with self._lock:
            for job in self._jobs:
                if job["status"] in ("queued", "running"):
                    self._cancel_locked(job)
        self._emit_queue()
        return True

    def clear_finished(self):
        with self._lock:
            self._jobs = [j for j in self._jobs if j["status"] not in TERMINAL_STATUSES]
        self._emit_queue()
        return True

    def remove(self, job_id):
        """Drop one finished row. Active jobs must be cancelled first."""
        with self._lock:
            job = self._find(job_id)
            if not job or job["status"] not in TERMINAL_STATUSES:
                return False
            self._jobs.remove(job)
        self._emit_queue()
        return True

    def snapshot(self):
        with self._lock:
            return [self._public(j) for j in self._jobs]

    def state(self):
        """What the UI renders from: the jobs plus whether dispatch is paused."""
        with self._lock:
            return {"jobs": [self._public(j) for j in self._jobs], "paused": self._paused}

    def set_paused(self, paused):
        """Paused: nothing new starts; whatever is running finishes.
        Resuming dispatches immediately."""
        with self._lock:
            self._paused = bool(paused)
        self._emit_queue()
        if not paused:
            self._dispatch()

    def pending(self):
        """What a restart should pick up again: everything not yet finished,
        as enqueue() items with their own settings and folder. A running
        job counts too — yt-dlp resumes its .part file."""
        with self._lock:
            return [{"url": j["url"], "title": j["title"], "section": j.get("section"),
                     "settings": j["settings"], "dest": j["dest"]}
                    for j in self._jobs if j["status"] in ("queued", "running")]

    def is_active(self):
        with self._lock:
            return any(j["status"] in ("queued", "running") for j in self._jobs)

    def wait_idle(self, timeout=5.0):
        """True once nothing is queued or running *and* every worker has
        finished its post-status work (the done event, notification and
        history write happen after the status flips). Tests rely on this;
        the app itself only needs is_active()."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self._inflight == 0 and not any(j["status"] in ("queued", "running") for j in self._jobs):
                    return True
            time.sleep(0.01)
        return False

    def get(self, job_id):
        """A copy of one job's full record (settings, files, ...) — what the
        history needs once it's finished. None if it's been removed."""
        with self._lock:
            job = self._find(job_id)
            if job is None:
                return None
            return {k: v for k, v in job.items() if k != "proc"}

    def unreported_finished(self):
        """Terminal jobs nobody has reported on yet (marks them reported).
        Lets the notifier summarize a whole batch once when the queue drains
        instead of once per job."""
        with self._lock:
            out = [j for j in self._jobs if j["status"] in TERMINAL_STATUSES and not j["reported"]]
            for j in out:
                j["reported"] = True
            return out

    # --- internals ----------------------------------------------------------

    def _find(self, job_id):
        return next((j for j in self._jobs if j["id"] == job_id), None)

    def _public(self, job):
        return {k: job[k] for k in ("id", "url", "status", "title", "pct", "code", "hint", "section", "files")}

    def retry(self, job_id):
        """A fresh job with the same url/title/settings/dest as a finished
        one (failed or cancelled). The old row stays; returns the new id,
        or None if the job is unknown or still active."""
        with self._lock:
            job = self._find(job_id)
            if not job or job["status"] not in TERMINAL_STATUSES:
                return None
            item = {"url": job["url"], "title": job["title"], "section": job.get("section")}
            settings, dest = job["settings"], job["dest"]
        ids = self.enqueue([item], settings, dest)
        return ids[0] if ids else None

    def _emit_queue(self):
        self._emit("ytdlp-queue", self.state())
        if self.persist:
            try:
                self.persist(self.pending())
            except Exception:
                pass   # a full disk must not stall the worker thread

    def _cancel_locked(self, job):
        job["cancel"] = True
        if job["status"] == "queued":
            job["status"] = "cancelled"
        elif job["status"] == "running" and job["proc"] and job["proc"].poll() is None:
            terminate_job(job["proc"])

    def _dispatch(self):
        """Start queued jobs until max_concurrent are running. Called after
        anything that could free a slot or add work."""
        to_start = []
        with self._lock:
            if self._paused:
                return
            running = sum(1 for j in self._jobs if j["status"] == "running")
            active = running + sum(1 for j in self._jobs if j["status"] == "queued")
            for job in self._jobs:
                if running >= self._max_concurrent:
                    break
                if job["status"] == "queued":
                    job["status"] = "running"
                    # How many jobs the rate limit is really shared with: a
                    # lone job with four slots configured gets the whole limit.
                    job["slots"] = max(1, min(self._max_concurrent, active))
                    running += 1
                    to_start.append(job)
        for job in to_start:
            self._emit_queue()
            threading.Thread(target=self._run_one, args=(job,), daemon=True).start()

    def _run_one(self, job):
        with self._lock:
            self._inflight += 1
        try:
            self._run_one_inner(job)
        finally:
            with self._lock:
                self._inflight -= 1

    def _run_one_inner(self, job):
        try:
            code = self._runner(job, self._emit)
        except Exception as e:
            self._emit("ytdlp-log", {"jobId": job["id"], "line": f"Error: {e}"})
            code = -1
        with self._lock:
            job["code"] = code
            job["proc"] = None
            if job["cancel"]:
                job["status"] = "cancelled"
            elif code == 0:
                job["status"] = "done"
                job["pct"] = 100
                if skipped_by_archive(job):
                    job["hint"] = {"text": "Already in History — skipped", "action": None}
            else:
                job["status"] = "failed"
                job["hint"] = error_hint(job.get("tail"))
            status = job["status"]
        self._emit("ytdlp-done", {
            "jobId": job["id"],
            "success": status == "done",
            "cancelled": status == "cancelled",
            "code": code,
        })
        self._emit_queue()
        self._dispatch()


# Flags that make a -J metadata fetch useless or have side effects, with
# whether they swallow the following argument. Typed into Extra Arguments
# they'd otherwise break the preview ("Couldn't fetch info") — or, for
# --exec, run a command just because the user paused while typing a URL.
PREVIEW_UNSAFE_FLAGS = {
    "-F": False, "--list-formats": False, "--list-subs": False, "--list-subtitles": False,
    "--list-thumbnails": False, "--list-impersonate-targets": False, "--list-extractors": False,
    "-j": False, "-J": False, "--dump-json": False, "--dump-single-json": False,
    "--skip-download": False, "--no-simulate": False, "--flat-playlist": False,
    "--no-flat-playlist": False, "--split-chapters": False,
    "--print": True, "-O": True, "--print-to-file": True, "--exec": True,
    "--downloader": True, "--download-sections": True, "--parse-metadata": True,
}


def strip_preview_unsafe(tokens):
    """Drop the flags above (and their values) from a token list."""
    out, skip = [], False
    for token in tokens:
        if skip:
            skip = False
            continue
        flag = token.split("=", 1)[0]
        if flag in PREVIEW_UNSAFE_FLAGS:
            skip = PREVIEW_UNSAFE_FLAGS[flag] and "=" not in token
            continue
        out.append(token)
    return out


def preview_settings(settings):
    """The settings as they should apply to a metadata fetch: cookies,
    proxy, geo and playlist ranges yes; anything that would change what -J
    prints, run a command, or skip the lookup entirely, no."""
    out = dict(settings)
    out["postrun"] = {}                      # --exec must not fire while typing
    out["playlist"] = dict(out.get("playlist") or {}, skipDownloaded=False, breakOnExisting=False)
    out["extraArgs"] = " ".join(shlex.quote(t) for t in strip_preview_unsafe(shlex.split(settings.get("extraArgs") or "")))
    return out


def info_args(binary, settings, dest, url):
    """argv for a metadata-only fetch. Reuses build_args so cookies, proxy,
    geo-bypass, playlist ranges etc. apply exactly as they would to the real
    download; -J implies simulate, so the output/postprocessing flags are
    inert. --flat-playlist keeps a playlist URL to one request."""
    # -J of an archived video would print nothing but "already recorded",
    # and a stray -F or --exec in Extra Arguments would break the fetch or
    # run a command; preview_settings() takes both out.
    return build_args(binary, preview_settings(settings), dest) + [
        "-J", "--flat-playlist", "--no-warnings", url]


def human_size(n):
    if not n:
        return ""
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def _codec_family(codec):
    if not codec or codec == "none":
        return ""
    return codec.split(".")[0]


def summarize_formats(formats):
    """The parts of yt-dlp's format list worth showing, best first. Storyboard
    and other non-media entries are dropped."""
    out = []
    for f in formats or []:
        vcodec, acodec = f.get("vcodec") or "none", f.get("acodec") or "none"
        if f.get("ext") == "mhtml" or "storyboard" in (f.get("format_note") or "").lower():
            continue
        if vcodec == "none" and acodec == "none":
            continue
        has_video, has_audio = vcodec != "none", acodec != "none"
        out.append({
            "id": f.get("format_id"),
            "ext": f.get("ext") or "",
            "resolution": (f.get("resolution") or "") if has_video else "audio only",
            "height": f.get("height") or 0,
            "fps": f.get("fps"),
            "vcodec": _codec_family(vcodec),
            "acodec": _codec_family(acodec),
            "size": human_size(f.get("filesize") or f.get("filesize_approx")),
            "tbr": round(f["tbr"]) if f.get("tbr") else None,
            "note": f.get("format_note") or "",
            "kind": "video+audio" if has_video and has_audio else ("video" if has_video else "audio"),
        })
    # video first (tallest, then highest bitrate), audio-only after
    out.sort(key=lambda x: (x["kind"] == "audio", -x["height"], -(x["tbr"] or 0)))
    return out


def format_selector(fmt):
    """What to put in the custom -f field when a row is clicked: a video-only
    stream needs audio merged in, anything with audio can stand alone."""
    return f"{fmt['id']}+bestaudio/best" if fmt["kind"] == "video" else str(fmt["id"])


def archive_line(data):
    """The --download-archive line yt-dlp would use for this info dict, or
    None. Flat playlist entries carry ie_key rather than extractor_key."""
    ext = data.get("extractor_key") or data.get("ie_key")
    vid = data.get("id")
    if not ext or not vid:
        return None
    return f"{str(ext).lower()} {vid}"


def summarize_entries(entries, downloaded=frozenset()):
    """Playlist entries as the picker shows them, in playlist order. Each
    becomes its own queue job when selected, so it needs a URL of its own;
    entries without one (rare, extractor-specific) are skipped.
    `downloaded` is the archive set: matching entries are flagged so the
    picker can start them unticked."""
    out = []
    for position, e in enumerate(entries or [], start=1):
        if not e:
            continue
        url = e.get("url") or e.get("webpage_url")
        if not url:
            continue
        out.append({
            # Its place in the playlist as yt-dlp counts it, which is what
            # --playlist-items needs — not its row number, since entries
            # without a URL are dropped above.
            "index": e.get("playlist_index") or position,
            "url": url,
            "title": e.get("title") or url,
            "duration": int(e["duration"]) if e.get("duration") else None,
            "uploader": e.get("uploader") or e.get("channel") or "",
            "downloaded": archive_line(e) in downloaded,
        })
    return out


def summarize_info(data, downloaded=frozenset()):
    """Trim yt-dlp -J output to what the preview card needs. `downloaded`
    is the set of archive lines already in history."""
    if data.get("_type") == "playlist":
        entries = data.get("entries") or []
        return {
            "kind": "playlist",
            "title": data.get("title") or "",
            "uploader": data.get("uploader") or data.get("channel") or "",
            "count": data.get("playlist_count") or len(entries),
            "thumbnail": data.get("thumbnail") or next((e.get("thumbnail") for e in entries if e and e.get("thumbnail")), None),
            "url": data.get("webpage_url") or data.get("original_url") or "",
            "formats": [],
            "entries": summarize_entries(entries, downloaded),
        }
    return {
        "kind": "video",
        "title": data.get("title") or "",
        "uploader": data.get("uploader") or data.get("channel") or "",
        "duration": int(data["duration"]) if data.get("duration") else None,
        "thumbnail": data.get("thumbnail"),
        "url": data.get("webpage_url") or data.get("original_url") or "",
        "formats": summarize_formats(data.get("formats")),
        "chapters": summarize_chapters(data.get("chapters")),
        "subtitles": summarize_subtitles(data),
        "live": live_state(data),
        "fields": template_fields(data),
        "downloaded": archive_line(data) in downloaded,
    }


# The output-template fields worth showing an example for. yt-dlp has many
# more, but these are the ones a filename is usually built from.
TEMPLATE_FIELDS = (
    "id", "ext", "title", "fulltitle", "uploader", "channel", "uploader_id",
    "upload_date", "release_date", "duration_string", "resolution", "height",
    "width", "fps", "vcodec", "acodec", "format_id", "format_note", "view_count",
    "like_count", "extractor_key", "playlist", "playlist_title", "playlist_id",
    "playlist_index", "playlist_count", "webpage_url_domain", "license", "epoch",
)


def template_fields(data):
    """Scalar values for the filename example, so it shows what this very
    video would be called rather than a made-up sample."""
    out = {}
    for key in TEMPLATE_FIELDS:
        value = data.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            out[key] = value
    out.setdefault("ext", data.get("ext") or "mp4")
    return out


LIVE_LABELS = {"is_live": "live", "is_upcoming": "upcoming", "post_live": "just ended", "was_live": "was live"}


def live_state(data):
    """{"state", "label", "startsAt"} for a stream, or None for an
    ordinary video. `startsAt` is the scheduled unix time of an upcoming
    one, which the UI turns into a local time."""
    status = data.get("live_status")
    if not status and data.get("is_live"):
        status = "is_live"
    if status not in LIVE_LABELS:
        return None
    starts = data.get("release_timestamp")
    return {"state": status, "label": LIVE_LABELS[status],
            "startsAt": int(starts) if isinstance(starts, (int, float)) else None}


def summarize_subtitles(data):
    """The languages this video actually has, for the picker: manual
    tracks first (with yt-dlp's own display name where it gives one),
    then automatic captions, which are usually a long machine-translated
    list — flagged so the UI can fold them away."""
    out = []
    for key, auto in (("subtitles", False), ("automatic_captions", True)):
        for code, tracks in (data.get(key) or {}).items():
            if not code or any(e["code"] == code for e in out):
                continue
            name = next((t.get("name") for t in (tracks or []) if isinstance(t, dict) and t.get("name")), "")
            out.append({"code": code, "name": name or code, "auto": auto})
    return out


def summarize_chapters(chapters):
    out = []
    for c in chapters or []:
        if not isinstance(c, dict) or c.get("start_time") is None or c.get("end_time") is None:
            continue
        out.append({"title": c.get("title") or f"Chapter {len(out) + 1}",
                    "start": c["start_time"], "end": c["end_time"]})
    return out


def notify_command(title, message):
    """argv for a native desktop notification on this OS, or None if there's
    no way to show one (Linux without notify-send, anything else)."""
    if sys.platform == "darwin":
        # osascript strings: backslash and double-quote are the only escapes
        # that matter inside a double-quoted AppleScript literal.
        esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
        return ["osascript", "-e", f'display notification "{esc(message)}" with title "{esc(title)}"']
    if sys.platform.startswith("linux"):
        tool = shutil.which("notify-send")
        return [tool, title, message] if tool else None
    return None


def send_notification(title, message):
    cmd = notify_command(title, message)
    if not cmd:
        return False
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def summarize_finished(jobs):
    """One line for the queue-drained notification. `jobs` are the terminal
    jobs not yet reported. Cancelled ones are the user's own doing and
    aren't counted; None if there's nothing worth saying."""
    done = [j for j in jobs if j["status"] == "done"]
    failed = [j for j in jobs if j["status"] == "failed"]
    if not done and not failed:
        return None
    if len(done) == 1 and not failed:
        return f"Downloaded: {done[0].get('title') or done[0]['url']}"
    if len(failed) == 1 and not done:
        return f"Download failed: {failed[0].get('title') or failed[0]['url']}"
    parts = []
    if done:
        parts.append(f"{len(done)} download{'s' if len(done) != 1 else ''} finished")
    if failed:
        parts.append(f"{len(failed)} failed")
    return ", ".join(parts)


# yt-dlp tells us where each finished file ended up (after merging, audio
# extraction, and every other postprocessor) via --print after_move — the
# only reliable source, since the "[download] Destination:" lines name the
# intermediate streams. --print implies --quiet, which would also silence
# the progress lines the UI parses, so --no-quiet turns them back on. The
# marker keeps the printed path out of the log stream.
FILE_MARKER = "\x1e__ytdlpgui_file__\x1e"
ARCHIVE_MARKER = "\x1e__ytdlpgui_archive__\x1e"
FILE_PRINT_ARGS = ["--no-quiet", "--print", f"after_move:{FILE_MARKER}%(filepath)s",
                   # what yt-dlp itself would write to --download-archive for this video
                   "--print", f"after_move:{ARCHIVE_MARKER}%(extractor_key)s %(id)s"]


# The handful of yt-dlp failures that account for most of them, each with
# what to do about it. Matched as case-insensitive substrings against the
# job's last lines, first entry wins — so the specific ones come first.
# `action` names a button the UI knows how to render (or None).
ERROR_HINTS = [
    # "sign in to confirm you’re not a bot" — typographic apostrophe in the
    # real message, so match the part before it
    (("sign in to confirm you", "sign in if you", "requires login",
      "login required", "please sign in", "use --cookies"),
     "YouTube wants a signed-in session — use your browser's cookies", "cookies"),
    (("requested format is not available",),
     "That format doesn't exist for this video — pick one from the format list", "formats"),
    (("no such option",),
     "Unrecognised option in Extra Arguments", "extra"),
    (("ffprobe and ffmpeg not found", "ffmpeg not found", "ffmpeg is not installed"),
     "ffmpeg is missing — install it and relaunch (see the sidebar)", None),
    (("private video", "video unavailable", "video is unavailable", "has been removed", "this video is not available",
      "members-only", "join this channel", "not available in your country", "geo restricted",
      "geo-restricted"),
     "The video isn't accessible (private, removed, region- or member-locked)", None),
    (("unsupported url",),
     "yt-dlp doesn't have an extractor for this site", None),
    (("http error 403", "unable to extract", "nsig extraction failed", "signature extraction failed",
      "unable to download webpage", "http error 429"),
     "yt-dlp is probably out of date, or its cache is stale", "update"),
]


ARCHIVE_SKIP_TEXT = "has already been recorded in the archive"


def skipped_by_archive(job):
    """yt-dlp exits 0 without producing anything when --download-archive
    says it's been done; that's not a download, so it shouldn't look like
    one in the queue or land in history."""
    return not job.get("files") and any(ARCHIVE_SKIP_TEXT in l for l in job.get("tail") or [])


def error_hint(lines):
    """{"text", "action"} for the first known failure found in `lines`
    (a job's stderr tail, newest last), or None. Deliberately a small
    table of literal substrings, not a parser."""
    haystack = "\n".join(lines or []).lower()
    if not haystack.strip():
        return None
    for needles, text, action in ERROR_HINTS:
        if any(n in haystack for n in needles):
            return {"text": text, "action": action}
    return None


TAIL_LINES = 30


def terminate_job(proc):
    """SIGTERM the job's whole process group (yt-dlp plus any ffmpeg it is
    running for a merge/recode/extract), falling back to just the process
    when it wasn't started as a session leader."""
    try:
        pgid = os.getpgid(proc.pid)
        if pgid == os.getpgrp():
            raise OSError("not a session leader")   # would take us down too
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.terminate()
        except OSError:
            pass


def run_download_job(job, emit):
    """Runs one queued job with yt-dlp, streaming log/progress events.
    Returns the process exit code (-1 if it couldn't start)."""
    binary = find_ytdlp()
    if not binary:
        emit("ytdlp-log", {"jobId": job["id"], "line": "Error: yt-dlp binary not found."})
        return -1

    os.makedirs(job["dest"], exist_ok=True)
    try:
        args = build_args(binary, job["settings"], job["dest"], job.get("section"), job.get("slots")) + [job["url"]]
    except Exception as e:
        emit("ytdlp-log", {"jobId": job["id"], "line": f"Error: invalid settings: {e}"})
        return -1

    # The log shows the command as the user's settings produced it; the
    # --print plumbing that feeds the history is spliced in only for the run.
    emit("ytdlp-log", {"jobId": job["id"], "line": f"$ {' '.join(shlex.quote(a) for a in redact_args(args))}"})
    try:
        # Own process group, so cancelling reaches the ffmpeg yt-dlp spawns
        # for merging/recoding — not just yt-dlp itself (see terminate_job).
        proc = subprocess.Popen(
            args[:-1] + FILE_PRINT_ARGS + args[-1:],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            start_new_session=True,
        )
    except Exception as e:
        emit("ytdlp-log", {"jobId": job["id"], "line": f"Error: {e}"})
        return -1
    job["proc"] = proc
    if job["cancel"]:  # cancelled in the gap before the process existed
        terminate_job(proc)

    for line in proc.stdout:
        line = line.rstrip("\n")
        if not line:
            continue
        if line.startswith(FILE_MARKER):
            job["files"].append(line[len(FILE_MARKER):])
            continue
        if line.startswith(ARCHIVE_MARKER):
            ext, _, vid = line[len(ARCHIVE_MARKER):].partition(" ")
            if ext and vid and vid != "NA":
                job.setdefault("archive", []).append(f"{ext.lower()} {vid}")
            continue
        tail = job.setdefault("tail", [])
        tail.append(line)
        if len(tail) > TAIL_LINES:
            del tail[:-TAIL_LINES]
        emit("ytdlp-log", {"jobId": job["id"], "line": line})
        title = title_from_log_line(line)
        if title and not job["title"]:
            job["title"] = title
            emit("ytdlp-title", {"jobId": job["id"], "title": title})
        progress = parse_progress(line)
        if progress:
            if progress["pct"] is not None:
                job["pct"] = progress["pct"]
            emit("ytdlp-progress", dict(progress, jobId=job["id"]))
    return proc.wait()


# --- history ---------------------------------------------------------------------

HISTORY_CAP = 500   # newest kept; oldest dropped past this


def quality_label(settings):
    """What the History row shows for 'how it was downloaded'."""
    preset = settings.get("preset", "best")
    if preset == "custom":
        return (settings.get("format") or {}).get("customFormat") or "custom"
    if preset == "audio":
        fmt = (settings.get("audio") or {}).get("audioFormat") or ""
        return f"audio ({fmt})" if fmt and (settings.get("audio") or {}).get("extractAudio") else "audio"
    if preset == "compat":
        return "compatible (h264/aac mp4)"
    return preset


def history_entry(job, now=None):
    """A history record for a finished (done or failed) job. Carries the
    settings snapshot so 'Download again' reproduces it exactly — minus
    the password, same rule as settings.json."""
    settings = sanitize_settings_payload({"settings": job["settings"]})["settings"]
    when = (now or datetime.datetime.now()).astimezone()
    return {
        "id": f"{int(when.timestamp() * 1000)}-{job['id']}",
        "url": job["url"],
        "title": job.get("title"),
        "dest": job["dest"],
        "files": list(job.get("files") or []),
        "section": job.get("section"),
        "archive": list(job.get("archive") or []),
        "status": job["status"],
        "code": job.get("code"),
        "when": when.isoformat(timespec="seconds"),
        "quality": quality_label(settings),
        "settings": settings,
    }


# --- queue persistence --------------------------------------------------------------
# Whatever hasn't finished is written after every queue change, and picked
# up again — paused, so nothing starts unasked — on the next launch.

def queue_path():
    return config_path("queue.json")


def write_queue(items):
    if not items:
        try:
            os.remove(queue_path())
        except FileNotFoundError:
            pass
        return
    with open(queue_path(), "w") as f:
        json.dump({"items": items}, f, indent=2)


def load_queue():
    try:
        with open(queue_path()) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    items = data.get("items") if isinstance(data, dict) else None
    return [i for i in (items or []) if isinstance(i, dict) and isinstance(i.get("url"), str) and i["url"].strip()]


# --- download archive ---------------------------------------------------------------
# yt-dlp skips anything listed in --download-archive FILE, one
# "<extractor> <id>" per line. The history already knows every finished
# video, so the archive is *derived* from it — regenerated before each
# batch and whenever history changes — rather than a second source of
# truth that could drift (yt-dlp appends to the file itself too; those
# same completions land in history through the print marker).

def archive_path():
    return config_path("archive.txt")


def archive_ids(entries):
    """Every archive line of every successful history entry, in order,
    without duplicates."""
    seen, out = set(), []
    for e in entries:
        if e.get("status") != "done":
            continue
        for line in e.get("archive") or []:
            if line and line not in seen:
                seen.add(line)
                out.append(line)
    return out


def write_archive(entries):
    with open(archive_path(), "w") as f:
        f.write("".join(line + "\n" for line in archive_ids(entries)))


def skip_downloaded(settings):
    return bool((settings.get("playlist") or {}).get("skipDownloaded"))


def load_history():
    try:
        with open(history_path()) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    entries = data.get("entries") if isinstance(data, dict) else None
    return [e for e in (entries or []) if isinstance(e, dict)]


def write_history(entries):
    with open(history_path(), "w") as f:
        json.dump({"entries": entries[-HISTORY_CAP:]}, f, indent=2)


def reveal_command(path):
    """argv that shows `path` to the user: the file selected in Finder on
    macOS; on Linux, the containing folder (no portable 'select' verb).
    A file that's since been moved or deleted falls back to its folder."""
    target = path
    if not os.path.exists(target):
        target = os.path.dirname(path)
        if not os.path.isdir(target):
            return None
    if sys.platform == "darwin":
        return ["open", "-R", target] if os.path.isfile(target) else ["open", target]
    opener = shutil.which("xdg-open")
    if not opener:
        return None
    return [opener, target if os.path.isdir(target) else os.path.dirname(target)]


# --- profiles --------------------------------------------------------------------

def sanitize_profiles(data):
    """{"profiles": {name: payload}} with every payload run through the same
    password exclusion as settings.json, and anything malformed dropped."""
    profiles = data.get("profiles") if isinstance(data, dict) else None
    if not isinstance(profiles, dict):
        profiles = {}
    out = {}
    for name, payload in profiles.items():
        name = str(name).strip()
        if not name or not isinstance(payload, dict) or not isinstance(payload.get("settings"), dict):
            continue
        clean = sanitize_settings_payload(payload)
        out[name] = {"settings": clean["settings"], "destFolder": clean.get("destFolder") or ""}
    return {"profiles": out}


class Api:
    def __init__(self):
        self.window = None
        self.queue = DownloadQueue(self._emit, run_download_job)
        self.notifier = send_notification
        self._history_lock = threading.Lock()   # parallel jobs can finish together
        self._info_lock = threading.Lock()
        self._info_proc = None                   # the in-flight preview lookup, if any
        self.queue.persist = self._persist_queue
        self.restored = 0                        # jobs picked up from the last run, for the UI's notice

    def _persist_queue(self, items):
        try:
            write_queue(items)
        except OSError:
            pass

    def restore_queue(self):
        """Re-queue what the last run left unfinished — paused, so the user
        decides when it starts. Each item carries its own settings/folder."""
        items = load_queue()
        if not items:
            return 0
        self.queue.set_paused(True)
        for item in items:
            self.queue.enqueue([item], item.get("settings") or {}, item.get("dest") or os.path.expanduser("~/Downloads"))
        self.restored = len(items)
        return self.restored

    def set_paused(self, paused):
        self.queue.set_paused(paused)
        return True

    def set_title(self, text):
        if self.window:
            try:
                self.window.set_title(text)
            except Exception:
                pass
        return True

    def set_window(self, window):
        self.window = window

    def add_urls(self, urls, options=None):
        """URLs handed over by a later launch (the extension used while the
        app was open). Runs on the instance-server thread; pywebview's
        evaluate_js/show are safe to call from there."""
        if not self.window:
            return
        options = options or {}
        if urls:
            self.window.evaluate_js(
                f"receiveUrls({json.dumps(list(urls))}, {json.dumps(options)})")
        # "Download now" from the popup means the app should get on with it,
        # not jump in front of whatever the user is doing.
        if options.get("enqueue"):
            return
        try:
            self.window.restore()   # un-minimize if needed
            self.window.show()      # and bring to the front (activates the app on macOS)
        except Exception:
            pass

    def choose_folder(self):
        result = self.window.create_file_dialog(webview.FileDialog.FOLDER)
        return result[0] if result else None

    def choose_file(self, file_types=()):
        result = self.window.create_file_dialog(webview.FileDialog.OPEN, file_types=file_types)
        return result[0] if result else None

    def default_folder(self):
        return os.path.expanduser("~/Downloads")

    def load_settings(self):
        try:
            with open(settings_path()) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):   # missing, unreadable, or a config dir we can't create
            return None

    def save_settings(self, payload):
        payload = sanitize_settings_payload(payload)
        return write_config_file(settings_path, payload)

    def export_settings(self, payload):
        result = self.window.create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename="ytdlp-gui-settings.json",
            file_types=("JSON files (*.json)", "All files (*.*)"),
        )
        dest = result[0] if result else None
        if not dest:
            return {"ok": False, "cancelled": True}
        try:
            payload = sanitize_settings_payload(payload)
            with open(dest, "w") as f:
                json.dump(payload, f, indent=2)
            return {"ok": True, "path": dest}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def save_log(self, text):
        result = self.window.create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename="ytdlp-gui-log.txt",
            file_types=("Text files (*.txt)", "All files (*.*)"),
        )
        dest = result[0] if result else None
        if not dest:
            return {"ok": False, "cancelled": True}
        try:
            with open(dest, "w") as f:
                f.write(text)
            return {"ok": True, "path": dest}
        except OSError as e:
            return {"ok": False, "error": str(e)}

    def import_settings(self):
        result = self.window.create_file_dialog(
            webview.FileDialog.OPEN,
            file_types=("JSON files (*.json)", "All files (*.*)"),
        )
        src = result[0] if result else None
        if not src:
            return {"ok": False, "cancelled": True}
        try:
            with open(src) as f:
                data = json.load(f)
            if not isinstance(data, dict) or "settings" not in data:
                return {"ok": False, "error": "Not a yt-dlp GUI settings file."}
            return {"ok": True, "data": data}
        except (OSError, json.JSONDecodeError) as e:
            return {"ok": False, "error": str(e)}

    # --- profiles ---

    def load_profiles(self):
        try:
            with open(profiles_path()) as f:
                return sanitize_profiles(json.load(f))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"profiles": {}}

    def save_profiles(self, data):
        return write_config_file(profiles_path, sanitize_profiles(data))

    # --- history ---

    def history_list(self):
        with self._history_lock:
            return list(reversed(load_history()))   # newest first

    def history_remove(self, entry_id):
        with self._history_lock:
            entries = [e for e in load_history() if e.get("id") != entry_id]
            write_history(entries)
            self._write_archive_quietly(entries)
        return True

    def history_clear(self):
        with self._history_lock:
            write_history([])
            self._write_archive_quietly([])
        return True

    def _write_archive_quietly(self, entries):
        # Removing from history means "forget it" — including for the skip list.
        try:
            write_archive(entries)
        except OSError:
            pass

    def reveal(self, path):
        cmd = reveal_command(path)
        if not cmd:
            return {"ok": False, "error": "File and folder no longer exist"}
        try:
            subprocess.Popen(cmd)
            return {"ok": True}
        except OSError as e:
            return {"ok": False, "error": str(e)}

    def _record_history(self, job_id):
        """True once the job is on disk in history.json."""
        job = self.queue.get(job_id)
        if not job or job["status"] not in ("done", "failed"):
            return False   # cancelled by the user: nothing worth remembering
        if job["status"] == "done" and skipped_by_archive(job):
            return False   # nothing happened; the entry that caused the skip is already there
        try:
            with self._history_lock:
                entries = load_history()
                entries.append(history_entry(job))
                write_history(entries)
            return True
        except Exception:
            return False   # a read-only config dir must not take the queue down (worker thread)

    def ytdlp_config_files(self):
        """The config files yt-dlp would read, that actually exist — so the
        Debug panel can say whether ignoring them changes anything."""
        home = os.path.expanduser("~")
        xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
        candidates = [
            os.path.join(xdg, "yt-dlp", "config"),
            os.path.join(xdg, "yt-dlp", "config.txt"),
            os.path.join(xdg, "yt-dlp.conf"),
            os.path.join(home, "yt-dlp.conf"),
            os.path.join(home, ".yt-dlp", "config"),
            "/etc/yt-dlp.conf",
            "/etc/yt-dlp/config",
        ]
        return [p for p in candidates if os.path.isfile(p)]

    def check_binary(self):
        path = find_ytdlp()
        ffmpeg_path = find_ffmpeg()
        js_runtime = find_js_runtime()
        info = {
            "ffmpeg": bool(ffmpeg_path),
            "jsRuntime": dict(zip(("name", "path"), js_runtime)) if js_runtime else None,
        }
        if not path:
            info["found"] = False
            return info
        try:
            info.update({"found": True, "path": path, "version": ytdlp_version(path)})
        except Exception as e:
            info.update({"found": False, "error": str(e)})
        return info

    def check_for_update(self, current=None, settings=None):
        # `current` is the version check_binary() already reported — pass it
        # back in rather than re-running `yt-dlp --version`, which costs
        # several seconds on the standalone PyInstaller binary (it unpacks
        # itself on every launch).
        path = find_ytdlp()
        if not path:
            return {"ok": False, "reason": "not-found"}
        try:
            channel = update_channel(settings)
            current = current or ytdlp_version(path)
            latest = fetch_latest_version(channel=channel)
        except Exception as e:
            # Offline, rate-limited, GitHub down — none of these should
            # surface as an error in the UI, just skip the check.
            return {"ok": False, "reason": "unavailable", "error": str(e)}
        if not latest:
            return {"ok": False, "reason": "unavailable"}
        method, interpreter = detect_install_method(path)
        return {
            "ok": True,
            "current": current,
            "latest": latest,
            "channel": channel,
            # Only the standalone binary follows a channel of its own; for
            # the others the check is really "is the package out of date".
            "channelApplies": method == "standalone",
            "updateAvailable": is_newer(latest, current),
            "method": method,
            "canAutoUpdate": update_command(method, path, interpreter, channel) is not None,
            "manualCommand": MANUAL_UPDATE_HINTS[method],
        }

    def update_ytdlp(self, settings=None):
        threading.Thread(target=self._run_update, args=(update_channel(settings),), daemon=True).start()
        return True

    def _run_update(self, channel="stable"):
        path = find_ytdlp()
        method, interpreter = detect_install_method(path) if path else ("standalone", None)
        cmd = update_command(method, path, interpreter, channel) if path else None
        if not cmd:
            self._emit("ytdlp-update-done", {
                "success": False,
                "error": f"Can't update automatically — {MANUAL_UPDATE_HINTS[method]}",
            })
            return

        self._emit("ytdlp-log", {"line": f"$ {' '.join(shlex.quote(a) for a in cmd)}"})
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            )
        except Exception as e:
            self._emit("ytdlp-update-done", {"success": False, "error": str(e)})
            return

        # Whatever happens from here, the UI must hear ytdlp-update-done or
        # its Update button stays wedged on "Updating…".
        code, version, error = -1, None, None
        try:
            for line in proc.stdout:
                line = line.rstrip("\n")
                if line:
                    self._emit("ytdlp-log", {"line": line})
            code = proc.wait()
            try:
                version = ytdlp_version(find_ytdlp() or path)
            except Exception:
                pass
        except Exception as e:
            error = str(e)
        finally:
            done = {"success": code == 0 and error is None, "code": code, "version": version}
            if error:
                done["error"] = error
            self._emit("ytdlp-update-done", done)

    def fetch_info(self, url, settings, dest):
        """Metadata for the preview card. Runs yt-dlp -J synchronously — the
        JS side awaits it off the UI thread and drops stale responses. Only
        one lookup runs at a time: a new one kills the previous, since the
        UI has already moved on from whatever that would have answered."""
        binary = find_ytdlp()
        if not binary:
            return {"ok": False, "error": "yt-dlp not found"}
        try:
            args = info_args(binary, settings, dest, url)
        except ValueError as e:   # shlex on a broken Extra Arguments string
            return {"ok": False, "error": f"invalid extra arguments: {e}"}
        with self._info_lock:
            old = self._info_proc
            if old and old.poll() is None:
                terminate_job(old)
            try:
                proc = subprocess.Popen(
                    args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    start_new_session=True,
                )
            except OSError as e:
                return {"ok": False, "error": str(e)}
            self._info_proc = proc
        try:
            stdout, stderr = proc.communicate(timeout=90)
        except subprocess.TimeoutExpired:
            terminate_job(proc)
            proc.communicate()
            return {"ok": False, "error": "timed out"}
        if proc.returncode != 0 or not stdout.strip():
            if proc.returncode < 0:
                return {"ok": False, "error": "cancelled"}   # superseded by a newer lookup
            err = (stderr or "").strip().splitlines()
            # With --verbose the last line is often a debug header, not the
            # error; a recognised failure anywhere in stderr reads better.
            hint = error_hint(err[-TAIL_LINES:])
            if hint:
                return {"ok": False, "error": hint["text"], "hint": hint}
            return {"ok": False, "error": err[-1] if err else f"yt-dlp exited with code {proc.returncode}"}
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return {"ok": False, "error": "couldn't parse yt-dlp's output"}
        with self._history_lock:
            downloaded = frozenset(archive_ids(load_history()))
        info = summarize_info(data, downloaded)
        info["ok"] = True
        return info

    def enqueue(self, urls, settings, dest):
        self.queue.set_max_concurrent(parallel_from_settings(settings))
        if skip_downloaded(settings):
            self._sync_archive()
        return self.queue.enqueue(urls, settings, dest)

    def _sync_archive(self):
        try:
            with self._history_lock:
                write_archive(load_history())
        except OSError:
            pass   # yt-dlp then sees a stale or missing archive; the download still runs

    def set_parallel(self, n):
        self.queue.set_max_concurrent(n)
        return True

    def retry_download(self, job_id):
        return self.queue.retry(job_id)

    def clear_ytdlp_cache(self):
        """`yt-dlp --rm-cache-dir` — the standard first step for 403s and
        stale signature functions. Logged like an update."""
        binary = find_ytdlp()
        if not binary:
            return {"ok": False, "error": "yt-dlp not found"}
        cmd = [binary, "--rm-cache-dir"]
        self._emit("ytdlp-log", {"line": f"$ {' '.join(shlex.quote(a) for a in cmd)}"})
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as e:
            self._emit("ytdlp-log", {"line": f"Error: {e}"})
            return {"ok": False, "error": str(e)}
        for line in (proc.stdout + proc.stderr).splitlines():
            if line.strip():
                self._emit("ytdlp-log", {"line": line})
        if proc.returncode != 0:
            return {"ok": False, "error": f"yt-dlp exited with code {proc.returncode}"}
        self._emit("ytdlp-log", {"line": "yt-dlp cache cleared."})
        return {"ok": True}

    def cancel_download(self, job_id):
        return self.queue.cancel(job_id)

    def cancel_all(self):
        return self.queue.cancel_all()

    def clear_finished(self):
        return self.queue.clear_finished()

    def remove_download(self, job_id):
        return self.queue.remove(job_id)

    def queue_snapshot(self):
        return self.queue.snapshot()

    def queue_state(self):
        state = self.queue.state()
        state["restored"] = self.restored
        self.restored = 0   # a one-time notice
        return state

    def _emit(self, event, payload):
        if self.window:
            js = f"window.dispatchEvent(new CustomEvent('{event}', {{detail: {json.dumps(payload)}}}))"
            self.window.evaluate_js(js)
        if event == "ytdlp-done":
            self._notify_if_drained()
            if self._record_history(payload["jobId"]):
                self._emit("ytdlp-history", {"jobId": payload["jobId"]})

    def _notify_if_drained(self):
        # ytdlp-done fires with the finished job already terminal and any
        # remaining work still queued/running, so "not active" here means
        # this was the last one — one notification for the whole batch.
        if self.queue.is_active():
            return
        finished = self.queue.unreported_finished()
        if not any(notifications_enabled(j["settings"]) for j in finished):
            return
        message = summarize_finished(finished)
        if not message:
            return
        try:
            self.notifier("yt-dlp", message)
        except Exception:
            # A missing/broken notification daemon must never take the
            # queue down with it — this runs on the worker thread, before
            # the queue dispatches the next job.
            pass


# --- single instance ----------------------------------------------------------------
# The browser extension launches `app.py <url>` on every click. When the app
# is already open that must not become a second window with its own empty
# queue (and two processes racing on settings.json/history.json), so the
# running instance listens on a Unix socket and later launches hand their
# URL over and exit.

class AlreadyRunning(Exception):
    pass


# sockaddr_un is 104 bytes on macOS, 108 on Linux; a deeply nested config
# or runtime directory can overrun it, and bind() then fails.
MAX_SOCKET_PATH = 100


def instance_socket_path():
    """XDG_RUNTIME_DIR is the proper home for a per-user socket (tmpfs,
    cleared at logout); macOS has no such thing, so the config dir is the
    fallback — and a short path in the temp dir if even that is too long
    to fit in a Unix socket address."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    for path in ([os.path.join(runtime, "ytdlp-gui.sock")] if runtime and os.path.isdir(runtime) else []) + [config_path("app.sock")]:
        if len(path) <= MAX_SOCKET_PATH:
            return path
    return os.path.join(tempfile.gettempdir(), f"ytdlp-gui-{os.getuid()}.sock")


def send_to_running_instance(urls, path=None, timeout=2.0, options=None):
    """Hand `urls` to a running app. True only if it acknowledged; False
    for no socket, a stale socket file, or anything else — the caller
    then launches normally. `options` carries what the extension popup
    asked for: a profile to apply, and whether to start straight away."""
    path = path or instance_socket_path()
    payload = dict(options or {}, urls=list(urls))
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(path)
            s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            reply = s.makefile("r", encoding="utf-8").readline()
        return bool(reply) and json.loads(reply).get("ok") is True
    except (OSError, ValueError):
        return False


class InstanceServer:
    """One JSON line per connection — {"urls": [...], "profile": ...,
    "enqueue": ...} — answered with {"ok": true} after `handler(urls,
    options)` has run on the server thread."""

    def __init__(self, handler, path=None):
        self.handler = handler
        self.path = path or instance_socket_path()
        self._sock = None
        self._thread = None

    def start(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.bind(self.path)
        except OSError:
            # The file exists. Either a live instance holds it (then this
            # process should hand off, not serve) or it's left over from a
            # crash and can be replaced.
            if self._someone_listening():
                sock.close()
                raise AlreadyRunning(self.path)
            try:
                os.unlink(self.path)
            except FileNotFoundError:
                pass
            sock.bind(self.path)
        sock.listen(4)
        self._sock = sock
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _someone_listening(self):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(1.0)
                probe.connect(self.path)
            return True
        except OSError:
            return False

    def _serve(self):
        sock = self._sock   # local: close() drops the attribute from another thread
        while True:
            try:
                conn, _ = sock.accept()
            except OSError:
                return   # closed
            with conn:
                try:
                    conn.settimeout(2.0)
                    line = conn.makefile("r", encoding="utf-8").readline()
                    if not line.strip():
                        continue   # a liveness probe, nothing to do
                    message = json.loads(line)
                    urls = [u for u in (message.get("urls") or []) if isinstance(u, str) and u.strip()]
                    self.handler(urls, {
                        "profile": message.get("profile") or "",
                        "enqueue": bool(message.get("enqueue")),
                    })
                    conn.sendall(b'{"ok": true}\n')
                except Exception as e:
                    try:
                        conn.sendall((json.dumps({"ok": False, "error": str(e)}) + "\n").encode("utf-8"))
                    except OSError:
                        pass

    def close(self):
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        try:
            os.unlink(self.path)
        except OSError:
            pass


WINDOW_BACKGROUNDS = {"dark": "#1e1e1e", "light": "#ffffff"}


def system_appearance():
    """'light' or 'dark' as the desktop reports it, defaulting to dark."""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                                 capture_output=True, text=True, timeout=2)
            # The key only exists in dark mode; absent means light.
            return "dark" if "dark" in out.stdout.strip().lower() else "light"
        out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                             capture_output=True, text=True, timeout=2)
        return "light" if "light" in out.stdout.lower() else "dark"
    except (OSError, subprocess.SubprocessError):
        return "dark"


def startup_background(settings):
    """The window's own background colour, so the frame doesn't flash the
    wrong theme before the page has painted. pywebview fixes this at
    creation, so it's read from the saved settings rather than the UI."""
    appearance = (settings or {}).get("appearance") or "system"
    if appearance not in WINDOW_BACKGROUNDS:
        appearance = system_appearance()
    return WINDOW_BACKGROUNDS.get(appearance, WINDOW_BACKGROUNDS["dark"])


def parse_argv(argv):
    """(url, options) from the command line. The extension's popup passes
    the same choices a running app receives over the socket."""
    url, options = "", {"profile": "", "enqueue": False}
    rest = list(argv)
    while rest:
        arg = rest.pop(0)
        if arg == "--profile" and rest:
            options["profile"] = rest.pop(0)
        elif arg.startswith("--profile="):
            options["profile"] = arg.split("=", 1)[1]
        elif arg == "--enqueue":
            options["enqueue"] = True
        elif not url and not arg.startswith("-"):
            url = arg
    return url, options


def main():
    initial_url, options = parse_argv(sys.argv[1:])
    # Already open? Hand the URL over and get out of the way. With no URL
    # this just brings the existing window forward.
    if send_to_running_instance([initial_url] if initial_url else [], options=options):
        return

    entry = "ui/index.html"
    if initial_url:
        entry += "?url=" + urllib.parse.quote(initial_url, safe="")
        if options["profile"]:
            entry += "&profile=" + urllib.parse.quote(options["profile"], safe="")
        if options["enqueue"]:
            entry += "&enqueue=1"

    api = Api()
    api.restore_queue()
    server = InstanceServer(api.add_urls)
    try:
        server.start()
    except OSError:
        # No socket (an unwritable or impossibly long path): later launches
        # can't hand over, but that's no reason not to open a window.
        server = None
    except AlreadyRunning:
        # Lost a race with another launch between the probe above and bind.
        if send_to_running_instance([initial_url] if initial_url else [], options=options):
            return
        server = None   # can't serve, but a window is still better than nothing
    window = webview.create_window(
        "yt-dlp",
        entry,
        js_api=api,
        width=860,
        height=640,
        min_size=(700, 520),
        background_color=startup_background((api.load_settings() or {}).get("settings")),
    )
    api.set_window(window)
    try:
        webview.start()
    finally:
        if server:
            server.close()


if __name__ == "__main__":
    main()
