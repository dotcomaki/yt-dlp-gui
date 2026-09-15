import json
import os
import shlex
import shutil
import ssl
import subprocess
import sys
import threading
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

PROGRESS_RE = re.compile(
    r"\[download\]\s+(?P<pct>[\d.]+)%.*?of\s+~?(?P<size>[\d.]+\S+)"
    r"(?:\s+at\s+(?P<speed>[\d.]+\S+/s))?(?:\s+ETA\s+(?P<eta>\S+))?"
)

QUALITY_FORMATS = {
    "best": "bestvideo+bestaudio/best",
    "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]",
    "audio": "bestaudio/best",
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


def settings_path():
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    config_dir = os.path.join(config_home, "ytdlp-gui")
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "settings.json")


YTDLP_RELEASES_API = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"


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


def fetch_latest_version(timeout=5):
    req = urllib.request.Request(
        YTDLP_RELEASES_API,
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


def update_command(method, path, interpreter=None):
    """argv that updates this install, or None if it has to be done by hand."""
    if method == "standalone":
        return [path, "-U"]
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


def build_args(binary, settings, dest):
    """Translate the settings dict from the UI into a yt-dlp argv list."""
    preset = settings.get("preset", "best")
    fmt = settings.get("format", {})
    filename = settings.get("filename", {})
    playlist = settings.get("playlist", {})
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

    # --- filename / output template ---
    template = (filename.get("template") or "%(title)s.%(ext)s").strip()
    args += ["-o", os.path.join(dest, template)]
    if filename.get("restrict"):
        args.append("--restrict-filenames")
    if filename.get("noOverwrites"):
        args.append("--no-overwrites")
    if filename.get("windowsFilenames"):
        args.append("--windows-filenames")

    # --- format / quality ---
    extract_audio = bool(audio.get("extractAudio")) or preset == "audio"
    custom_format = fmt.get("customFormat") if preset == "custom" else None

    if extract_audio:
        args += ["-f", custom_format or "bestaudio/best"]
        args.append("-x")
        args += ["--audio-format", audio.get("audioFormat") or "mp3"]
        if audio.get("audioQuality"):
            args += ["--audio-quality", str(audio["audioQuality"])]
    else:
        args += ["-f", custom_format or QUALITY_FORMATS.get(preset, QUALITY_FORMATS["best"])]
        merge_fmt = fmt.get("mergeOutputFormat") or "mp4"
        if merge_fmt != "none":
            args += ["--merge-output-format", merge_fmt]

    if fmt.get("preferFreeFormats"):
        args.append("--prefer-free-formats")
    if fmt.get("recodeVideo") and fmt["recodeVideo"] != "none":
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

    # --- subtitles ---
    if subs.get("write"):
        args.append("--write-subs")
    if subs.get("writeAuto"):
        args.append("--write-auto-subs")
    if subs.get("langs"):
        args += ["--sub-langs", subs["langs"]]
    if subs.get("embed"):
        args.append("--embed-subs")

    # --- thumbnail / metadata ---
    if thumb.get("write"):
        args.append("--write-thumbnail")
    if thumb.get("embed"):
        args.append("--embed-thumbnail")
    if thumb.get("addMetadata"):
        args.append("--add-metadata")
    if thumb.get("embedChapters"):
        args.append("--embed-chapters")

    # --- network ---
    if net.get("proxy"):
        args += ["--proxy", net["proxy"]]
    if net.get("rateLimit"):
        args += ["--limit-rate", net["rateLimit"]]
    if net.get("retries"):
        args += ["--retries", str(net["retries"])]
    if net.get("socketTimeout"):
        args += ["--socket-timeout", str(net["socketTimeout"])]
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
        args += ["--cookies-from-browser", auth["cookiesFromBrowser"]]

    # --- sponsorblock ---
    # No fallback to "all" here — the settings default already is "all",
    # so an empty value only happens when the user deliberately cleared
    # every category, which should mean "don't mark/remove anything",
    # not silently act on every category anyway.
    categories = sb.get("categories") or ""
    if isinstance(categories, (list, tuple)):
        categories = ",".join(c for c in categories if c)
    if sb.get("mark") and categories:
        args += ["--sponsorblock-mark", categories]
    if sb.get("remove") and categories:
        args += ["--sponsorblock-remove", categories]

    # --- geo-restriction ---
    if geo.get("bypass"):
        args.append("--geo-bypass")
    if geo.get("bypassCountry"):
        args += ["--geo-bypass-country", geo["bypassCountry"]]

    # --- post-run command ---
    if postrun.get("exec"):
        args += ["--exec", postrun["exec"]]

    # --- debug / verbosity ---
    if debug.get("verbose"):
        args.append("--verbose")
    if debug.get("simulate"):
        args.append("--simulate")
    if debug.get("ignoreErrors"):
        args.append("--ignore-errors")

    # --- raw extra arguments (escape hatch for anything not exposed above) ---
    if extra and extra.strip():
        args += shlex.split(extra)

    return args


class Api:
    def __init__(self):
        self.window = None
        self.proc = None
        self.cancelled = False

    def set_window(self, window):
        self.window = window

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
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def save_settings(self, payload):
        payload = sanitize_settings_payload(payload)
        try:
            with open(settings_path(), "w") as f:
                json.dump(payload, f, indent=2)
            return True
        except Exception:
            return False

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

    def check_binary(self):
        path = find_ytdlp()
        ffmpeg_path = find_ffmpeg()
        info = {"ffmpeg": bool(ffmpeg_path)}
        if not path:
            info["found"] = False
            return info
        try:
            info.update({"found": True, "path": path, "version": ytdlp_version(path)})
        except Exception as e:
            info.update({"found": False, "error": str(e)})
        return info

    def check_for_update(self, current=None):
        # `current` is the version check_binary() already reported — pass it
        # back in rather than re-running `yt-dlp --version`, which costs
        # several seconds on the standalone PyInstaller binary (it unpacks
        # itself on every launch).
        path = find_ytdlp()
        if not path:
            return {"ok": False, "reason": "not-found"}
        try:
            current = current or ytdlp_version(path)
            latest = fetch_latest_version()
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
            "updateAvailable": is_newer(latest, current),
            "method": method,
            "canAutoUpdate": update_command(method, path, interpreter) is not None,
            "manualCommand": MANUAL_UPDATE_HINTS[method],
        }

    def update_ytdlp(self):
        threading.Thread(target=self._run_update, daemon=True).start()
        return True

    def _run_update(self):
        path = find_ytdlp()
        method, interpreter = detect_install_method(path) if path else ("standalone", None)
        cmd = update_command(method, path, interpreter) if path else None
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

        for line in proc.stdout:
            line = line.rstrip("\n")
            if line:
                self._emit("ytdlp-log", {"line": line})
        code = proc.wait()

        version = None
        try:
            version = ytdlp_version(find_ytdlp() or path)
        except Exception:
            pass
        self._emit("ytdlp-update-done", {
            "success": code == 0,
            "code": code,
            "version": version,
        })

    def start_download(self, url, settings, dest):
        threading.Thread(target=self._run_download, args=(url, settings, dest), daemon=True).start()
        return True

    def cancel_download(self):
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        return True

    def _emit(self, event, payload):
        if self.window:
            js = f"window.dispatchEvent(new CustomEvent('{event}', {{detail: {json.dumps(payload)}}}))"
            self.window.evaluate_js(js)

    def _run_download(self, url, settings, dest):
        self.cancelled = False
        binary = find_ytdlp()
        if not binary:
            self._emit("ytdlp-error", {"message": "yt-dlp binary not found."})
            return

        os.makedirs(dest, exist_ok=True)

        try:
            args = build_args(binary, settings, dest) + [url]
        except Exception as e:
            self._emit("ytdlp-error", {"message": f"Invalid settings: {e}"})
            return

        self._emit("ytdlp-log", {"line": f"$ {' '.join(shlex.quote(a) for a in args)}"})

        try:
            self.proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            self._emit("ytdlp-error", {"message": str(e)})
            return

        for line in self.proc.stdout:
            line = line.rstrip("\n")
            if not line:
                continue
            self._emit("ytdlp-log", {"line": line})
            m = PROGRESS_RE.search(line)
            if m:
                self._emit("ytdlp-progress", {
                    "pct": float(m.group("pct")),
                    "size": m.group("size"),
                    "speed": m.group("speed") or "",
                    "eta": m.group("eta") or "",
                })

        code = self.proc.wait()
        if self.cancelled:
            self._emit("ytdlp-done", {"success": False, "cancelled": True})
        elif code == 0:
            self._emit("ytdlp-done", {"success": True, "cancelled": False})
        else:
            self._emit("ytdlp-done", {"success": False, "cancelled": False, "code": code})


def main():
    initial_url = sys.argv[1] if len(sys.argv) > 1 else ""
    entry = "ui/index.html"
    if initial_url:
        entry += "?url=" + urllib.parse.quote(initial_url, safe="")

    api = Api()
    window = webview.create_window(
        "yt-dlp",
        entry,
        js_api=api,
        width=860,
        height=640,
        min_size=(700, 520),
        background_color="#1e1e1e",
    )
    api.set_window(window)
    webview.start()


if __name__ == "__main__":
    main()
