"""Tests for build_args() — the function that turns the UI's settings dict
into the actual yt-dlp argv list. This is the highest-value place to have
coverage: every Advanced-tab option flows through it, and it has no GUI
dependency, so it's fully testable without a real window or browser.
"""
import pytest

import app


@pytest.fixture(autouse=True)
def fixed_ffmpeg(monkeypatch):
    """build_args() always calls find_ffmpeg() to inject --ffmpeg-location.
    Pin it to a fixed value so tests don't depend on the test machine's
    actual ffmpeg install state.
    """
    monkeypatch.setattr(app, "find_ffmpeg", lambda: "/usr/bin/ffmpeg")


def flag_value(args, flag):
    """Return the value following `flag` in an argv list, or None if the
    flag isn't present."""
    if flag not in args:
        return None
    return args[args.index(flag) + 1]


def test_baseline_structure():
    args = app.build_args("yt-dlp", {}, "/tmp/out")
    assert args[0] == "yt-dlp"
    assert "--newline" in args
    assert flag_value(args, "-o") == "/tmp/out/%(title)s.%(ext)s"
    # default preset is "best"
    assert flag_value(args, "-f") == "bestvideo+bestaudio/best"
    assert flag_value(args, "--merge-output-format") == "mp4"


def test_ffmpeg_location_included_when_found(monkeypatch):
    monkeypatch.setattr(app, "find_ffmpeg", lambda: "/opt/homebrew/bin/ffmpeg")
    args = app.build_args("yt-dlp", {}, "/tmp")
    assert flag_value(args, "--ffmpeg-location") == "/opt/homebrew/bin/ffmpeg"


def test_ffmpeg_location_omitted_when_not_found(monkeypatch):
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)
    args = app.build_args("yt-dlp", {}, "/tmp")
    assert "--ffmpeg-location" not in args


# --- filename / output template -------------------------------------------

def test_custom_output_template():
    settings = {"filename": {"template": "%(uploader)s/%(title)s.%(ext)s"}}
    args = app.build_args("yt-dlp", settings, "/dl")
    assert flag_value(args, "-o") == "/dl/%(uploader)s/%(title)s.%(ext)s"


def test_filename_flags():
    settings = {"filename": {"restrict": True, "noOverwrites": True, "windowsFilenames": True}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert "--restrict-filenames" in args
    assert "--no-overwrites" in args
    assert "--windows-filenames" in args


# --- format / quality -------------------------------------------------------

@pytest.mark.parametrize("preset,expected_format", [
    ("best", "bestvideo+bestaudio/best"),
    ("720p", "bestvideo[height<=720]+bestaudio/best[height<=720]"),
    ("480p", "bestvideo[height<=480]+bestaudio/best[height<=480]"),
])
def test_quality_presets(preset, expected_format):
    args = app.build_args("yt-dlp", {"preset": preset}, "/tmp")
    assert flag_value(args, "-f") == expected_format
    assert "-x" not in args


def test_audio_only_preset():
    args = app.build_args("yt-dlp", {"preset": "audio"}, "/tmp")
    assert flag_value(args, "-f") == "bestaudio/best"
    assert "-x" in args
    assert flag_value(args, "--audio-format") == "mp3"
    # audio-only downloads don't merge video+audio
    assert "--merge-output-format" not in args


def test_audio_extract_flag_independent_of_preset():
    # audio.extractAudio can force audio extraction even on a video preset
    settings = {"preset": "720p", "audio": {"extractAudio": True, "audioFormat": "flac"}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert "-x" in args
    assert flag_value(args, "--audio-format") == "flac"


def test_custom_format_string():
    settings = {"preset": "custom", "format": {"customFormat": "bestvideo[ext=mp4]+bestaudio[ext=m4a]"}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert flag_value(args, "-f") == "bestvideo[ext=mp4]+bestaudio[ext=m4a]"


def test_merge_output_format_none_omits_flag():
    settings = {"format": {"mergeOutputFormat": "none"}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert "--merge-output-format" not in args


def test_prefer_free_formats_and_recode():
    settings = {"format": {"preferFreeFormats": True, "recodeVideo": "mkv"}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert "--prefer-free-formats" in args
    assert flag_value(args, "--recode-video") == "mkv"


def test_keep_video():
    settings = {"audio": {"extractAudio": True, "keepVideo": True}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert "--keep-video" in args


# --- playlist ----------------------------------------------------------------

def test_playlist_options():
    settings = {"playlist": {"items": "1-3,7", "noPlaylist": True, "maxDownloads": 5}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert flag_value(args, "--playlist-items") == "1-3,7"
    assert "--no-playlist" in args
    assert flag_value(args, "--max-downloads") == "5"


# --- subtitles -----------------------------------------------------------------

def test_subtitle_options():
    settings = {"subtitles": {"write": True, "writeAuto": True, "langs": "en,es", "embed": True}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert "--write-subs" in args
    assert "--write-auto-subs" in args
    assert flag_value(args, "--sub-langs") == "en,es"
    assert "--embed-subs" in args


# --- thumbnail / metadata -------------------------------------------------------

def test_thumbnail_and_metadata_options():
    settings = {"thumbnail": {"write": True, "embed": True, "addMetadata": True, "embedChapters": True}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert "--write-thumbnail" in args
    assert "--embed-thumbnail" in args
    assert "--add-metadata" in args
    assert "--embed-chapters" in args


# --- network -----------------------------------------------------------------

def test_network_options():
    settings = {"network": {
        "proxy": "socks5://127.0.0.1:9050",
        "rateLimit": "1M",
        "retries": 10,
        "socketTimeout": 20,
        "forceIpv4": True,
    }}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert flag_value(args, "--proxy") == "socks5://127.0.0.1:9050"
    assert flag_value(args, "--limit-rate") == "1M"
    assert flag_value(args, "--retries") == "10"
    assert flag_value(args, "--socket-timeout") == "20"
    assert "-4" in args
    assert "-6" not in args


def test_force_ipv6():
    args = app.build_args("yt-dlp", {"network": {"forceIpv6": True}}, "/tmp")
    assert "-6" in args


# --- auth / cookies ------------------------------------------------------------

def test_auth_options():
    settings = {"auth": {
        "username": "alice",
        "password": "hunter2",
        "cookiesFile": "/home/alice/cookies.txt",
        "cookiesFromBrowser": "firefox",
    }}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert flag_value(args, "-u") == "alice"
    assert flag_value(args, "-p") == "hunter2"
    assert flag_value(args, "--cookies") == "/home/alice/cookies.txt"
    assert flag_value(args, "--cookies-from-browser") == "firefox"


def test_cookies_from_browser_none_is_skipped():
    args = app.build_args("yt-dlp", {"auth": {"cookiesFromBrowser": "none"}}, "/tmp")
    assert "--cookies-from-browser" not in args


# --- sponsorblock --------------------------------------------------------------

def test_sponsorblock_mark_and_remove_with_categories():
    settings = {"sponsorblock": {"mark": True, "remove": True, "categories": "sponsor,intro"}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert flag_value(args, "--sponsorblock-mark") == "sponsor,intro"
    assert flag_value(args, "--sponsorblock-remove") == "sponsor,intro"


def test_sponsorblock_disabled_by_default():
    args = app.build_args("yt-dlp", {"sponsorblock": {"categories": "all"}}, "/tmp")
    assert "--sponsorblock-mark" not in args
    assert "--sponsorblock-remove" not in args


def test_sponsorblock_empty_categories_omits_flag():
    # Regression test: an empty category selection must not silently act
    # on every category. See the PR #13 review discussion.
    settings = {"sponsorblock": {"mark": True, "remove": True, "categories": ""}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert "--sponsorblock-mark" not in args
    assert "--sponsorblock-remove" not in args


def test_sponsorblock_categories_as_list():
    settings = {"sponsorblock": {"mark": True, "categories": ["sponsor", "selfpromo", "filler"]}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert flag_value(args, "--sponsorblock-mark") == "sponsor,selfpromo,filler"


# --- geo-restriction -----------------------------------------------------------

def test_geo_options():
    settings = {"geo": {"bypass": True, "bypassCountry": "US"}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert "--geo-bypass" in args
    assert flag_value(args, "--geo-bypass-country") == "US"


# --- post-run command ------------------------------------------------------------

def test_postrun_exec():
    settings = {"postrun": {"exec": "open {}"}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert flag_value(args, "--exec") == "open {}"


# --- debug / verbosity -----------------------------------------------------------

def test_debug_flags():
    settings = {"debug": {"verbose": True, "simulate": True, "ignoreErrors": True}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert "--verbose" in args
    assert "--simulate" in args
    assert "--ignore-errors" in args


# --- extra arguments passthrough --------------------------------------------------

def test_extra_args_are_shlex_split():
    settings = {"extraArgs": "--write-info-json --no-mtime"}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert "--write-info-json" in args
    assert "--no-mtime" in args


def test_extra_args_respects_quoting():
    settings = {"extraArgs": '--exec "echo hello world"'}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert "echo hello world" in args


def test_blank_extra_args_adds_nothing():
    args_empty = app.build_args("yt-dlp", {"extraArgs": ""}, "/tmp")
    args_whitespace = app.build_args("yt-dlp", {"extraArgs": "   "}, "/tmp")
    args_none = app.build_args("yt-dlp", {}, "/tmp")
    # same length as each other — nothing extra got appended
    assert len(args_empty) == len(args_whitespace) == len(args_none)
