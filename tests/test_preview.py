"""Tests for the pre-download preview: trimming yt-dlp -J output, format
filtering/sorting, the -f string a clicked row produces, and Api.fetch_info
against a stub yt-dlp (a shell script that prints canned JSON)."""
import json

import pytest

import app


def fmt(**kw):
    base = {"format_id": "x", "ext": "mp4", "vcodec": "avc1.4d401f", "acodec": "none",
            "height": 720, "resolution": "1280x720", "fps": 30, "filesize": 1000, "tbr": 500.0}
    base.update(kw)
    return base


# --- human_size ------------------------------------------------------------------

@pytest.mark.parametrize("n,expected", [
    (None, ""), (0, ""), (512, "512 B"), (1536, "1.5 KiB"),
    (5 * 1024 ** 2, "5.0 MiB"), (int(2.25 * 1024 ** 3), "2.2 GiB"),
])
def test_human_size(n, expected):
    assert app.human_size(n) == expected


# --- summarize_formats ------------------------------------------------------------

def test_drops_storyboards_and_codec_less_entries():
    formats = [
        fmt(format_id="sb0", ext="mhtml", vcodec="none", acodec="none", height=None, resolution="48x27", format_note="storyboard"),
        fmt(format_id="weird", vcodec="none", acodec="none"),
        fmt(format_id="137"),
    ]
    assert [f["id"] for f in app.summarize_formats(formats)] == ["137"]


def test_sorts_video_by_height_then_bitrate_with_audio_last():
    formats = [
        fmt(format_id="a-hi", vcodec="none", acodec="opus", height=None, resolution="audio only", tbr=130),
        fmt(format_id="v360", height=360, tbr=400),
        fmt(format_id="v1080-lo", height=1080, tbr=2000),
        fmt(format_id="a-lo", vcodec="none", acodec="opus", height=None, resolution="audio only", tbr=50),
        fmt(format_id="v1080-hi", height=1080, tbr=4000),
        fmt(format_id="combined", acodec="mp4a.40.2", height=720, tbr=1200),
    ]
    ids = [f["id"] for f in app.summarize_formats(formats)]
    assert ids == ["v1080-hi", "v1080-lo", "combined", "v360", "a-hi", "a-lo"]


def test_kind_and_codec_family():
    out = app.summarize_formats([
        fmt(format_id="v", vcodec="vp09.00.40.08", acodec="none"),
        fmt(format_id="a", vcodec="none", acodec="mp4a.40.2", height=None),
        fmt(format_id="va", vcodec="avc1.64001f", acodec="opus"),
    ])
    by = {f["id"]: f for f in out}
    assert by["v"]["kind"] == "video" and by["v"]["vcodec"] == "vp09" and by["v"]["acodec"] == ""
    assert by["a"]["kind"] == "audio" and by["a"]["acodec"] == "mp4a" and by["a"]["resolution"] == "audio only"
    assert by["va"]["kind"] == "video+audio"


def test_size_prefers_exact_then_approx():
    out = app.summarize_formats([
        fmt(format_id="exact", filesize=2048, filesize_approx=9999),
        fmt(format_id="approx", filesize=None, filesize_approx=4096),
        fmt(format_id="none", filesize=None, filesize_approx=None),
    ])
    by = {f["id"]: f["size"] for f in out}
    assert by == {"exact": "2.0 KiB", "approx": "4.0 KiB", "none": ""}


# --- format_selector -------------------------------------------------------------

def test_video_only_row_gets_audio_merged_in():
    assert app.format_selector({"id": "137", "kind": "video"}) == "137+bestaudio/best"


def test_rows_with_audio_stand_alone():
    assert app.format_selector({"id": "22", "kind": "video+audio"}) == "22"
    assert app.format_selector({"id": "251", "kind": "audio"}) == "251"


# --- summarize_info --------------------------------------------------------------

def test_video_info():
    info = app.summarize_info({
        "_type": "video", "title": "Me at the zoo", "uploader": "jawed", "duration": 19.4,
        "thumbnail": "https://i/thumb.jpg", "webpage_url": "https://w", "formats": [fmt(format_id="137")],
    })
    assert info["kind"] == "video"
    assert info["title"] == "Me at the zoo" and info["uploader"] == "jawed"
    assert info["duration"] == 19
    assert info["thumbnail"] == "https://i/thumb.jpg" and info["url"] == "https://w"
    assert [f["id"] for f in info["formats"]] == ["137"]


def test_video_info_falls_back_to_channel_and_tolerates_missing_fields():
    info = app.summarize_info({"title": "t", "channel": "chan"})
    assert info["uploader"] == "chan"
    assert info["duration"] is None and info["thumbnail"] is None and info["formats"] == []


def test_playlist_info_is_flat_and_counts_entries():
    info = app.summarize_info({
        "_type": "playlist", "title": "My List", "uploader": "someone",
        "entries": [{"id": "a"}, {"id": "b", "thumbnail": "https://i/b.jpg"}, {"id": "c"}],
        "webpage_url": "https://p",
    })
    assert info == {
        "kind": "playlist", "title": "My List", "uploader": "someone", "count": 3,
        "thumbnail": "https://i/b.jpg", "url": "https://p", "formats": [],
    }


def test_playlist_count_prefers_playlist_count_field():
    info = app.summarize_info({"_type": "playlist", "entries": [{}], "playlist_count": 250})
    assert info["count"] == 250


# --- info_args -------------------------------------------------------------------

def test_info_args_reuses_build_args_and_appends_json_flags(monkeypatch):
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)
    settings = {"auth": {"cookiesFromBrowser": "firefox"}, "network": {"proxy": "socks5://h:1"}}
    args = app.info_args("yt-dlp", settings, "/dl", "https://v")
    assert args[-1] == "https://v"
    assert args[-4:-1] == ["-J", "--flat-playlist", "--no-warnings"]
    assert "--cookies-from-browser" in args and "--proxy" in args   # same auth/network as the real download


# --- Api.fetch_info ----------------------------------------------------------------

def stub_ytdlp(tmp_path, script):
    exe = tmp_path / "yt-dlp"
    exe.write_text("#!/bin/sh\n" + script)
    exe.chmod(0o755)
    return str(exe)


def test_fetch_info_parses_json(tmp_path, monkeypatch):
    data = {"_type": "video", "title": "Stubbed", "duration": 5, "formats": [fmt(format_id="22", acodec="mp4a.40.2")]}
    exe = stub_ytdlp(tmp_path, f"cat <<'EOF'\n{json.dumps(data)}\nEOF\n")
    monkeypatch.setattr(app, "find_ytdlp", lambda: exe)
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)
    info = app.Api().fetch_info("https://v", {}, str(tmp_path))
    assert info["ok"] is True and info["title"] == "Stubbed"
    assert info["formats"][0]["id"] == "22" and info["formats"][0]["kind"] == "video+audio"


def test_fetch_info_reports_ytdlp_failure_with_last_stderr_line(tmp_path, monkeypatch):
    exe = stub_ytdlp(tmp_path, "echo 'WARNING: something' >&2\necho 'ERROR: [youtube] abc: Video unavailable' >&2\nexit 1\n")
    monkeypatch.setattr(app, "find_ytdlp", lambda: exe)
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)
    info = app.Api().fetch_info("https://v", {}, str(tmp_path))
    assert info == {"ok": False, "error": "ERROR: [youtube] abc: Video unavailable"}


def test_fetch_info_handles_garbage_output(tmp_path, monkeypatch):
    exe = stub_ytdlp(tmp_path, "echo 'not json'\n")
    monkeypatch.setattr(app, "find_ytdlp", lambda: exe)
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)
    info = app.Api().fetch_info("https://v", {}, str(tmp_path))
    assert info["ok"] is False and "parse" in info["error"]


def test_fetch_info_without_ytdlp(monkeypatch):
    monkeypatch.setattr(app, "find_ytdlp", lambda: None)
    assert app.Api().fetch_info("https://v", {}, "/tmp") == {"ok": False, "error": "yt-dlp not found"}
