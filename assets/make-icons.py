#!/usr/bin/env python3
"""Redraw the app icon at the sizes macOS and Linux want.

The extension's 128px PNG is the original, but it's too small to upscale
into a Dock icon, so the same artwork — a blue disc with a download
arrow — is drawn here at whatever size is asked for. Run this only when
the artwork changes; the results are checked in.

    python3 assets/make-icons.py        # needs Pillow, and iconutil for the .icns

Outputs:
    yt-dlp.app/Contents/Resources/AppIcon.icns   (macOS Dock/Finder)
    assets/icon-256.png, icon-512.png            (Linux .desktop)
"""
import os
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw

ACCENT = (10, 132, 255, 255)
WHITE = (255, 255, 255, 255)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def draw(size):
    """The artwork at `size` px, drawn 4x and downsampled for clean edges."""
    scale = 4
    s = size * scale
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    u = s / 128.0                      # the original was designed at 128px

    d.ellipse([14 * u, 14 * u, 114 * u, 114 * u], fill=ACCENT)

    stem_w = 11 * u
    cx = 64 * u
    d.rectangle([cx - stem_w / 2, 34 * u, cx + stem_w / 2, 74 * u], fill=WHITE)
    d.polygon([(44 * u, 70 * u), (84 * u, 70 * u), (cx, 96 * u)], fill=WHITE)
    d.rounded_rectangle([36 * u, 99 * u, 92 * u, 107 * u], radius=3 * u, fill=WHITE)

    return im.resize((size, size), Image.LANCZOS)


def main():
    out = os.path.join(ROOT, "assets")
    for size in (256, 512):
        draw(size).save(os.path.join(out, f"icon-{size}.png"))

    iconset = os.path.join(out, "AppIcon.iconset")
    shutil.rmtree(iconset, ignore_errors=True)
    os.makedirs(iconset)
    for size in (16, 32, 128, 256, 512):
        draw(size).save(os.path.join(iconset, f"icon_{size}x{size}.png"))
        draw(size * 2).save(os.path.join(iconset, f"icon_{size}x{size}@2x.png"))

    resources = os.path.join(ROOT, "yt-dlp.app", "Contents", "Resources")
    os.makedirs(resources, exist_ok=True)
    icns = os.path.join(resources, "AppIcon.icns")
    if not shutil.which("iconutil"):
        print("iconutil not found (macOS only) — left the .iconset in place", file=sys.stderr)
        return 1
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns], check=True)
    shutil.rmtree(iconset, ignore_errors=True)
    print("wrote", icns)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
