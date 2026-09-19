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


def test_js_runtime_flag_included_as_name_colon_path(monkeypatch):
    monkeypatch.setattr(app, "find_js_runtime", lambda: ("node", "/home/u/.nvm/versions/node/v22.12.0/bin/node"))
    args = app.build_args("yt-dlp", {}, "/tmp")
    assert flag_value(args, "--js-runtimes") == "node:/home/u/.nvm/versions/node/v22.12.0/bin/node"


def test_js_runtime_flag_explicit_even_for_deno(monkeypatch):
    # deno is yt-dlp's default, but under the extension's minimal PATH it
    # still wouldn't find it on its own — the location is always spelled out.
    monkeypatch.setattr(app, "find_js_runtime", lambda: ("deno", "/opt/homebrew/bin/deno"))
    args = app.build_args("yt-dlp", {}, "/tmp")
    assert flag_value(args, "--js-runtimes") == "deno:/opt/homebrew/bin/deno"


def test_js_runtime_flag_omitted_when_not_found():
    # conftest empties JS_RUNTIME_CANDIDATES, so nothing is found here.
    args = app.build_args("yt-dlp", {}, "/tmp")
    assert "--js-runtimes" not in args


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


def test_sponsorblock_mark_only_categories_are_dropped_from_remove():
    # poi_highlight/chapter are valid for --sponsorblock-mark but yt-dlp
    # rejects them for --sponsorblock-remove; one shared list feeds both.
    settings = {"sponsorblock": {"mark": True, "remove": True, "categories": "sponsor,poi_highlight,chapter"}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert flag_value(args, "--sponsorblock-mark") == "sponsor,poi_highlight,chapter"
    assert flag_value(args, "--sponsorblock-remove") == "sponsor"


def test_sponsorblock_remove_omitted_when_only_mark_only_categories_selected():
    settings = {"sponsorblock": {"mark": False, "remove": True, "categories": "poi_highlight,chapter"}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert "--sponsorblock-remove" not in args


def test_sponsorblock_all_passes_through_to_remove_unchanged():
    # yt-dlp interprets "all" itself for remove (it excludes the mark-only
    # ones internally) — must not be expanded or filtered here.
    settings = {"sponsorblock": {"mark": True, "remove": True, "categories": "all"}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert flag_value(args, "--sponsorblock-remove") == "all"


def test_sponsorblock_legacy_free_text_whitespace_is_normalized():
    # Values saved by the pre-checkbox free-text field could contain spaces.
    settings = {"sponsorblock": {"mark": True, "categories": " intro , outro,, "}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert flag_value(args, "--sponsorblock-mark") == "intro,outro"


def test_sponsorblock_categories_as_list():
    settings = {"sponsorblock": {"mark": True, "categories": ["sponsor", "selfpromo", "filler"]}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert flag_value(args, "--sponsorblock-mark") == "sponsor,selfpromo,filler"


# --- geo-restriction -----------------------------------------------------------

def test_geo_country_maps_to_xff():
    # --geo-bypass / --geo-bypass-country are deprecated aliases; --xff is the option
    args = app.build_args("yt-dlp", {"geo": {"bypassCountry": " US "}}, "/tmp")
    assert flag_value(args, "--xff") == "US"
    assert "--geo-bypass" not in args and "--geo-bypass-country" not in args


def test_geo_disable_wins_and_default_sends_nothing():
    args = app.build_args("yt-dlp", {"geo": {"disable": True, "bypassCountry": "US"}}, "/tmp")
    assert flag_value(args, "--xff") == "never"
    args = app.build_args("yt-dlp", {"geo": {"bypass": True, "bypassCountry": ""}}, "/tmp")   # old settings key: ignored
    assert "--xff" not in args


# --- redaction of the logged command ----------------------------------------------

def test_redact_masks_passwords_and_proxy_userinfo():
    args = ["yt-dlp", "-u", "me", "-p", "hunter2", "--video-password", "vp", "--twofactor", "123456",
            "--proxy", "socks5://alice:s3cret@proxy:1080", "--proxy", "http://proxy:8080", "https://v"]
    out = app.redact_args(args)
    assert out == ["yt-dlp", "-u", "me", "-p", "••••••", "--video-password", "••••••", "--twofactor", "••••••",
                   "--proxy", "socks5://••••••@proxy:1080", "--proxy", "http://proxy:8080", "https://v"]
    assert args[4] == "hunter2"   # the real argv is untouched


def test_redact_leaves_ordinary_args_alone():
    args = ["yt-dlp", "-f", "best", "-o", "/dl/%(title)s.%(ext)s", "https://v"]
    assert app.redact_args(args) == args


def test_logged_command_never_shows_the_password(tmp_path, monkeypatch):
    exe = tmp_path / "yt-dlp"; exe.write_text("#!/bin/sh\nexit 0\n"); exe.chmod(0o755)
    monkeypatch.setattr(app, "find_ytdlp", lambda: str(exe))
    logs = []
    job = {"id": 1, "url": "https://v", "dest": str(tmp_path), "title": None, "pct": 0, "files": [], "proc": None,
           "cancel": False, "settings": {"auth": {"username": "u", "password": "hunter2"}, "network": {"proxy": "http://a:b@p:1"}}}
    app.run_download_job(job, lambda ev, p: logs.append((ev, p)))
    header = next(p["line"] for ev, p in logs if ev == "ytdlp-log" and p["line"].startswith("$ "))
    assert "hunter2" not in header and "a:b@" not in header
    assert "-p '••••••'" in header and "http://••••••@p:1" in header


# --- no ffmpeg ------------------------------------------------------------------------

def test_without_ffmpeg_presets_ask_for_a_single_merged_stream(monkeypatch):
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)
    args = app.build_args("yt-dlp", {"preset": "best"}, "/tmp")
    assert flag_value(args, "-f") == "best[vcodec!=none][acodec!=none]/best"
    assert "--merge-output-format" not in args and "--ffmpeg-location" not in args
    args = app.build_args("yt-dlp", {"preset": "720p"}, "/tmp")
    assert flag_value(args, "-f") == "best[height<=720][vcodec!=none][acodec!=none]/best[height<=720]"


def test_without_ffmpeg_a_custom_format_is_still_respected(monkeypatch):
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)
    args = app.build_args("yt-dlp", {"preset": "custom", "format": {"customFormat": "137+140"}}, "/tmp")
    assert flag_value(args, "-f") == "137+140"   # the user asked for it explicitly; yt-dlp will say what's wrong


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


# --- rate limit split across parallel downloads (#8) ----------------------------------

@pytest.mark.parametrize("text,expected", [
    ("50K", 50 * 1024),
    ("4.2M", int(4.2 * 1024 ** 2)),
    ("1G", 1024 ** 3),
    ("1048576", 1048576),
    (" 2m ", 2 * 1024 ** 2),
    ("1MiB", 1024 ** 2),
    ("", None),
    (None, None),
    ("fast", None),
    ("1.2.3K", None),
])
def test_parse_rate_limit(text, expected):
    assert app.parse_rate_limit(text) == expected


def test_rate_limit_is_split_across_parallel_slots():
    settings = {"network": {"rateLimit": "1M", "parallel": "2"}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert flag_value(args, "--limit-rate") == str(1024 ** 2 // 2)


def test_rate_limit_untouched_when_sequential():
    settings = {"network": {"rateLimit": "1M", "parallel": "1"}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert flag_value(args, "--limit-rate") == "1M"
    # and with no parallel key at all (settings from before #8)
    args = app.build_args("yt-dlp", {"network": {"rateLimit": "1M"}}, "/tmp")
    assert flag_value(args, "--limit-rate") == "1M"


def test_unparseable_rate_limit_passes_through_for_ytdlp_to_reject():
    settings = {"network": {"rateLimit": "lots", "parallel": "3"}}
    args = app.build_args("yt-dlp", settings, "/tmp")
    assert flag_value(args, "--limit-rate") == "lots"


@pytest.mark.parametrize("value,expected", [("2", 2), (3, 3), ("", 1), (None, 1), ("abc", 1), ("0", 1), ("-4", 1)])
def test_parallel_from_settings(value, expected):
    assert app.parallel_from_settings({"network": {"parallel": value}}) == expected
    assert app.parallel_from_settings({}) == 1
