# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unit & Mock Stage Execution Tests for Stage R1 (Notepad Test) and Stage R2 (Chrome Navigation).
"""

import json
import os
from pathlib import Path
import pytest

from tests.eval_suite.verifiers import (
    get_desktop_dir,
    verify_file_on_desktop,
    verify_process_running,
    verify_session_logs,
)
from tests.eval_suite.stages.stage_r1 import (
    DEFAULT_FILENAME as R1_DEFAULT_FILENAME,
    DEFAULT_MESSAGE as R1_DEFAULT_MESSAGE,
    pre_cleanup as pre_cleanup_r1,
    verify_r1,
)
from tests.eval_suite.stages.stage_r2 import (
    DEFAULT_INITIAL_URL as R2_DEFAULT_INITIAL_URL,
    DEFAULT_SECOND_URL as R2_DEFAULT_SECOND_URL,
    verify_r2,
)
from tests.eval_suite.eval_runner import EvaluationRunner


# --- Verifiers Unit Tests ---

def test_verify_file_on_desktop_missing():
    """Verify missing file handling on Desktop."""
    res = verify_file_on_desktop(filename="non_existent_ufo_test_file_99999.txt")
    assert res["verified"] is False
    assert res["exists"] is False
    assert res["content_matched"] is False
    assert res["error"] is not None


def test_verify_file_on_desktop_exists_and_content_matched():
    """Verify existing file on Desktop with matching content."""
    desktop = get_desktop_dir()
    test_file = desktop / "ufo_test_temp_verify.txt"
    test_content = "Hello from UFO 5-Stage Evaluation Suite!"
    try:
        test_file.write_text(test_content, encoding="utf-8")
        res = verify_file_on_desktop(
            filename="ufo_test_temp_verify.txt",
            expected_content=test_content,
        )
        assert res["verified"] is True
        assert res["exists"] is True
        assert res["content_matched"] is True
        assert res["actual_content"] == test_content
    finally:
        if test_file.exists():
            test_file.unlink()


def test_verify_file_on_desktop_content_mismatch():
    """Verify existing file with mismatched content."""
    desktop = get_desktop_dir()
    test_file = desktop / "ufo_test_temp_mismatch.txt"
    try:
        test_file.write_text("Wrong Content", encoding="utf-8")
        res = verify_file_on_desktop(
            filename="ufo_test_temp_mismatch.txt",
            expected_content="Expected Content",
        )
        assert res["verified"] is False
        assert res["exists"] is True
        assert res["content_matched"] is False
        assert res["error"] is not None
    finally:
        if test_file.exists():
            test_file.unlink()


def test_verify_process_running_non_existent():
    """Verify process check for non-existent process."""
    res = verify_process_running(["non_existent_app_process_12345.exe"])
    assert res["verified"] is False
    assert len(res["running_processes"]) == 0
    assert res["error"] is not None


def test_verify_process_running_python():
    """Verify process check for running python process."""
    res = verify_process_running(["python.exe", "python"])
    assert res["verified"] is True
    assert len(res["running_processes"]) > 0
    assert res["error"] is None


def test_verify_session_logs_missing_dir():
    """Verify session log check with missing directory."""
    res = verify_session_logs(log_dir=Path("non_existent_log_dir_12345"))
    assert res["verified"] is False
    assert res["total_steps"] == 0


def test_verify_session_logs_with_mock_log(tmp_path):
    """Verify session log parsing with valid log file."""
    log_dir = tmp_path / "mock_session_log"
    log_dir.mkdir(parents=True, exist_ok=True)
    resp_log = log_dir / "response.log"

    log_records = [
        {"step": 1, "action": "Open Notepad app", "status": "SUCCESS"},
        {"step": 2, "action": "type_text Hello from UFO", "status": "SUCCESS"},
        {"step": 3, "action": "save_file ufo_test.txt", "status": "SUCCESS"},
    ]
    with open(resp_log, "w", encoding="utf-8") as f:
        for rec in log_records:
            f.write(json.dumps(rec) + "\n")

    res = verify_session_logs(log_dir=log_dir, required_patterns=["Notepad", "save_file"])
    assert res["verified"] is True
    assert res["total_steps"] == 3
    assert "Notepad" in res["matched_patterns"]
    assert "save_file" in res["matched_patterns"]
    assert len(res["errors"]) == 0


def test_verify_session_logs_with_error(tmp_path):
    """Verify session log parsing when error record is present."""
    log_dir = tmp_path / "mock_error_log"
    log_dir.mkdir(parents=True, exist_ok=True)
    resp_log = log_dir / "response.log"

    log_records = [
        {"step": 1, "action": "Open Notepad", "status": "SUCCESS"},
        {"step": 2, "action": "type_text", "status": "ERROR", "last_error": "UI element not found"},
    ]
    with open(resp_log, "w", encoding="utf-8") as f:
        for rec in log_records:
            f.write(json.dumps(rec) + "\n")

    res = verify_session_logs(log_dir=log_dir, required_patterns=["Notepad"])
    assert res["verified"] is False
    assert len(res["errors"]) == 1
    assert "UI element not found" in res["errors"][0]


# --- Stage R1 Tests ---

def test_stage_r1_pre_cleanup():
    """Test stage R1 pre-cleanup function."""
    desktop = get_desktop_dir()
    test_file = desktop / R1_DEFAULT_FILENAME
    test_file.write_text("stale test content", encoding="utf-8")

    assert test_file.exists()
    pre_cleanup_r1(filename=R1_DEFAULT_FILENAME)
    assert not test_file.exists()


def test_stage_r1_verify_r1_dry_run():
    """Test stage R1 verifier in dry-run mode."""
    res = verify_r1(dry_run=True)
    assert res["verified"] is True
    assert res["stage_id"] == "R1"
    assert res["dry_run"] is True
    assert res["file_exists"] is True
    assert res["content_matched"] is True


def test_stage_r1_verify_r1_live(tmp_path):
    """Test stage R1 verifier with live file on Desktop."""
    desktop = get_desktop_dir()
    test_file = desktop / R1_DEFAULT_FILENAME
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "step_1.json").write_text(json.dumps({"action": "Notepad type text", "status": "SUCCESS"}), encoding="utf-8")
    try:
        test_file.write_text(R1_DEFAULT_MESSAGE, encoding="utf-8")
        res = verify_r1(task_log_dir=log_dir, dry_run=False)
        assert res["verified"] is True
        assert res["file_exists"] is True
        assert res["content_matched"] is True
    finally:
        if test_file.exists():
            test_file.unlink()


# --- Stage R2 Tests ---

def test_stage_r2_verify_r2_dry_run():
    """Test stage R2 verifier in dry-run mode."""
    res = verify_r2(dry_run=True)
    assert res["verified"] is True
    assert res["stage_id"] == "R2"
    assert res["dry_run"] is True
    assert res["chrome_process_detected"] is True
    assert res["trajectory_verified"] is True


def test_stage_r2_verify_r2_mock_logs(tmp_path):
    """Test stage R2 verifier with mock log directory."""
    log_dir = tmp_path / "mock_chrome_log"
    log_dir.mkdir(parents=True, exist_ok=True)
    resp_log = log_dir / "response.log"

    log_records = [
        {"step": 1, "action": "Open Google Chrome app", "status": "SUCCESS"},
        {"step": 2, "action": f"navigate {R2_DEFAULT_INITIAL_URL}", "status": "SUCCESS"},
        {"step": 3, "action": f"navigate {R2_DEFAULT_SECOND_URL}", "status": "SUCCESS"},
    ]
    with open(resp_log, "w", encoding="utf-8") as f:
        for rec in log_records:
            f.write(json.dumps(rec) + "\n")

    res = verify_r2(task_log_dir=log_dir, dry_run=False)
    assert res["stage_id"] == "R2"
    assert res["initial_url"] == R2_DEFAULT_INITIAL_URL
    assert res["second_url"] == R2_DEFAULT_SECOND_URL
    assert res["trajectory_verified"] is True


# --- Evaluation Runner Integration Tests ---

@pytest.mark.asyncio
async def test_eval_runner_r1_dry_run(tmp_path):
    """Test running Stage R1 via EvaluationRunner in dry-run mode."""
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    res = await runner.run_stage("R1")
    assert res["stage_id"] == "R1"
    assert res["status"] == "SUCCESS (DRY_RUN)"
    assert "verification" in res
    assert res["verification"]["verified"] is True
    assert res["verification"]["stage_id"] == "R1"


@pytest.mark.asyncio
async def test_eval_runner_r2_dry_run(tmp_path):
    """Test running Stage R2 via EvaluationRunner in dry-run mode."""
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    res = await runner.run_stage("R2")
    assert res["stage_id"] == "R2"
    assert res["status"] == "SUCCESS (DRY_RUN)"
    assert "verification" in res
    assert res["verification"]["verified"] is True
    assert res["verification"]["stage_id"] == "R2"


@pytest.mark.asyncio
async def test_eval_runner_r1_r2_suite_dry_run(tmp_path):
    """Test running R1 and R2 together via run_suite in dry-run mode."""
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    summary = await runner.run_suite(stages=["R1", "R2"])
    assert summary["total_stages"] == 2
    assert summary["passed_stages"] == 2
    assert summary["failed_stages"] == 0
    assert len(summary["stage_results"]) == 2
    assert summary["stage_results"][0]["stage_id"] == "R1"
    assert summary["stage_results"][1]["stage_id"] == "R2"
