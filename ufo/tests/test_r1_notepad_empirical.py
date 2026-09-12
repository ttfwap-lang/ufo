# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Empirical Verification Harness for R1 (Notepad Test) Verifier and Stage Runner.
Created by Challenger 1 for M2 empirical verification.
"""

import json
import os
import shutil
from pathlib import Path
import pytest

from tests.eval_suite.stages.stage_r1 import (
    DEFAULT_FILENAME,
    DEFAULT_MESSAGE,
    pre_cleanup as pre_cleanup_r1,
    verify_r1,
)
from tests.eval_suite.verifiers import (
    get_desktop_dir,
    verify_file_on_desktop,
    verify_session_logs,
)
from tests.eval_suite.eval_runner import EvaluationRunner


class TestR1DesktopFileCreation:
    """Test 1: Desktop File Creation Verification."""

    def test_file_creation_on_desktop(self, tmp_path, monkeypatch):
        # Point USERPROFILE to tmp_path so desktop is tmp_path/Desktop
        desktop_dir = tmp_path / "Desktop"
        desktop_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

        target_file = desktop_dir / DEFAULT_FILENAME
        target_file.write_text(DEFAULT_MESSAGE, encoding="utf-8")

        result = verify_file_on_desktop(filename=DEFAULT_FILENAME, expected_content=DEFAULT_MESSAGE)
        assert result["exists"] is True
        assert result["verified"] is True
        assert result["content_matched"] is True
        assert result["file_path"] == str(target_file)
        assert result["actual_content"] == DEFAULT_MESSAGE
        assert result["error"] is None

    def test_fallback_to_home_directory(self, tmp_path, monkeypatch):
        # Desktop directory does NOT have the file, but Home directory does
        desktop_dir = tmp_path / "Desktop"
        desktop_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        home_file = tmp_path / DEFAULT_FILENAME
        home_file.write_text(DEFAULT_MESSAGE, encoding="utf-8")

        result = verify_file_on_desktop(filename=DEFAULT_FILENAME, expected_content=DEFAULT_MESSAGE)
        assert result["exists"] is True
        assert result["verified"] is True
        assert result["file_path"] == str(home_file)


class TestR1TextVerification:
    """Test 2: Text Verification & Content Matching Logic."""

    def test_exact_and_normalized_content_match(self, tmp_path, monkeypatch):
        desktop_dir = tmp_path / "Desktop"
        desktop_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "step1.json").write_text(json.dumps({"action": "Notepad type text", "status": "SUCCESS"}), encoding="utf-8")

        # Windows line endings \r\n vs expected \n
        target_file = desktop_dir / DEFAULT_FILENAME
        target_file.write_text("Hello from UFO 5-Stage Evaluation Suite!\r\n", encoding="utf-8")

        result = verify_r1(task_log_dir=log_dir, expected_message=DEFAULT_MESSAGE, target_filename=DEFAULT_FILENAME)
        assert result["verified"] is True
        assert result["file_exists"] is True
        assert result["content_matched"] is True

    def test_mismatched_text_content(self, tmp_path, monkeypatch):
        desktop_dir = tmp_path / "Desktop"
        desktop_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "step1.json").write_text(json.dumps({"action": "Notepad type text", "status": "SUCCESS"}), encoding="utf-8")

        target_file = desktop_dir / DEFAULT_FILENAME
        target_file.write_text("Completely incorrect message content!", encoding="utf-8")

        result = verify_r1(task_log_dir=log_dir, expected_message=DEFAULT_MESSAGE, target_filename=DEFAULT_FILENAME)
        assert result["verified"] is False
        assert result["file_exists"] is True
        assert result["content_matched"] is False
        assert result["actual_content"] == "Completely incorrect message content!"

    def test_unicode_utf8_sig_encoding(self, tmp_path, monkeypatch):
        desktop_dir = tmp_path / "Desktop"
        desktop_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

        # UTF-8 with BOM
        target_file = desktop_dir / DEFAULT_FILENAME
        target_file.write_text(DEFAULT_MESSAGE, encoding="utf-8-sig")

        result = verify_file_on_desktop(filename=DEFAULT_FILENAME, expected_content=DEFAULT_MESSAGE)
        assert result["verified"] is True
        assert result["content_matched"] is True
        # Note: verifiers.py tries 'utf-8' before 'utf-8-sig', so \ufeff BOM is retained in actual_content
        assert result["actual_content"].lstrip("\ufeff") == DEFAULT_MESSAGE


class TestR1StaleFilePreCleanup:
    """Test 3: Stale File Pre-Cleanup Logic."""

    def test_pre_cleanup_removes_existing_desktop_and_home_files(self, tmp_path, monkeypatch):
        desktop_dir = tmp_path / "Desktop"
        desktop_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        stale_desktop_file = desktop_dir / DEFAULT_FILENAME
        stale_desktop_file.write_text("Stale desktop file", encoding="utf-8")

        stale_home_file = tmp_path / DEFAULT_FILENAME
        stale_home_file.write_text("Stale home file", encoding="utf-8")

        assert stale_desktop_file.exists()
        assert stale_home_file.exists()

        pre_cleanup_r1(filename=DEFAULT_FILENAME)

        assert not stale_desktop_file.exists()
        assert not stale_home_file.exists()


class TestR1MissingFileFailureHandling:
    """Test 4: Missing File Failure Handling."""

    def test_missing_file_returns_unverified_with_clear_error(self, tmp_path, monkeypatch):
        desktop_dir = tmp_path / "Desktop"
        desktop_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        # File does not exist anywhere
        result = verify_r1(target_filename="non_existent_file.txt")

        assert result["verified"] is False
        assert result["file_exists"] is False
        assert result["content_matched"] is False
        assert "not found" in result["details"].lower() or result["file_exists"] is False


@pytest.mark.asyncio
async def test_eval_runner_r1_stage_lifecycle(tmp_path, monkeypatch):
    """Test full Stage R1 lifecycle via EvaluationRunner in dry-run and live log verification."""
    desktop_dir = tmp_path / "Desktop"
    desktop_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    # Put a stale file
    stale_file = desktop_dir / DEFAULT_FILENAME
    stale_file.write_text("Stale file content", encoding="utf-8")

    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    res = await runner.run_stage("R1")

    # Verify pre_cleanup is skipped during dry_run=True to prevent side effects, so stale file remains
    assert stale_file.exists()
    assert res["status"] == "SUCCESS (DRY_RUN)"
    assert res["verification"]["verified"] is True
