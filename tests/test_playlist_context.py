"""Tests for keeping playlist context (numbering, title) on picked
entries, for keeping the preview's metadata fetch safe from whatever is
in Extra Arguments, and for ignoring yt-dlp's own config files."""
import time

import pytest

import app


def flag(args, name):
    return args[args.index(name) + 1]


@pytest.fixture(autouse=True)
def no_ffmpeg(monkeypatch):
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)


# --- per-item settings (one job with its own --playlist-items) -----------------------

def test_an_item_can_bring_its_own_settings():
    seen = []
    q = app.DownloadQueue(lambda e, p: None, lambda job, emit: seen.append((job["url"], job["settings"])) or 0)
    q.enqueue([
        {"url": "https://list", "title": "My list (2)", "settings": {"preset": "best", "playlist": {"items": "1,3"}}},
        "https://other",
    ], {"preset": "480p"}, "/dl")
    assert q.wait_idle()
    assert seen == [
        ("https://list", {"preset": "best", "playlist": {"items": "1,3"}}),
        ("https://other", {"preset": "480p"}),      # the batch's settings, as before
    ]


def test_playlist_items_reaches_the_command_line():
    args = app.build_args("yt-dlp", {"playlist": {"items": "1,3,7"}}, "/dl")
    assert flag(args, "--playlist-items") == "1,3,7"


def test_entries_carry_their_playlist_position():
    info = app.summarize_info({"_type": "playlist", "entries": [
        {"url": "https://v/1"}, {"title": "no url"}, {"url": "https://v/3"},
    ]})
    assert [(e["index"], e["url"]) for e in info["entries"]] == [(1, "https://v/1"), (3, "https://v/3")]


def test_an_explicit_playlist_index_wins_over_position():
    info = app.summarize_info({"_type": "playlist", "entries": [
        {"url": "https://v/a", "playlist_index": 11}, {"url": "https://v/b", "playlist_index": 12},
    ]})
    assert [e["index"] for e in info["entries"]] == [11, 12]


# --- preview-safe arguments ----------------------------------------------------------

@pytest.mark.parametrize("extra,expected", [
    ("-F", []),
    ("--list-subs --write-thumbnail", ["--write-thumbnail"]),
    ("--print filename", []),
    ("--print=filename", []),
    ("--exec 'rm -rf /' --retries 3", ["--retries", "3"]),
    ("--downloader aria2c", []),
    ("--skip-download --no-simulate", []),
    ("--cookies-from-browser firefox", ["--cookies-from-browser", "firefox"]),
])
def test_strip_preview_unsafe(extra, expected):
    import shlex
    assert app.strip_preview_unsafe(shlex.split(extra)) == expected


def test_preview_never_runs_exec_or_lists_formats():
    settings = {"postrun": {"exec": "rm -rf /tmp/x"}, "extraArgs": "-F --print filename",
                "playlist": {"skipDownloaded": True, "items": "1:3"}}
    args = app.info_args("yt-dlp", settings, "/dl", "https://v")
    for unsafe in ("--exec", "-F", "--print", "--download-archive"):
        assert unsafe not in args, unsafe
    assert flag(args, "--playlist-items") == "1:3"     # ranges still apply
    assert args[-4:] == ["-J", "--flat-playlist", "--no-warnings", "https://v"]


def test_preview_keeps_harmless_extra_args():
    args = app.info_args("yt-dlp", {"extraArgs": "--retries 5 -F"}, "/dl", "https://v")
    assert flag(args, "--retries") == "5" and "-F" not in args


def test_the_real_download_is_untouched_by_the_preview_filter():
    settings = {"postrun": {"exec": "echo hi"}, "extraArgs": "--print filename"}
    args = app.build_args("yt-dlp", settings, "/dl")
    assert flag(args, "--exec") == "echo hi" and "--print" in args


# --- yt-dlp's own config files --------------------------------------------------------

def test_config_files_are_ignored_by_default():
    assert "--ignore-config" in app.build_args("yt-dlp", {}, "/dl")


def test_opting_in_stops_ignoring_them():
    assert "--ignore-config" not in app.build_args("yt-dlp", {"debug": {"useConfigFile": True}}, "/dl")


def test_config_file_listing_only_reports_what_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    api = app.Api()
    assert [p for p in api.ytdlp_config_files() if str(tmp_path) in p] == []
    target = tmp_path / "cfg" / "yt-dlp"
    target.mkdir(parents=True)
    (target / "config").write_text("-f best\n")
    assert str(target / "config") in api.ytdlp_config_files()
