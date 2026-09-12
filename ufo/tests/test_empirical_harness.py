# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Empirical Challenge Harness for Milestones 2, 3, and 4 (5-Stage E2E GUI Evaluation Suite).
Tests:
1. Stage pre-cleanup error handling
2. Invalid stage ID inputs
3. Missing log directories
4. Content mismatch verifications
"""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
import pytest

from tests.eval_suite.eval_runner import EvaluationRunner, EVAL_STAGES
from tests.eval_suite.verifiers import (
    get_desktop_dir,
    verify_file_on_desktop,
    verify_process_running,
    verify_session_logs,
    verify_bankfidelity_process,
)
from tests.eval_suite.stages import stage_r1, stage_r2, stage_r3, stage_r4, stage_r5


# ---------------------------------------------------------------------------
# 1. EMPIRICAL CHALLENGE: STAGE PRE-CLEANUP ERROR HANDLING
# ---------------------------------------------------------------------------

def test_challenge_pre_cleanup_exception_handling():
    """Verify EvaluationRunner handles pre_cleanup exceptions gracefully without crashing."""
    runner = EvaluationRunner(dry_run=True, log_level="ERROR")

    # Create a custom stage config with a failing pre_cleanup
    def failing_pre_cleanup():
        raise RuntimeError("Simulated pre-cleanup disk error")

    # Temporarily patch R1 stage pre_cleanup
    original_pre_cleanup = EVAL_STAGES["R1"]["pre_cleanup"]
    EVAL_STAGES["R1"]["pre_cleanup"] = failing_pre_cleanup

    try:
        # run_stage should not raise exception when pre_cleanup fails
        res = asyncio.run(runner.run_stage("R1"))
        assert res["status"] == "SUCCESS (DRY_RUN)"
    finally:
        EVAL_STAGES["R1"]["pre_cleanup"] = original_pre_cleanup


def test_challenge_stage_r1_pre_cleanup_locked_or_missing_file():
    """Verify stage_r1 pre_cleanup handles non-existent or read-only desktop files."""
    desktop = get_desktop_dir()
    test_file = desktop / "ufo_test_challenge_temp.txt"
    
    # Ensure file doesn't exist initially
    if test_file.exists():
        test_file.unlink()

    # Pre-cleanup on non-existent file should be a no-op and not raise exception
    stage_r1.pre_cleanup(filename="ufo_test_challenge_temp.txt")

    # Create dummy file, run pre_cleanup, verify it gets removed
    test_file.write_text("temporary data")
    assert test_file.exists()
    stage_r1.pre_cleanup(filename="ufo_test_challenge_temp.txt")
    assert not test_file.exists()


def test_challenge_stage_r4_and_r5_pre_cleanup():
    """Verify stage_r4 and stage_r5 pre_cleanup handles multiple files gracefully."""
    desktop = get_desktop_dir()
    f4 = desktop / "bankfidelity_report.csv"
    f5 = desktop / "bankfidelity_summary.txt"

    f4.write_text("col1,col2\nval1,val2")
    f5.write_text("account balance: 5000")

    assert f4.exists()
    assert f5.exists()

    stage_r4.pre_cleanup()
    stage_r5.pre_cleanup()

    assert not f4.exists()
    assert not f5.exists()


# ---------------------------------------------------------------------------
# 2. EMPIRICAL CHALLENGE: INVALID STAGE ID INPUTS
# ---------------------------------------------------------------------------

def test_challenge_invalid_stage_id_run_stage():
    """Verify run_stage raises ValueError on unknown stage ID."""
    runner = EvaluationRunner(dry_run=True, log_level="ERROR")

    with pytest.raises(ValueError, match="Unknown evaluation stage 'R99'"):
        asyncio.run(runner.run_stage("R99"))

    with pytest.raises(ValueError, match="Unknown evaluation stage ''"):
        asyncio.run(runner.run_stage(""))


def test_challenge_invalid_stage_id_run_suite():
    """Verify run_suite handles invalid stage lists, mixed lists, and empty stage lists."""
    runner = EvaluationRunner(dry_run=True, log_level="ERROR")

    # Invalid stage in list
    with pytest.raises(ValueError, match="Invalid evaluation stage"):
        asyncio.run(runner.run_suite(stages=["R1", "INVALID_STAGE"]))

    # Case insensitivity & whitespace trimming check
    res = asyncio.run(runner.run_suite(stages=["  r1  ", "R3 "]))
    assert res["total_stages"] == 2
    assert res["passed_stages"] == 2

    # Empty stage list or whitespace-only list
    with pytest.raises(ValueError, match="No valid evaluation stages specified"):
        asyncio.run(runner.run_suite(stages=["  ", ""]))


def test_challenge_request_override_with_multiple_stages():
    """Verify request_override raises ValueError when multiple stages are selected."""
    runner = EvaluationRunner(dry_run=True, log_level="ERROR")
    with pytest.raises(ValueError, match="Request override '--request' can only be specified when running a single stage"):
        asyncio.run(runner.run_suite(stages=["R1", "R2"], request_override="Custom request"))


# ---------------------------------------------------------------------------
# 3. EMPIRICAL CHALLENGE: MISSING LOG DIRECTORIES
# ---------------------------------------------------------------------------

def test_challenge_missing_log_dir_direct_verifier():
    """Verify verify_session_logs returns verified=False when log_dir does not exist."""
    missing_dir = Path(tempfile.gettempdir()) / "non_existent_ufo_log_dir_12345"
    if missing_dir.exists():
        shutil.rmtree(missing_dir)

    res = verify_session_logs(missing_dir, required_patterns=["Notepad"])
    assert res["verified"] is False
    assert "does not exist" in res["error"]


def test_challenge_empty_log_dir():
    """Verify verify_session_logs returns verified=False when log_dir is empty."""
    with tempfile.TemporaryDirectory() as empty_dir:
        res = verify_session_logs(empty_dir, required_patterns=["Notepad"])
        assert res["verified"] is False
        assert "No log files found" in res["error"]


def test_challenge_stage_verifiers_with_missing_log_dir():
    """Stress test stage verifiers R1-R5 when task_log_dir points to missing directory."""
    missing_dir = Path(tempfile.gettempdir()) / "non_existent_ufo_log_dir_67890"

    # Stage R2 live verifier with missing log dir should fail trajectory verification
    res_r2 = stage_r2.verify_r2(task_log_dir=missing_dir, dry_run=False)
    assert res_r2["trajectory_verified"] is False

    # Stage R3 live verifier with missing log dir
    res_r3 = stage_r3.verify_r3(task_log_dir=missing_dir, dry_run=False)
    # Check behavior of R3 with missing log dir
    assert "trajectory_verified" in res_r3

    # Stage R4 live verifier with missing log dir
    res_r4 = stage_r4.verify_r4(task_log_dir=missing_dir, dry_run=False)
    assert "trajectory_verified" in res_r4

    # Stage R5 live verifier with missing log dir
    res_r5 = stage_r5.verify_r5(task_log_dir=missing_dir, dry_run=False)
    assert "trajectory_verified" in res_r5


# ---------------------------------------------------------------------------
# 4. EMPIRICAL CHALLENGE: CONTENT MISMATCH VERIFICATIONS
# ---------------------------------------------------------------------------

def test_challenge_content_mismatch_verification():
    """Empirically challenge content mismatch in verify_file_on_desktop."""
    desktop = get_desktop_dir()
    test_filename = "ufo_challenge_mismatch_test.txt"
    test_filepath = desktop / test_filename

    try:
        # 1. Non-existent file
        if test_filepath.exists():
            test_filepath.unlink()
        res_missing = verify_file_on_desktop(test_filename, expected_content="Hello")
        assert res_missing["verified"] is False
        assert res_missing["exists"] is False
        assert "not found" in res_missing["error"]

        # 2. Content mismatch
        test_filepath.write_text("Actual content: Balance is $1000", encoding="utf-8")
        res_mismatch = verify_file_on_desktop(test_filename, expected_content="Expected Secret Key: 9999")
        assert res_mismatch["verified"] is False
        assert res_mismatch["exists"] is True
        assert res_mismatch["content_matched"] is False
        assert "Content mismatch" in res_mismatch["error"]

        # 3. Exact content match
        res_exact = verify_file_on_desktop(test_filename, expected_content="Balance is $1000")
        assert res_exact["verified"] is True
        assert res_exact["content_matched"] is True

        # 4. Case-insensitive substring match
        res_case = verify_file_on_desktop(test_filename, expected_content="BALANCE IS")
        assert res_case["verified"] is True
        assert res_case["content_matched"] is True

        # 5. Line ending normalization match (\r\n vs \n)
        test_filepath.write_bytes(b"Line 1\r\nLine 2\r\n")
        res_newline = verify_file_on_desktop(test_filename, expected_content="Line 1\nLine 2")
        assert res_newline["verified"] is True

    finally:
        if test_filepath.exists():
            test_filepath.unlink()


def test_challenge_stage_r1_and_r5_content_mismatch_live():
    """Verify stage_r1 and stage_r5 live verifiers fail when desktop file content mismatches."""
    desktop = get_desktop_dir()

    # R1 test with mismatched file content
    r1_file = desktop / stage_r1.DEFAULT_FILENAME
    r1_file.write_text("Wrong message content", encoding="utf-8")
    try:
        res_r1 = stage_r1.verify_r1(dry_run=False)
        assert res_r1["verified"] is False
        assert res_r1["content_matched"] is False
    finally:
        if r1_file.exists():
            r1_file.unlink()

    # R5 test with mismatched summary content
    r5_file = desktop / stage_r5.DEFAULT_SUMMARY_FILENAME
    r5_file.write_text("No expected words here", encoding="utf-8")
    try:
        res_r5 = stage_r5.verify_r5(dry_run=False, expected_keyword="account_balance_unique_key")
        assert res_r5["verified"] is False
        assert res_r5["content_matched"] is False
    finally:
        if r5_file.exists():
            r5_file.unlink()
