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
        "thumbnail": "https://i/b.jpg", "url": "https://p", "formats": [], "entries": [],
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
    exe = stub_ytdlp(tmp_path, "echo 'WARNING: something' >&2\necho 'ERROR: [youtube] abc: something new and unknown' >&2\nexit 1\n")
    monkeypatch.setattr(app, "find_ytdlp", lambda: exe)
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)
    info = app.Api().fetch_info("https://v", {}, str(tmp_path))
    assert info == {"ok": False, "error": "ERROR: [youtube] abc: something new and unknown"}


def test_fetch_info_prefers_a_recognised_failure_over_the_last_line(tmp_path, monkeypatch):
    # with --verbose the last line is a debug header; the real error is earlier
    exe = stub_ytdlp(tmp_path, "echo 'ERROR: [youtube] abc: Sign in to confirm you\u2019re not a bot' >&2\n"
                               "echo '[debug] Exiting' >&2\nexit 1\n")
    monkeypatch.setattr(app, "find_ytdlp", lambda: exe)
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)
    info = app.Api().fetch_info("https://v", {}, str(tmp_path))
    assert info["error"].startswith("YouTube wants a signed-in session") and info["hint"]["action"] == "cookies"


def test_fetch_info_handles_garbage_output(tmp_path, monkeypatch):
    exe = stub_ytdlp(tmp_path, "echo 'not json'\n")
    monkeypatch.setattr(app, "find_ytdlp", lambda: exe)
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)
    info = app.Api().fetch_info("https://v", {}, str(tmp_path))
    assert info["ok"] is False and "parse" in info["error"]


def test_fetch_info_without_ytdlp(monkeypatch):
    monkeypatch.setattr(app, "find_ytdlp", lambda: None)
    assert app.Api().fetch_info("https://v", {}, "/tmp") == {"ok": False, "error": "yt-dlp not found"}


# --- playlist entries (#2) ------------------------------------------------------------

def test_playlist_entries_are_surfaced_in_order_with_title_and_duration():
    info = app.summarize_info({
        "_type": "playlist", "title": "L", "entries": [
            {"_type": "url", "url": "https://v/1", "title": "One", "duration": 61.9, "uploader": "a"},
            {"_type": "url", "url": "https://v/2", "title": "Two", "channel": "b"},
            {"_type": "url", "webpage_url": "https://v/3", "title": "Three", "duration": 5},
        ],
    })
    assert info["entries"] == [
        {"url": "https://v/1", "title": "One", "duration": 61, "uploader": "a", "downloaded": False},
        {"url": "https://v/2", "title": "Two", "duration": None, "uploader": "b", "downloaded": False},
        {"url": "https://v/3", "title": "Three", "duration": 5, "uploader": "", "downloaded": False},
    ]


def test_playlist_entries_without_a_url_are_skipped_and_titles_fall_back_to_url():
    info = app.summarize_info({"_type": "playlist", "entries": [None, {"title": "no url"}, {"url": "https://v/x"}]})
    assert info["entries"] == [{"url": "https://v/x", "title": "https://v/x", "duration": None, "uploader": "", "downloaded": False}]


def test_video_info_has_no_entries_key():
    assert "entries" not in app.summarize_info({"title": "t"})


# --- one lookup at a time (0c) ------------------------------------------------------

def test_a_newer_fetch_kills_the_previous_one(tmp_path, monkeypatch):
    import threading, time
    exe = stub_ytdlp(tmp_path, "sleep 30\necho '{}'\n")
    monkeypatch.setattr(app, "find_ytdlp", lambda: exe)
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)
    api = app.Api()
    results = {}
    t = threading.Thread(target=lambda: results.update(first=api.fetch_info("https://one", {}, str(tmp_path))))
    t.start()
    time.sleep(0.3)
    first_proc = api._info_proc
    exe2 = stub_ytdlp(tmp_path / "b", "echo '{\"title\": \"two\"}'\n") if (tmp_path / "b").mkdir() is None else None
    monkeypatch.setattr(app, "find_ytdlp", lambda: exe2)
    second = api.fetch_info("https://two", {}, str(tmp_path))
    t.join(5)
    assert second["ok"] is True and second["title"] == "two"
    assert results["first"] == {"ok": False, "error": "cancelled"}
    assert first_proc.poll() is not None   # really gone, not just ignored


def test_fetch_info_reports_broken_extra_args_cleanly(monkeypatch):
    monkeypatch.setattr(app, "find_ytdlp", lambda: "/bin/echo")
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)
    info = app.Api().fetch_info("https://v", {"extraArgs": "--foo 'unbalanced"}, "/tmp")
    assert info["ok"] is False and "invalid extra arguments" in info["error"]


# --- subtitle languages (#22) ---------------------------------------------------------

def test_summarize_subtitles_lists_manual_tracks_then_auto():
    info = app.summarize_info({
        "title": "t",
        "subtitles": {"en": [{"ext": "vtt", "name": "English"}], "de": [{"ext": "vtt"}]},
        "automatic_captions": {"en": [{"ext": "vtt"}], "fr": [{"ext": "vtt"}]},
    })
    assert info["subtitles"] == [
        {"code": "en", "name": "English", "auto": False},
        {"code": "de", "name": "de", "auto": False},
        {"code": "fr", "name": "fr", "auto": True},          # "en" already listed as manual
    ]


def test_summarize_subtitles_tolerates_missing_or_odd_data():
    assert app.summarize_info({"title": "t"})["subtitles"] == []
    assert app.summarize_info({"title": "t", "subtitles": {"en": None}})["subtitles"] == [
        {"code": "en", "name": "en", "auto": False}]
