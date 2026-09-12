# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Empirical Stress & Challenge Test Suite for M1 Evaluation Suite Defect Resolution.
Targeting:
- Step log deduplication (root + subfolder + summary JSON files)
- Missing log directory handling (trajectory_verified evaluates to False)
- stage_data parameter parsing (str, Path, dict, positional dicts, whitespace)
- Non-directory file path inputs (handling without NotADirectoryError)
- Package export completeness for tests.eval_suite.stages
"""

import json
import pytest
from pathlib import Path
import tempfile
import shutil

from tests.eval_suite.verifiers import (
    resolve_log_path,
    verify_session_logs,
    verify_bankfidelity_process,
    verify_process_running,
)
from tests.eval_suite.stages import (
    verify_r1,
    verify_r2,
    verify_r3,
    verify_r4,
    verify_r5,
    pre_cleanup_r1,
    pre_cleanup_r2,
    pre_cleanup_r3,
    pre_cleanup_r4,
    pre_cleanup_r5,
    STAGE_R3_DEFAULT_REQUEST,
    STAGE_R4_DEFAULT_REPORT_FILENAME,
    STAGE_R5_DEFAULT_SUMMARY_FILENAME,
)


@pytest.fixture
def temp_log_dir():
    """Create a temporary directory for log stress testing."""
    temp_dir = tempfile.mkdtemp(prefix="ufo_challenger_test_")
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


# ============================================================================
# 1. Step Log Deduplication Stress Tests
# ============================================================================

def test_step_log_deduplication_subfolders(temp_log_dir):
    """
    Verify that step JSON files in root and subdirectories are counted exactly once,
    and summary output reports (eval_results_*.json) are ignored.
    """
    root_step = temp_log_dir / "step_1.json"
    root_step.write_text(json.dumps({"step": 1, "status": "SUCCESS", "action": "bankfidelity_click"}))

    sub_dir = temp_log_dir / "sub_session"
    sub_dir.mkdir(parents=True, exist_ok=True)
    sub_step = sub_dir / "step_2.json"
    sub_step.write_text(json.dumps({"step": 2, "status": "SUCCESS", "action": "bankfidelity_navigate"}))

    # Summary result file that MUST be ignored
    summary_file = temp_log_dir / "eval_results_20260813_120000.json"
    summary_file.write_text(json.dumps({"title": "Evaluation Report", "passed_stages": 5}))

    res = verify_session_logs(temp_log_dir, required_patterns=["bankfidelity"])

    assert res["total_steps"] == 2, f"Expected total_steps == 2, got {res['total_steps']}"
    assert res["verified"] is True
    assert "bankfidelity" in res["matched_patterns"]


def test_step_log_deduplication_deep_nesting(temp_log_dir):
    """Verify deep directory structures do not cause duplicate counting."""
    nested_dir = temp_log_dir / "level1" / "level2" / "level3"
    nested_dir.mkdir(parents=True, exist_ok=True)

    (temp_log_dir / "step_1.json").write_text(json.dumps({"step": 1, "status": "SUCCESS", "app": "bankfidelity"}))
    (nested_dir / "step_2.json").write_text(json.dumps({"step": 2, "status": "SUCCESS", "app": "bankfidelity"}))

    res = verify_session_logs(temp_log_dir, required_patterns=["bankfidelity"])
    assert res["total_steps"] == 2
    assert res["verified"] is True


# ============================================================================
# 2. Missing Log Directory Handling Stress Tests
# ============================================================================

def test_missing_log_dir_r1_to_r5():
    """
    Verify that when log_path is passed but does NOT exist on disk,
    trajectory_verified evaluates to False across all stage verifiers (R1..R5).
    """
    missing_dir = Path("C:/ufo_nonexistent_log_dir_challenge_99999")

    # Stage R1
    r1_res = verify_r1(stage_data=missing_dir, dry_run=False)
    assert r1_res["trajectory_verified"] is False
    assert r1_res["verified"] is False

    # Stage R2
    r2_res = verify_r2(stage_data=missing_dir, dry_run=False)
    assert r2_res["trajectory_verified"] is False
    assert r2_res["verified"] is False

    # Stage R3
    r3_res = verify_r3(stage_data=missing_dir, dry_run=False)
    assert r3_res["trajectory_verified"] is False
    assert r3_res["verified"] is False

    # Stage R4
    r4_res = verify_r4(stage_data=missing_dir, dry_run=False)
    assert r4_res["trajectory_verified"] is False
    assert r4_res["verified"] is False

    # Stage R5
    r5_res = verify_r5(stage_data=missing_dir, dry_run=False)
    assert r5_res["trajectory_verified"] is False
    assert r5_res["verified"] is False


def test_missing_log_dir_direct_verifier(temp_log_dir):
    """Verify verify_session_logs returns verified=False and non-zero error message on missing directory."""
    non_existent = temp_log_dir / "does_not_exist"
    res = verify_session_logs(non_existent)
    assert res["verified"] is False
    assert res["total_steps"] == 0
    assert "Log directory does not exist" in res["error"]


# ============================================================================
# 3. Parameter Resolution (stage_data / task_log_dir / output_dir)
# ============================================================================

def test_resolve_log_path_types():
    """Verify resolve_log_path handles string, Path, dict variants, and positional dicts."""
    p_str = "C:/logs/test_str"
    p_path = Path("C:/logs/test_path")

    # String input
    assert resolve_log_path(stage_data=p_str) == Path(p_str)
    # Path input
    assert resolve_log_path(stage_data=p_path) == p_path

    # Dict variants
    assert resolve_log_path(stage_data={"task_log_dir": p_str}) == Path(p_str)
    assert resolve_log_path(stage_data={"log_dir": p_str}) == Path(p_str)
    assert resolve_log_path(stage_data={"output_dir": p_str}) == Path(p_str)

    # Output dir parameter
    assert resolve_log_path(output_dir=p_str) == Path(p_str)

    # Positional dict passed as task_log_dir
    assert resolve_log_path(task_log_dir={"log_dir": p_str}) == Path(p_str)

    # Whitespace and empty inputs
    assert resolve_log_path(stage_data="") is None
    assert resolve_log_path(stage_data="   ") is None
    assert resolve_log_path(stage_data={}) is None
    assert resolve_log_path(stage_data={"task_log_dir": None}) is None


# ============================================================================
# 4. Non-Directory File Input Safety
# ============================================================================

def test_file_as_log_dir_safety(temp_log_dir):
    """
    Verify that passing a regular FILE path (instead of a directory) to verifiers
    returns a clean failure dict without raising NotADirectoryError.
    """
    file_path = temp_log_dir / "not_a_dir.txt"
    file_path.write_text("Just a regular file content.")

    res = verify_session_logs(file_path)
    assert res["verified"] is False
    assert res["total_steps"] == 0
    assert "Log path is not a directory" in res["error"]

    # Test stage verifier with file path
    r3_res = verify_r3(stage_data=file_path, dry_run=False)
    assert r3_res["trajectory_verified"] is False
    assert r3_res["verified"] is False


# ============================================================================
# 5. Export Completeness Verification
# ============================================================================

def test_stages_package_exports():
    """Verify all R1-R5 functions and constants are exported by tests.eval_suite.stages."""
    assert callable(verify_r1)
    assert callable(verify_r2)
    assert callable(verify_r3)
    assert callable(verify_r4)
    assert callable(verify_r5)
    assert callable(pre_cleanup_r1)
    assert callable(pre_cleanup_r2)
    assert callable(pre_cleanup_r3)
    assert callable(pre_cleanup_r4)
    assert callable(pre_cleanup_r5)
    assert isinstance(STAGE_R3_DEFAULT_REQUEST, str)
    assert isinstance(STAGE_R4_DEFAULT_REPORT_FILENAME, str)
    assert isinstance(STAGE_R5_DEFAULT_SUMMARY_FILENAME, str)
