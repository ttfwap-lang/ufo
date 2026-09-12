# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Empirical Stress Test for Milestone 3 (challenger_m3_1).

Tests:
1. get_desktop_dir under missing/OneDrive environments and missing USERPROFILE.
2. verify_file_on_desktop under UTF-8 BOM, UTF-8-SIG, CRLF, and missing desktop directory.
3. verify_file_on_desktop with home directory fallback under UTF-8 BOM.
"""

import os
from pathlib import Path
import tempfile
import pytest

from tests.eval_suite.verifiers import get_desktop_dir, verify_file_on_desktop


def test_get_desktop_dir_onedrive_environment(tmp_path, monkeypatch):
    """Test get_desktop_dir when OneDrive/Desktop exists under USERPROFILE."""
    fake_userprofile = tmp_path / "user_profile"
    onedrive_desktop = fake_userprofile / "OneDrive" / "Desktop"
    onedrive_desktop.mkdir(parents=True)
    normal_desktop = fake_userprofile / "Desktop"
    normal_desktop.mkdir(parents=True)

    monkeypatch.setenv("USERPROFILE", str(fake_userprofile))
    resolved_desktop = get_desktop_dir()
    assert resolved_desktop == onedrive_desktop
    assert resolved_desktop.exists()


def test_get_desktop_dir_standard_environment(tmp_path, monkeypatch):
    """Test get_desktop_dir when standard Desktop exists (no OneDrive/Desktop)."""
    fake_userprofile = tmp_path / "user_profile"
    normal_desktop = fake_userprofile / "Desktop"
    normal_desktop.mkdir(parents=True)

    monkeypatch.setenv("USERPROFILE", str(fake_userprofile))
    resolved_desktop = get_desktop_dir()
    assert resolved_desktop == normal_desktop
    assert resolved_desktop.exists()


def test_get_desktop_dir_missing_userprofile_fallback(monkeypatch):
    """Test get_desktop_dir when USERPROFILE is unset."""
    monkeypatch.delenv("USERPROFILE", raising=False)
    resolved_desktop = get_desktop_dir()
    assert resolved_desktop == Path.home() / "Desktop"


def test_get_desktop_dir_missing_desktop_dirs(tmp_path, monkeypatch):
    """Test get_desktop_dir when USERPROFILE exists but neither Desktop nor OneDrive/Desktop exist."""
    fake_userprofile = tmp_path / "user_profile_empty"
    fake_userprofile.mkdir(parents=True)

    monkeypatch.setenv("USERPROFILE", str(fake_userprofile))
    resolved_desktop = get_desktop_dir()
    # Falls back to Path.home() / "Desktop"
    assert resolved_desktop == Path.home() / "Desktop"


def test_verify_file_on_desktop_utf8_bom(tmp_path, monkeypatch):
    """Test verify_file_on_desktop when file content contains UTF-8 BOM header."""
    fake_desktop = tmp_path / "Desktop"
    fake_desktop.mkdir(parents=True)
    monkeypatch.setattr("tests.eval_suite.verifiers.get_desktop_dir", lambda: fake_desktop)

    test_file = fake_desktop / "ufo_test_bom.txt"
    # Write file with explicit UTF-8 BOM bytes (\xef\xbb\xbf)
    bom_content = b"\xef\xbb\xbfHello from UFO 5-Stage Evaluation Suite!\r\n"
    test_file.write_bytes(bom_content)

    res = verify_file_on_desktop(
        filename="ufo_test_bom.txt",
        expected_content="Hello from UFO 5-Stage Evaluation Suite!",
    )

    assert res["verified"] is True
    assert res["exists"] is True
    assert res["content_matched"] is True
    assert "Hello from UFO 5-Stage Evaluation Suite!" in res["actual_content"]
    assert not res["actual_content"].startswith("\ufeff")


def test_verify_file_on_desktop_utf8_sig_encoding(tmp_path, monkeypatch):
    """Test verify_file_on_desktop written with utf-8-sig encoding and CRLF."""
    fake_desktop = tmp_path / "Desktop"
    fake_desktop.mkdir(parents=True)
    monkeypatch.setattr("tests.eval_suite.verifiers.get_desktop_dir", lambda: fake_desktop)

    test_file = fake_desktop / "ufo_test_sig.txt"
    expected_text = "Meeting notes: Review Q3 roadmap and budget.\r\nLine 2 info."
    test_file.write_text(expected_text, encoding="utf-8-sig")

    res = verify_file_on_desktop(
        filename="ufo_test_sig.txt",
        expected_content="Meeting notes: Review Q3 roadmap and budget.",
    )

    assert res["verified"] is True
    assert res["exists"] is True
    assert res["content_matched"] is True
    assert res["error"] is None


def test_verify_file_on_desktop_home_fallback_utf8_bom(tmp_path, monkeypatch):
    """Test verify_file_on_desktop home directory fallback with UTF-8 BOM."""
    fake_desktop = tmp_path / "EmptyDesktop"
    fake_desktop.mkdir(parents=True)
    monkeypatch.setattr("tests.eval_suite.verifiers.get_desktop_dir", lambda: fake_desktop)

    fake_home = tmp_path / "Home"
    fake_home.mkdir(parents=True)
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

    fallback_file = fake_home / "fallback_bom.txt"
    fallback_file.write_bytes(b"\xef\xbb\xbfFallback Content Header\nLine 2")

    res = verify_file_on_desktop(
        filename="fallback_bom.txt",
        expected_content="Fallback Content Header",
    )

    assert res["verified"] is True
    assert res["exists"] is True
    assert res["content_matched"] is True
    assert res["file_path"] == str(fallback_file)
