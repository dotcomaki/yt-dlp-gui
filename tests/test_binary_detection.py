"""Tests for the yt-dlp/ffmpeg/JS-runtime candidate-list detection logic.

find_ytdlp(), find_ffmpeg() and find_js_runtime() all walk an ordered
candidate list and return the first entry that exists and is executable, via
the shared _first_executable() helper. Candidate order matters (it's how the
real Homebrew-alias-drift and Apple-CLT-stub bugs got fixed — see
native_host.py's PYTHON_CANDIDATES comment for the sibling story on the
interpreter side), so these tests exercise both the shared helper and the
candidate lists.
"""
import os
import stat

import app


def make_executable(path):
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def test_first_executable_returns_first_match(tmp_path):
    missing = tmp_path / "does-not-exist"
    real = tmp_path / "real-binary"
    make_executable(real)

    assert app._first_executable([str(missing), str(real)]) == str(real)


def test_first_executable_skips_non_executable_file(tmp_path):
    not_executable = tmp_path / "not-executable"
    not_executable.write_text("no shebang, no x bit")
    real = tmp_path / "real-binary"
    make_executable(real)

    assert app._first_executable([str(not_executable), str(real)]) == str(real)


def test_first_executable_returns_none_when_nothing_matches(tmp_path):
    missing = tmp_path / "nope"
    assert app._first_executable([str(missing), None, ""]) is None


def test_first_executable_skips_none_and_empty_candidates(tmp_path):
    real = tmp_path / "real-binary"
    make_executable(real)
    assert app._first_executable([None, "", str(real)]) == str(real)


def test_find_ytdlp_uses_ytdlp_candidates(monkeypatch, tmp_path):
    fake = tmp_path / "yt-dlp"
    make_executable(fake)
    monkeypatch.setattr(app, "YTDLP_CANDIDATES", [str(fake)])
    assert app.find_ytdlp() == str(fake)


def test_find_ytdlp_returns_none_when_no_candidate_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "YTDLP_CANDIDATES", [str(tmp_path / "missing")])
    assert app.find_ytdlp() is None


def test_find_ffmpeg_uses_ffmpeg_candidates(monkeypatch, tmp_path):
    fake = tmp_path / "ffmpeg"
    make_executable(fake)
    monkeypatch.setattr(app, "FFMPEG_CANDIDATES", [str(fake)])
    assert app.find_ffmpeg() == str(fake)


def test_find_ffmpeg_returns_none_when_no_candidate_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "FFMPEG_CANDIDATES", [str(tmp_path / "missing")])
    assert app.find_ffmpeg() is None


# --- find_js_runtime -----------------------------------------------------------

def test_find_js_runtime_returns_name_and_path(monkeypatch, tmp_path):
    fake = tmp_path / "node"
    make_executable(fake)
    monkeypatch.setattr(app, "JS_RUNTIME_CANDIDATES", [("node", [str(fake)])])
    assert app.find_js_runtime() == ("node", str(fake))


def test_find_js_runtime_prefers_earlier_runtime(monkeypatch, tmp_path):
    # deno outranks node in yt-dlp's priority order even when both exist.
    deno = tmp_path / "deno"
    node = tmp_path / "node"
    make_executable(deno)
    make_executable(node)
    monkeypatch.setattr(app, "JS_RUNTIME_CANDIDATES", [
        ("deno", [str(deno)]),
        ("node", [str(node)]),
    ])
    assert app.find_js_runtime() == ("deno", str(deno))


def test_find_js_runtime_falls_through_to_next_runtime(monkeypatch, tmp_path):
    node = tmp_path / "node"
    make_executable(node)
    monkeypatch.setattr(app, "JS_RUNTIME_CANDIDATES", [
        ("deno", [str(tmp_path / "missing-deno"), None]),
        ("node", [str(tmp_path / "missing-node"), str(node)]),
    ])
    assert app.find_js_runtime() == ("node", str(node))


def test_find_js_runtime_returns_none_when_nothing_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "JS_RUNTIME_CANDIDATES", [
        ("deno", [str(tmp_path / "missing")]),
        ("node", [None, ""]),
    ])
    assert app.find_js_runtime() is None


def test_runtime_candidates_order(monkeypatch):
    # PATH hit first, then the usual install prefixes, then the per-runtime
    # extras (~/.deno/bin, nvm, …) — same shape as FFMPEG_CANDIDATES.
    monkeypatch.setattr(app.shutil, "which", lambda name: f"/from/path/{name}")
    assert app._runtime_candidates("deno", "/home/u/.deno/bin/deno") == [
        "/from/path/deno", "/opt/homebrew/bin/deno", "/usr/local/bin/deno", "/usr/bin/deno",
        "/home/u/.deno/bin/deno",
    ]


def test_nvm_node_candidates_newest_version_first(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / ".nvm" / "versions" / "node"
    for v in ("v9.11.2", "v22.12.0", "v18.20.4", "v22.9.0", ".DS_Store", "not-a-version"):
        (root / v / "bin").mkdir(parents=True)
    assert app._nvm_node_candidates() == [
        str(root / v / "bin" / "node") for v in ("v22.12.0", "v22.9.0", "v18.20.4", "v9.11.2")
    ]   # numeric order: string order would put v9 first and v22.9 above v22.12


def test_nvm_node_candidates_empty_without_nvm(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert app._nvm_node_candidates() == []
