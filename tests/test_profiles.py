"""Tests for named profiles: the on-disk shape, password exclusion per
profile, tolerance of malformed files, and the load/save round trip."""
import json

import app


def test_sanitize_strips_passwords_and_drops_malformed_entries():
    data = {"profiles": {
        "Podcast": {"settings": {"preset": "audio", "auth": {"password": "x", "username": "u"}}, "destFolder": "/p"},
        "  ": {"settings": {}},                       # blank name
        "NoSettings": {"destFolder": "/x"},           # missing settings
        "Wrong": "not a dict",
        "Bare": {"settings": {"preset": "best"}},     # no folder is fine
    }}
    out = app.sanitize_profiles(data)
    assert out == {"profiles": {
        "Podcast": {"settings": {"preset": "audio", "auth": {"password": "", "username": "u"}}, "destFolder": "/p"},
        "Bare": {"settings": {"preset": "best"}, "destFolder": ""},
    }}


def test_sanitize_tolerates_garbage():
    assert app.sanitize_profiles(None) == {"profiles": {}}
    assert app.sanitize_profiles({"profiles": "nope"}) == {"profiles": {}}


def test_load_missing_or_broken_file_is_empty():
    api = app.Api()
    assert api.load_profiles() == {"profiles": {}}
    with open(app.profiles_path(), "w") as f:
        f.write("{")
    assert api.load_profiles() == {"profiles": {}}


def test_save_then_load_round_trips_without_the_password():
    api = app.Api()
    assert api.save_profiles({"profiles": {"Archive": {"settings": {"preset": "best", "auth": {"password": "s3cret"}}, "destFolder": "/a"}}}) == {"ok": True}
    with open(app.profiles_path()) as f:
        on_disk = json.load(f)
    assert on_disk["profiles"]["Archive"]["settings"]["auth"]["password"] == ""
    assert api.load_profiles() == {"profiles": {"Archive": {"settings": {"preset": "best", "auth": {"password": ""}}, "destFolder": "/a"}}}


def test_profiles_live_beside_settings():
    import os
    assert os.path.dirname(app.profiles_path()) == os.path.dirname(app.settings_path())
    assert os.path.dirname(app.history_path()) == os.path.dirname(app.settings_path())


def test_save_failures_are_reported_not_swallowed(monkeypatch, tmp_path):
    blocker = tmp_path / "blocker"; blocker.write_text("")            # a file where the config dir should be
    monkeypatch.setenv("XDG_CONFIG_HOME", str(blocker))
    api = app.Api()
    r = api.save_settings({"settings": {}})
    assert r["ok"] is False and r["error"]
    r = api.save_profiles({"profiles": {}})
    assert r["ok"] is False and r["error"]
    assert api.load_settings() is None                                  # and loading degrades to defaults, no crash
