"""Tests for SponsorBlock category options and build_args command line generator."""
import re
from pathlib import Path

from app import build_args


def test_build_args_sponsorblock_default_all():
    settings = {
        "sponsorblock": {
            "mark": True,
            "remove": False,
            "categories": "all",
        }
    }
    args = build_args("yt-dlp", settings, "/tmp")
    assert "--sponsorblock-mark" in args
    assert args[args.index("--sponsorblock-mark") + 1] == "all"
    assert "--sponsorblock-remove" not in args


def test_build_args_sponsorblock_custom_categories_subset():
    settings = {
        "sponsorblock": {
            "mark": True,
            "remove": True,
            "categories": "sponsor,intro,outro",
        }
    }
    args = build_args("yt-dlp", settings, "/tmp")
    assert "--sponsorblock-mark" in args
    assert args[args.index("--sponsorblock-mark") + 1] == "sponsor,intro,outro"
    assert "--sponsorblock-remove" in args
    assert args[args.index("--sponsorblock-remove") + 1] == "sponsor,intro,outro"


def test_build_args_sponsorblock_disabled():
    settings = {
        "sponsorblock": {
            "mark": False,
            "remove": False,
            "categories": "all",
        }
    }
    args = build_args("yt-dlp", settings, "/tmp")
    assert "--sponsorblock-mark" not in args
    assert "--sponsorblock-remove" not in args


def test_build_args_sponsorblock_list_categories():
    settings = {
        "sponsorblock": {
            "mark": True,
            "remove": False,
            "categories": ["sponsor", "selfpromo", "filler"],
        }
    }
    args = build_args("yt-dlp", settings, "/tmp")
    assert "--sponsorblock-mark" in args
    assert args[args.index("--sponsorblock-mark") + 1] == "sponsor,selfpromo,filler"


def test_build_args_sponsorblock_empty_categories_no_flag():
    settings = {
        "sponsorblock": {
            "mark": True,
            "remove": False,
            "categories": "",
        }
    }
    args = build_args("yt-dlp", settings, "/tmp")
    # Empty categories string defaults back to "all" safely
    assert "--sponsorblock-mark" in args
    assert args[args.index("--sponsorblock-mark") + 1] == "all"


def test_build_args_baseline_and_destination():
    settings = {
        "preset": "best",
        "sponsorblock": {"mark": False, "remove": False, "categories": "all"},
    }
    args = build_args("yt-dlp", settings, "/media/downloads")
    assert args[0] == "yt-dlp"
    assert "--newline" in args
    assert "-o" in args
    assert args[args.index("-o") + 1].startswith("/media/downloads")


def test_html_sponsorblock_checkboxes_contract():
    html_path = Path(__file__).resolve().parent.parent / "ui" / "index.html"
    content = html_path.read_text(encoding="utf-8")

    # Verify All categories checkbox exists
    assert 'id="cb-sbCat-all"' in content

    # Verify all 8 standard SponsorBlock category checkboxes exist
    expected_categories = [
        "sponsor",
        "intro",
        "outro",
        "selfpromo",
        "preview",
        "filler",
        "interaction",
        "music_offtopic",
    ]

    for cat in expected_categories:
        assert f'value="{cat}"' in content, f"Missing category checkbox: {cat}"
        assert f'id="cb-sbCat-{cat}"' in content, f"Missing category checkbox ID: cb-sbCat-{cat}"

    # Verify old free-text input was removed
    assert 'data-bind="sponsorblock.categories"' not in content

    # Verify JavaScript wiring
    assert "initSponsorBlockCategories()" in content
    assert "updateSponsorBlockSettings" in content or "syncSettingsFromUI" in content
