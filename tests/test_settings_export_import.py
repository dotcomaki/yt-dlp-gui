"""Tests for settings export/import: sanitize_settings_payload() (pure
logic, no window needed) and Api.export_settings()/import_settings()
(mocking Api.window.create_file_dialog, since the real dialog needs an
actual GUI window pywebview can't provide in a test)."""
import json

import app


class FakeWindow:
    """Stands in for pywebview's window — just returns whatever path (or
    None, for "user cancelled") the test configures for the next dialog."""
    def __init__(self, dialog_result):
        self.dialog_result = dialog_result
        self.last_call = None

    def create_file_dialog(self, dialog_type, **kwargs):
        self.last_call = (dialog_type, kwargs)
        return self.dialog_result


# --- sanitize_settings_payload -----------------------------------------------

def test_sanitize_strips_password_only():
    payload = {
        "settings": {"auth": {"username": "alice", "password": "hunter2", "cookiesFile": "x"}},
        "destFolder": "/tmp",
    }
    result = app.sanitize_settings_payload(payload)
    assert result["settings"]["auth"]["password"] == ""
    assert result["settings"]["auth"]["username"] == "alice"
    assert result["settings"]["auth"]["cookiesFile"] == "x"
    assert result["destFolder"] == "/tmp"


def test_sanitize_does_not_mutate_the_original_payload():
    payload = {"settings": {"auth": {"password": "hunter2"}}}
    app.sanitize_settings_payload(payload)
    assert payload["settings"]["auth"]["password"] == "hunter2"


def test_sanitize_handles_missing_auth_gracefully():
    payload = {"settings": {"preset": "best"}}
    result = app.sanitize_settings_payload(payload)
    assert result == payload


def test_sanitize_handles_missing_settings_key_gracefully():
    payload = {"destFolder": "/tmp"}
    result = app.sanitize_settings_payload(payload)
    assert result == payload


# --- Api.export_settings ------------------------------------------------------

def test_export_writes_sanitized_payload(tmp_path):
    dest = tmp_path / "exported.json"
    api = app.Api()
    api.window = FakeWindow([str(dest)])

    payload = {"settings": {"preset": "720p", "auth": {"password": "secret"}}}
    result = api.export_settings(payload)

    assert result == {"ok": True, "path": str(dest)}
    written = json.loads(dest.read_text())
    assert written["settings"]["preset"] == "720p"
    assert written["settings"]["auth"]["password"] == ""


def test_export_reports_cancellation():
    api = app.Api()
    api.window = FakeWindow(None)  # user closed the save dialog without picking a file
    result = api.export_settings({"settings": {}})
    assert result == {"ok": False, "cancelled": True}


def test_export_reports_write_errors(tmp_path):
    # a directory that doesn't exist -> open() raises
    bad_dest = tmp_path / "no-such-dir" / "settings.json"
    api = app.Api()
    api.window = FakeWindow([str(bad_dest)])
    result = api.export_settings({"settings": {}})
    assert result["ok"] is False
    assert "error" in result


# --- Api.import_settings ------------------------------------------------------

def test_import_reads_valid_settings_file(tmp_path):
    src = tmp_path / "settings.json"
    src.write_text(json.dumps({"settings": {"preset": "480p"}, "destFolder": "/dl"}))

    api = app.Api()
    api.window = FakeWindow([str(src)])
    result = api.import_settings()

    assert result["ok"] is True
    assert result["data"]["settings"]["preset"] == "480p"
    assert result["data"]["destFolder"] == "/dl"


def test_import_reports_cancellation():
    api = app.Api()
    api.window = FakeWindow(None)
    result = api.import_settings()
    assert result == {"ok": False, "cancelled": True}


def test_import_rejects_invalid_json(tmp_path):
    src = tmp_path / "not-json.json"
    src.write_text("{not valid json")
    api = app.Api()
    api.window = FakeWindow([str(src)])
    result = api.import_settings()
    assert result["ok"] is False
    assert "error" in result


def test_import_rejects_json_missing_settings_key(tmp_path):
    src = tmp_path / "wrong-shape.json"
    src.write_text(json.dumps({"foo": "bar"}))
    api = app.Api()
    api.window = FakeWindow([str(src)])
    result = api.import_settings()
    assert result["ok"] is False
    assert "error" in result


def test_import_rejects_a_json_file_that_is_not_an_object(tmp_path):
    src = tmp_path / "array.json"
    src.write_text(json.dumps([1, 2, 3]))
    api = app.Api()
    api.window = FakeWindow([str(src)])
    result = api.import_settings()
    assert result["ok"] is False
