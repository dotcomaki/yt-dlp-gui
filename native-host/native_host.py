#!/usr/bin/env python3
"""Native messaging host: receives a YouTube URL from the browser extension
and opens the yt-dlp GUI app with that URL pre-filled."""

import json
import struct
import subprocess
import sys

APP_PATH = "/Applications/yt-dlp.app"


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
        subprocess.Popen(["open", "-a", APP_PATH, "--args", url])
        send_message({"ok": True})
    except Exception as e:
        send_message({"ok": False, "error": str(e)})


if __name__ == "__main__":
    main()
