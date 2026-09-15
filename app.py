import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import re
import urllib.parse

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
            out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
            info.update({"found": True, "path": path, "version": out.stdout.strip()})
        except Exception as e:
            info.update({"found": False, "error": str(e)})
        return info

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
