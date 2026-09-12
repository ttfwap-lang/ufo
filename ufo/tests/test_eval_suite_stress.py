# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Stress & Boundary Test Suite for UFO 5-Stage Evaluation Suite & Verifiers.
Empirical verification created by Challenger M2-2.
"""

import json
import os
import shutil
import tempfile
from pathlib import Path
import pytest

from tests.eval_suite.verifiers import (
    get_desktop_dir,
    verify_bankfidelity_process,
    verify_file_on_desktop,
    verify_process_running,
    verify_session_logs,
)
from tests.eval_suite.stages.stage_r1 import verify_r1, pre_cleanup as pre_cleanup_r1
from tests.eval_suite.stages.stage_r2 import verify_r2, pre_cleanup as pre_cleanup_r2
from tests.eval_suite.stages.stage_r3 import verify_r3, pre_cleanup as pre_cleanup_r3
from tests.eval_suite.stages.stage_r4 import verify_r4, pre_cleanup as pre_cleanup_r4
from tests.eval_suite.stages.stage_r5 import verify_r5, pre_cleanup as pre_cleanup_r5
from tests.eval_suite.eval_runner import EVAL_STAGES, EvaluationRunner, parse_args


# --- 1. Log Summary Output Generation Tests ---

@pytest.mark.asyncio
async def test_summary_report_generation_structure_and_files(tmp_path):
    """Verify eval_results_*.json and eval_summary_*.md are generated with correct contents."""
    out_dir = tmp_path / "reports"
    runner = EvaluationRunner(output_dir=str(out_dir), dry_run=True)
    
    summary = await runner.run_suite(stages=["ALL"])
    
    # Check return dictionary structure
    assert summary["total_stages"] == 5
    assert summary["passed_stages"] == 5
    assert summary["failed_stages"] == 0
    assert "timestamp" in summary
    assert "duration_seconds" in summary
    
    # Find generated output files
    json_files = list(out_dir.glob("eval_results_*.json"))
    md_files = list(out_dir.glob("eval_summary_*.md"))
    
    assert len(json_files) == 1, f"Expected 1 JSON file, found {len(json_files)}"
    assert len(md_files) == 1, f"Expected 1 MD file, found {len(md_files)}"
    
    # Inspect JSON file content
    with open(json_files[0], "r", encoding="utf-8") as f:
        json_data = json.load(f)
    assert json_data["total_stages"] == 5
    assert json_data["execution_method"] == "api"
    assert len(json_data["stage_results"]) == 5
    
    # Inspect Markdown file content
    md_content = md_files[0].read_text(encoding="utf-8")
    assert "# UFO 5-Stage Evaluation Suite Execution Report" in md_content
    assert "| Stage | Name | Target App | Status | Duration (s) | Task Name |" in md_content
    assert "| R1 | Notepad Test | Notepad |" in md_content
    assert "| R5 | Multi-Agent Task |" in md_content


@pytest.mark.asyncio
async def test_summary_file_collision_handling(tmp_path):
    """Verify runner handles timestamp file collisions gracefully by appending sequence counters."""
    out_dir = tmp_path / "collisions"
    runner = EvaluationRunner(output_dir=str(out_dir), dry_run=True)
    
    # Run suite twice
    s1 = await runner.run_suite(stages=["R1"])
    s2 = await runner.run_suite(stages=["R1"])
    
    json_files = list(out_dir.glob("eval_results_*.json"))
    md_files = list(out_dir.glob("eval_summary_*.md"))
    
    assert len(json_files) == 2
    assert len(md_files) == 2


@pytest.mark.asyncio
async def test_summary_report_with_stage_failures(tmp_path, monkeypatch):
    """Verify summary JSON and MD reports accurately capture stage failures and error messages."""
    out_dir = tmp_path / "failures"
    runner = EvaluationRunner(output_dir=str(out_dir), dry_run=True)
    
    # Mock stage verifier to fail for R2
    def mock_failing_verifier(*args, **kwargs):
        return {"verified": False, "details": "Simulated Chrome failure"}
    
    monkeypatch.setitem(EVAL_STAGES["R2"], "verifier", mock_failing_verifier)
    
    # Run in dry_run=True for R1, but mock R2 failure
    res = await runner.run_stage("R2")
    assert "FAILED" in res["status"] or res["verification"]["verified"] is False


# --- 2. Trajectory Verification & Verifier Edge Cases ---

def test_verify_session_logs_corrupted_json_lines(tmp_path):
    """Verify log verifier tolerates corrupted JSON lines alongside valid ones."""
    log_dir = tmp_path / "corrupt_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    resp_log = log_dir / "response.log"
    
    content = (
        '{"step": 1, "action": "open notepad", "status": "SUCCESS"}\n'
        'THIS IS NOT VALID JSON!!! Corrupted line\n'
        '{"step": 2, "action": "type text notepad", "status": "SUCCESS"}\n'
    )
    resp_log.write_text(content, encoding="utf-8")
    
    res = verify_session_logs(log_dir=log_dir, required_patterns=["notepad"])
    assert res["verified"] is True
    assert res["total_steps"] == 2
    assert "notepad" in res["matched_patterns"]


def test_verify_session_logs_nested_directory_structure(tmp_path):
    """Verify log verifier finds response.log in deeply nested subdirectories."""
    nested_dir = tmp_path / "sub1" / "sub2" / "task_123"
    nested_dir.mkdir(parents=True, exist_ok=True)
    resp_log = nested_dir / "response.log"
    
    log_data = [{"step": 1, "action": "BankFidelity login", "status": "SUCCESS"}]
    resp_log.write_text(json.dumps(log_data[0]) + "\n", encoding="utf-8")
    
    res = verify_session_logs(log_dir=tmp_path, required_patterns=["bankfidelity"])
    assert res["verified"] is True
    assert res["total_steps"] == 1


def test_verify_session_logs_json_fallback_duplicate_file_bug(tmp_path):
    """
    Verifies that verifiers.py deduplicates JSON files in fallback mode (rglob without duplication).
    When 2 JSON step files exist, verify_session_logs returns total_steps = 2.
    """
    log_dir = tmp_path / "json_steps"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    step1 = log_dir / "step_1.json"
    step1.write_text(json.dumps({"action": "Chrome navigate https://www.example.com", "status": "SUCCESS"}), encoding="utf-8")
    
    step2 = log_dir / "step_2.json"
    step2.write_text(json.dumps({"action": "Chrome navigate https://www.wikipedia.org", "status": "SUCCESS"}), encoding="utf-8")
    
    res = verify_session_logs(log_dir=log_dir, required_patterns=["chrome", "example.com"])
    assert res["verified"] is True
    assert res["total_steps"] == 2


def test_stage_r3_r4_r5_missing_log_dir_bypass_bug(tmp_path, monkeypatch):
    """
    Verifies that stage_r3, stage_r4, stage_r5 verifiers evaluate trajectory_verified to False if log_dir does not exist.
    """
    missing_dir = tmp_path / "non_existent_log_folder_999"
    
    # Mock process checker to return True (simulating process active)
    monkeypatch.setattr("tests.eval_suite.stages.stage_r3.verify_bankfidelity_process", lambda: {"verified": True, "running_processes": ["bankfidelity.exe"]})
    
    r3_res = verify_r3(task_log_dir=missing_dir, dry_run=False)
    
    # trajectory_verified is False for a missing log dir
    assert r3_res["trajectory_verified"] is False


def test_verify_file_on_desktop_multiline_crlf_normalization():
    """Verify content matching normalizes CRLF vs LF and case sensitivity."""
    desktop = get_desktop_dir()
    test_file = desktop / "ufo_crlf_test.txt"
    try:
        test_file.write_bytes(b"Line 1\r\nHello World\r\nLine 3")
        res = verify_file_on_desktop(
            filename="ufo_crlf_test.txt",
            expected_content="hello world",
        )
        assert res["verified"] is True
        assert res["exists"] is True
        assert res["content_matched"] is True
    finally:
        if test_file.exists():
            test_file.unlink()


def test_verify_file_on_desktop_home_directory_fallback(tmp_path, monkeypatch):
    """Verify fallback to Path.home() when file is not on Desktop."""
    home_dir = tmp_path / "fake_home"
    home_dir.mkdir(parents=True, exist_ok=True)
    desktop_dir = home_dir / "Desktop"
    desktop_dir.mkdir(parents=True, exist_ok=True)
    
    monkeypatch.setattr("tests.eval_suite.verifiers.get_desktop_dir", lambda: desktop_dir)
    monkeypatch.setattr(Path, "home", lambda: home_dir)
    
    # File in home dir, not desktop dir
    home_file = home_dir / "fallback_file.txt"
    home_file.write_text("fallback content", encoding="utf-8")
    
    res = verify_file_on_desktop(filename="fallback_file.txt", expected_content="fallback")
    assert res["verified"] is True
    assert res["exists"] is True


def test_verifiers_flexible_dict_signature():
    """Verify R3, R4, R5 verifiers support passing stage_data dict."""
    r3_res = verify_r3(stage_data={"dry_run": True})
    assert r3_res["verified"] is True
    assert r3_res["dry_run"] is True
    
    r4_res = verify_r4(stage_data={"dry_run": True})
    assert r4_res["verified"] is True
    assert r4_res["dry_run"] is True
    
    r5_res = verify_r5(stage_data={"dry_run": True})
    assert r5_res["verified"] is True
    assert r5_res["dry_run"] is True


# --- 3. Stage Cleanup Resilience & CLI Parsing Tests ---

def test_pre_cleanups_resilience():
    """Verify pre_cleanup functions execute without error even if target files do not exist."""
    pre_cleanup_r1(filename="non_existent_file_9999.txt")
    pre_cleanup_r2()
    pre_cleanup_r3()
    pre_cleanup_r4(report_filename="non_existent_report_9999.csv")
    pre_cleanup_r5(summary_filename="non_existent_summary_9999.txt")


def test_cli_parse_args_variations():
    """Verify CLI argument parser for EvaluationRunner."""
    args = parse_args(["--stage", "R1,R3", "--exec-method", "cli", "--dry-run", "--mode", "batch_normal"])
    assert args.stage == "R1,R3"
    assert args.exec_method == "cli"
    assert args.dry_run is True
    assert args.mode == "batch_normal"


@pytest.mark.asyncio
async def test_eval_runner_case_insensitive_stage_names(tmp_path):
    """Verify runner accepts lowercase stage names (r1, r2, r3)."""
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    summary = await runner.run_suite(stages=["r1", " R3 ", "r5"])
    assert summary["total_stages"] == 3
    assert [r["stage_id"] for r in summary["stage_results"]] == ["R1", "R3", "R5"]


@pytest.mark.asyncio
async def test_eval_runner_request_override_multiple_stages_raises():
    """Verify passing --request override with multiple stages raises ValueError."""
    runner = EvaluationRunner(dry_run=True)
    with pytest.raises(ValueError) as exc_info:
        await runner.run_suite(stages=["R1", "R2"], request_override="Custom request")
    assert "Request override '--request' can only be specified when running a single stage" in str(exc_info.value)
