#!/usr/bin/env python3
"""Native messaging host: receives a YouTube URL from the browser extension
and launches the yt-dlp GUI with that URL pre-filled."""

import json
import os
import shutil
import struct
import subprocess
import sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_SCRIPT = os.path.join(PROJECT_DIR, "app.py")

# Apps spawned outside an interactive shell (like this native messaging host)
# get a minimal PATH that often resolves `python3` to the wrong interpreter
# (e.g. Apple's Command Line Tools stub on macOS, which never has pywebview),
# so check known install locations directly rather than trusting PATH
# resolution. Listing paths that don't apply on the current OS/setup is
# harmless — they're just skipped by the existence check in find_python.
#
# find_python() deliberately does NOT execute any of these to verify
# pywebview is importable (e.g. running `python3 -c "import webview"`).
# That seems obvious for validation, but executing a binary that macOS
# hasn't seen before is exactly what can trigger a Gatekeeper "is
# damaged, move to Trash" dialog on first launch — observed repeatedly
# even for candidates that would have passed the check. So this only
# ever runs ONE interpreter, ever: whichever one is actually used to
# launch app.py below. If that pick is wrong, app.py fails fast with a
# normal ModuleNotFoundError instead of a silent/blocking OS dialog.
PYTHON_CANDIDATES = [
    # A project-local virtualenv, if one exists, takes priority over
    # anything system-wide — this is also the standard workaround for
    # PEP 668 ("externally-managed-environment") on modern Linux distros,
    # which blocks plain `pip install` into the system Python entirely.
    os.path.join(PROJECT_DIR, "venv", "bin", "python3"),
    os.path.join(PROJECT_DIR, ".venv", "bin", "python3"),
    # macOS — /usr/local/bin/python3 and the pinned framework versions come
    # before /opt/homebrew/bin/python3 deliberately: that symlink tracks
    # whatever Homebrew's *default* python3 formula currently is, which
    # drifts across major versions as Homebrew updates it (observed: it
    # silently became 3.14, installed as some other formula's dependency,
    # with no pywebview). Probing an interpreter we've never run before is
    # exactly what can trigger a Gatekeeper "is damaged" first-launch
    # dialog for something we don't even need — so check the stable,
    # known-good locations first and only reach for the drifting one last.
    "/usr/local/bin/python3",
    "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3",
    "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3",
    "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3",
    "/opt/homebrew/bin/python3",
    # Linux (distro package managers put python3 on the system PATH more
    # consistently than macOS does, but check explicitly anyway)
    "/usr/bin/python3",
    "/usr/local/bin/python3",
]


def find_python():
    for path in PYTHON_CANDIDATES:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return shutil.which("python3") or "python3"


def read_message():
    raw_length = sys.stdin.buffer.read(4)
    if len(raw_length) == 0:
        sys.exit(0)
    length = struct.unpack("=I", raw_length)[0]
    data = sys.stdin.buffer.read(length).decode("utf-8")
    return json.loads(data)


def send_message(obj):
    encoded = json.dumps(obj).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("=I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def main():
    message = read_message()
    url = message.get("url", "")

    try:
        python_bin = find_python()
        subprocess.Popen(
            [python_bin, APP_SCRIPT, url],
            cwd=PROJECT_DIR,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        send_message({"ok": True})
    except Exception as e:
        send_message({"ok": False, "error": str(e)})


if __name__ == "__main__":
    main()
