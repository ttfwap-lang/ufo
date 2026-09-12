# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Pytest Test Suite for UFO 5-Stage E2E GUI Evaluation Suite (R1-R5).
Verifies stage handlers (R1-R5), registry configurations, verifiers, and EvaluationRunner integration.
"""

import json
import os
from pathlib import Path
import pytest

from tests.eval_suite.verifiers import (
    get_desktop_dir,
    verify_bankfidelity_process,
    verify_file_on_desktop,
    verify_process_running,
    verify_session_logs,
)
from tests.eval_suite.stages.stage_r1 import (
    DEFAULT_FILENAME as R1_DEFAULT_FILENAME,
    DEFAULT_MESSAGE as R1_DEFAULT_MESSAGE,
    get_stage_config as get_config_r1,
    pre_cleanup as pre_cleanup_r1,
    verify_r1,
)
from tests.eval_suite.stages.stage_r2 import (
    DEFAULT_INITIAL_URL as R2_DEFAULT_INITIAL_URL,
    DEFAULT_SECOND_URL as R2_DEFAULT_SECOND_URL,
    get_stage_config as get_config_r2,
    pre_cleanup as pre_cleanup_r2,
    verify_r2,
)
from tests.eval_suite.stages.stage_r3 import (
    DEFAULT_REQUEST as R3_DEFAULT_REQUEST,
    get_stage_config as get_config_r3,
    pre_cleanup as pre_cleanup_r3,
    verify_r3,
)
from tests.eval_suite.stages.stage_r4 import (
    DEFAULT_REPORT_FILENAME as R4_DEFAULT_REPORT_FILENAME,
    DEFAULT_REQUEST as R4_DEFAULT_REQUEST,
    get_stage_config as get_config_r4,
    pre_cleanup as pre_cleanup_r4,
    verify_r4,
)
from tests.eval_suite.stages.stage_r5 import (
    DEFAULT_REQUEST as R5_DEFAULT_REQUEST,
    DEFAULT_SUMMARY_FILENAME as R5_DEFAULT_SUMMARY_FILENAME,
    get_stage_config as get_config_r5,
    pre_cleanup as pre_cleanup_r5,
    verify_r5,
)
from tests.eval_suite.eval_runner import EVAL_STAGES, EvaluationRunner


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


def test_verify_bankfidelity_process():
    """Verify BankFidelity process checker structure."""
    res = verify_bankfidelity_process()
    assert isinstance(res, dict)
    assert "verified" in res
    assert "running_processes" in res


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


def test_verify_session_logs_deduplication(tmp_path):
    """Verify verify_session_logs deduplicates top-level JSON files so step count is accurate."""
    log_dir = tmp_path / "dedup_json_log"
    log_dir.mkdir(parents=True, exist_ok=True)

    step1 = log_dir / "step_1.json"
    step2 = log_dir / "step_2.json"
    sub_dir = log_dir / "subdir"
    sub_dir.mkdir(parents=True, exist_ok=True)
    step3 = sub_dir / "step_3.json"

    step1.write_text(json.dumps({"step": 1, "action": "Open App", "status": "SUCCESS"}), encoding="utf-8")
    step2.write_text(json.dumps({"step": 2, "action": "Perform Action", "status": "SUCCESS"}), encoding="utf-8")
    step3.write_text(json.dumps({"step": 3, "action": "Close App", "status": "SUCCESS"}), encoding="utf-8")

    res = verify_session_logs(log_dir=log_dir)
    assert res["verified"] is True
    assert res["total_steps"] == 3


@pytest.mark.parametrize("stage_id, verifier_fn", [
    ("R1", verify_r1),
    ("R2", verify_r2),
    ("R3", verify_r3),
    ("R4", verify_r4),
    ("R5", verify_r5),
])
def test_stage_verifiers_missing_log_dir(tmp_path, stage_id, verifier_fn):
    """Verify stage verifiers fail with trajectory_verified=False when task_log_dir is missing."""
    non_existent_log_dir = tmp_path / f"non_existent_{stage_id}_logs"
    res = verifier_fn(task_log_dir=non_existent_log_dir, dry_run=False)
    assert res["verified"] is False
    assert res["trajectory_verified"] is False


# --- Stage R1 Tests ---

def test_stage_r1_config():
    """Test Stage R1 configuration module."""
    config = get_config_r1()
    assert config["id"] == "R1"
    assert config["name"] == "Notepad Test"
    assert config["target_app"] == "Notepad"
    assert callable(config["pre_cleanup"])
    assert callable(config["verifier"])


def test_stage_r1_pre_cleanup():
    """Test Stage R1 pre-cleanup function."""
    desktop = get_desktop_dir()
    test_file = desktop / R1_DEFAULT_FILENAME
    test_file.write_text("stale test content", encoding="utf-8")

    assert test_file.exists()
    pre_cleanup_r1(filename=R1_DEFAULT_FILENAME)
    assert not test_file.exists()


def test_stage_r1_verify_dry_run():
    """Test Stage R1 verifier in dry-run mode."""
    res = verify_r1(dry_run=True)
    assert res["verified"] is True
    assert res["stage_id"] == "R1"
    assert res["dry_run"] is True
    assert res["file_exists"] is True
    assert res["content_matched"] is True


def test_stage_r1_verify_live(tmp_path):
    """Test Stage R1 verifier with live file on Desktop."""
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

def test_stage_r2_config():
    """Test Stage R2 configuration module."""
    config = get_config_r2()
    assert config["id"] == "R2"
    assert config["name"] == "Chrome Navigation"
    assert config["target_app"] == "Google Chrome"
    assert callable(config["pre_cleanup"])
    assert callable(config["verifier"])
    pre_cleanup_r2()  # should run cleanly


def test_stage_r2_verify_dry_run():
    """Test Stage R2 verifier in dry-run mode."""
    res = verify_r2(dry_run=True)
    assert res["verified"] is True
    assert res["stage_id"] == "R2"
    assert res["dry_run"] is True
    assert res["chrome_process_detected"] is True
    assert res["trajectory_verified"] is True


def test_stage_r2_mock_logs(tmp_path):
    """Test Stage R2 verifier with mock log directory."""
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


# --- Stage R3 Tests ---

def test_stage_r3_config():
    """Test Stage R3 configuration module."""
    config = get_config_r3()
    assert config["id"] == "R3"
    assert config["name"] == "Basic BankFidelity Task"
    assert config["target_app"] == "BankFidelity"
    assert config["request"] == R3_DEFAULT_REQUEST
    assert callable(config["pre_cleanup"])
    assert callable(config["verifier"])
    pre_cleanup_r3()  # should run cleanly


def test_stage_r3_verify_dry_run():
    """Test Stage R3 verifier in dry-run mode."""
    res = verify_r3(dry_run=True)
    assert res["verified"] is True
    assert res["stage_id"] == "R3"
    assert res["dry_run"] is True
    assert res["process_detected"] is True
    assert res["trajectory_verified"] is True


def test_stage_r3_mock_logs(tmp_path):
    """Test Stage R3 verifier with mock log directory."""
    log_dir = tmp_path / "mock_bankfidelity_r3"
    log_dir.mkdir(parents=True, exist_ok=True)
    resp_log = log_dir / "response.log"

    log_records = [
        {"step": 1, "action": "Open BankFidelity app", "status": "SUCCESS"},
        {"step": 2, "action": "verify UI elements", "status": "SUCCESS"},
    ]
    with open(resp_log, "w", encoding="utf-8") as f:
        for rec in log_records:
            f.write(json.dumps(rec) + "\n")

    res = verify_r3(task_log_dir=log_dir, dry_run=True)
    assert res["verified"] is True
    assert res["stage_id"] == "R3"


# --- Stage R4 Tests ---

def test_stage_r4_config():
    """Test Stage R4 configuration module."""
    config = get_config_r4()
    assert config["id"] == "R4"
    assert config["name"] == "Complex BankFidelity Task"
    assert config["target_app"] == "BankFidelity"
    assert config["request"] == R4_DEFAULT_REQUEST
    assert callable(config["pre_cleanup"])
    assert callable(config["verifier"])


def test_stage_r4_pre_cleanup():
    """Test Stage R4 pre-cleanup function."""
    desktop = get_desktop_dir()
    test_file = desktop / R4_DEFAULT_REPORT_FILENAME
    test_file.write_text("dummy report content", encoding="utf-8")

    assert test_file.exists()
    pre_cleanup_r4(report_filename=R4_DEFAULT_REPORT_FILENAME)
    assert not test_file.exists()


def test_stage_r4_verify_dry_run():
    """Test Stage R4 verifier in dry-run mode."""
    res = verify_r4(dry_run=True)
    assert res["verified"] is True
    assert res["stage_id"] == "R4"
    assert res["dry_run"] is True
    assert res["process_detected"] is True
    assert res["trajectory_verified"] is True
    assert res["report_verified"] is True


def test_stage_r4_mock_logs(tmp_path):
    """Test Stage R4 verifier with mock log directory."""
    log_dir = tmp_path / "mock_bankfidelity_r4"
    log_dir.mkdir(parents=True, exist_ok=True)
    resp_log = log_dir / "response.log"

    log_records = [
        {"step": 1, "action": "Open BankFidelity app", "status": "SUCCESS"},
        {"step": 2, "action": "filter transactions 30 days", "status": "SUCCESS"},
        {"step": 3, "action": f"export_report {R4_DEFAULT_REPORT_FILENAME}", "status": "SUCCESS"},
    ]
    with open(resp_log, "w", encoding="utf-8") as f:
        for rec in log_records:
            f.write(json.dumps(rec) + "\n")

    res = verify_r4(task_log_dir=log_dir, dry_run=True)
    assert res["verified"] is True
    assert res["stage_id"] == "R4"


# --- Stage R5 Tests ---

def test_stage_r5_config():
    """Test Stage R5 configuration module."""
    config = get_config_r5()
    assert config["id"] == "R5"
    assert config["name"] == "Multi-Agent Task"
    assert config["target_app"] == "Multi-App (BankFidelity + Notepad)"
    assert config["request"] == R5_DEFAULT_REQUEST
    assert callable(config["pre_cleanup"])
    assert callable(config["verifier"])


def test_stage_r5_pre_cleanup():
    """Test Stage R5 pre-cleanup function."""
    desktop = get_desktop_dir()
    test_file = desktop / R5_DEFAULT_SUMMARY_FILENAME
    test_file.write_text("dummy summary content", encoding="utf-8")

    assert test_file.exists()
    pre_cleanup_r5(summary_filename=R5_DEFAULT_SUMMARY_FILENAME)
    assert not test_file.exists()


def test_stage_r5_verify_dry_run():
    """Test Stage R5 verifier in dry-run mode."""
    res = verify_r5(dry_run=True)
    assert res["verified"] is True
    assert res["stage_id"] == "R5"
    assert res["dry_run"] is True
    assert res["file_exists"] is True
    assert res["content_matched"] is True
    assert res["trajectory_verified"] is True


def test_stage_r5_verify_live(tmp_path):
    """Test Stage R5 verifier with live file on Desktop."""
    desktop = get_desktop_dir()
    test_file = desktop / R5_DEFAULT_SUMMARY_FILENAME
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "step_1.json").write_text(json.dumps({"action": "bankfidelity balance check", "status": "SUCCESS"}), encoding="utf-8")
    try:
        test_file.write_text("BankFidelity Account Balance: $12,345.67", encoding="utf-8")
        res = verify_r5(task_log_dir=log_dir, dry_run=False, summary_filename=R5_DEFAULT_SUMMARY_FILENAME, expected_keyword="balance")
        assert res["verified"] is True
        assert res["file_exists"] is True
        assert res["content_matched"] is True
    finally:
        if test_file.exists():
            test_file.unlink()


# --- Registry & EvaluationRunner Integration Tests ---

def test_eval_stages_registry():
    """Verify EVAL_STAGES registry contains complete mappings for R1 to R5."""
    expected_stages = ["R1", "R2", "R3", "R4", "R5"]
    assert set(EVAL_STAGES.keys()) == set(expected_stages)
    for stage_id in expected_stages:
        stage = EVAL_STAGES[stage_id]
        assert stage["id"] == stage_id
        assert "name" in stage
        assert "target_app" in stage
        assert "default_request" in stage or "request" in stage
        assert "pre_cleanup" in stage
        assert "verifier" in stage


@pytest.mark.asyncio
async def test_eval_runner_individual_stages_dry_run(tmp_path):
    """Test running each stage (R1-R5) through EvaluationRunner in dry-run mode."""
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    for stage_id in ["R1", "R2", "R3", "R4", "R5"]:
        res = await runner.run_stage(stage_id)
        assert res["stage_id"] == stage_id
        assert res["status"] == "SUCCESS (DRY_RUN)"
        assert "verification" in res
        assert res["verification"]["verified"] is True
        assert res["verification"]["stage_id"] == stage_id


@pytest.mark.asyncio
async def test_eval_runner_full_suite_dry_run(tmp_path):
    """Test running all 5 stages together via run_suite in dry-run mode."""
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    summary = await runner.run_suite(stages=["ALL"])
    assert summary["total_stages"] == 5
    assert summary["passed_stages"] == 5
    assert summary["failed_stages"] == 0
    assert len(summary["stage_results"]) == 5

    stage_ids = [r["stage_id"] for r in summary["stage_results"]]
    assert stage_ids == ["R1", "R2", "R3", "R4", "R5"]


@pytest.mark.asyncio
async def test_eval_runner_selected_stages_dry_run(tmp_path):
    """Test running a subset of stages (R3, R4, R5) via run_suite in dry-run mode."""
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    summary = await runner.run_suite(stages=["R3", "R4", "R5"])
    assert summary["total_stages"] == 3
    assert summary["passed_stages"] == 3
    assert summary["failed_stages"] == 0
    stage_ids = [r["stage_id"] for r in summary["stage_results"]]
    assert stage_ids == ["R3", "R4", "R5"]


@pytest.mark.asyncio
async def test_eval_runner_invalid_stage_raises_error(tmp_path):
    """Test that specifying an invalid stage ID raises ValueError."""
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    with pytest.raises(ValueError):
        await runner.run_stage("INVALID_STAGE_ID")

    with pytest.raises(ValueError):
        await runner.run_suite(stages=["R1", "NON_EXISTENT"])


# ============================================================================
# Area 1 — New Tests: Stage R1 (Notepad) — 6 additional tests
# ============================================================================


def test_stage_r1_utf8_bom_file(tmp_path):
    """Verify BOM-encoded file content matching works correctly."""
    desktop = get_desktop_dir()
    test_file = desktop / "ufo_test_bom_check.txt"
    bom_content = "\ufeff" + R1_DEFAULT_MESSAGE
    try:
        test_file.write_bytes(bom_content.encode("utf-8-sig"))
        res = verify_file_on_desktop(
            filename="ufo_test_bom_check.txt",
            expected_content=R1_DEFAULT_MESSAGE,
        )
        assert res["verified"] is True
        assert res["exists"] is True
        assert res["content_matched"] is True
    finally:
        if test_file.exists():
            test_file.unlink()


def test_stage_r1_stale_home_dir_cleanup():
    """Verify pre_cleanup removes file from Path.home() fallback location."""
    home_file = Path.home() / R1_DEFAULT_FILENAME
    try:
        home_file.write_text("stale home dir content", encoding="utf-8")
        assert home_file.exists()
        pre_cleanup_r1(filename=R1_DEFAULT_FILENAME)
        assert not home_file.exists()
    finally:
        if home_file.exists():
            home_file.unlink()


def test_stage_r1_verify_content_case_insensitive():
    """Content matching is case-insensitive (substring check)."""
    desktop = get_desktop_dir()
    test_file = desktop / "ufo_test_case_check.txt"
    try:
        test_file.write_text("HELLO FROM UFO 5-STAGE EVALUATION SUITE!", encoding="utf-8")
        res = verify_file_on_desktop(
            filename="ufo_test_case_check.txt",
            expected_content="hello from ufo 5-stage evaluation suite!",
        )
        assert res["verified"] is True
        assert res["content_matched"] is True
    finally:
        if test_file.exists():
            test_file.unlink()


def test_stage_r1_verify_empty_file():
    """Empty file on Desktop should result in content_matched=False when expected content is non-empty."""
    desktop = get_desktop_dir()
    test_file = desktop / "ufo_test_empty_check.txt"
    try:
        test_file.write_text("", encoding="utf-8")
        res = verify_file_on_desktop(
            filename="ufo_test_empty_check.txt",
            expected_content=R1_DEFAULT_MESSAGE,
        )
        assert res["exists"] is True
        assert res["content_matched"] is False
        assert res["verified"] is False
    finally:
        if test_file.exists():
            test_file.unlink()


def test_stage_r1_dry_run_via_dict():
    """Verify dry_run triggered via stage_data dict with dry_run=True."""
    res = verify_r1(stage_data={"dry_run": True})
    assert res["verified"] is True
    assert res["dry_run"] is True
    assert res["stage_id"] == "R1"


def test_stage_r1_request_text_contains_defaults():
    """DEFAULT_REQUEST string includes both DEFAULT_MESSAGE and DEFAULT_FILENAME."""
    from tests.eval_suite.stages.stage_r1 import DEFAULT_REQUEST
    assert R1_DEFAULT_MESSAGE in DEFAULT_REQUEST
    assert R1_DEFAULT_FILENAME in DEFAULT_REQUEST


# ============================================================================
# Area 1 — New Tests: Stage R2 (Chrome) — 7 additional tests
# ============================================================================


def test_stage_r2_verify_missing_url_pattern(tmp_path):
    """Missing URL in logs should cause trajectory_verified=False."""
    log_dir = tmp_path / "r2_missing_url"
    log_dir.mkdir(parents=True, exist_ok=True)
    resp_log = log_dir / "response.log"
    # Only has Chrome and initial URL, missing second URL
    log_records = [
        {"step": 1, "action": "Open chrome", "status": "SUCCESS"},
        {"step": 2, "action": f"navigate {R2_DEFAULT_INITIAL_URL}", "status": "SUCCESS"},
    ]
    with open(resp_log, "w", encoding="utf-8") as f:
        for rec in log_records:
            f.write(json.dumps(rec) + "\n")

    res = verify_r2(task_log_dir=log_dir, dry_run=False)
    assert res["trajectory_verified"] is False


def test_stage_r2_pre_cleanup_idempotent():
    """pre_cleanup runs safely multiple times without error."""
    pre_cleanup_r2()
    pre_cleanup_r2()  # Second call should not crash


def test_stage_r2_verify_dry_run_via_stage_data():
    """dry_run triggered via stage_data dict."""
    res = verify_r2(stage_data={"dry_run": True})
    assert res["verified"] is True
    assert res["dry_run"] is True
    assert res["stage_id"] == "R2"


def test_stage_r2_mock_partial_url_match(tmp_path):
    """Only one URL matched in trajectory should leave trajectory_verified=False."""
    log_dir = tmp_path / "r2_partial"
    log_dir.mkdir(parents=True, exist_ok=True)
    resp_log = log_dir / "response.log"
    log_records = [
        {"step": 1, "action": "Open chrome browser", "status": "SUCCESS"},
        {"step": 2, "action": f"navigate {R2_DEFAULT_INITIAL_URL}", "status": "SUCCESS"},
        # Missing second URL navigation
    ]
    with open(resp_log, "w", encoding="utf-8") as f:
        for rec in log_records:
            f.write(json.dumps(rec) + "\n")

    res = verify_r2(task_log_dir=log_dir, dry_run=False)
    assert res["trajectory_verified"] is False


def test_stage_r2_config_request_contains_urls():
    """DEFAULT_REQUEST includes both initial and second URLs."""
    from tests.eval_suite.stages.stage_r2 import DEFAULT_REQUEST
    assert R2_DEFAULT_INITIAL_URL in DEFAULT_REQUEST
    assert R2_DEFAULT_SECOND_URL in DEFAULT_REQUEST


def test_stage_r2_log_dir_not_directory(tmp_path):
    """verify_r2 with log_dir pointing to a file instead of directory fails gracefully."""
    fake_file = tmp_path / "not_a_dir.txt"
    fake_file.write_text("not a directory", encoding="utf-8")
    res = verify_session_logs(log_dir=fake_file)
    assert res["verified"] is False
    assert "not a directory" in res["error"]


def test_stage_r2_verify_no_chrome_running_structure():
    """Verify process check structure for chrome detection."""
    res = verify_process_running(["non_existent_chrome_variant_9999.exe"])
    assert res["verified"] is False
    assert isinstance(res["running_processes"], list)
    assert res["error"] is not None


# ============================================================================
# Area 1 — New Tests: Stage R3 (BankFidelity Basic) — 7 additional tests
# ============================================================================


def test_stage_r3_verify_with_mock_trajectory(tmp_path):
    """Live verification with mock trajectory logs (non-dry-run path)."""
    log_dir = tmp_path / "r3_mock_traj"
    log_dir.mkdir(parents=True, exist_ok=True)
    resp_log = log_dir / "response.log"
    log_records = [
        {"step": 1, "action": "Open BankFidelity app", "status": "SUCCESS"},
        {"step": 2, "action": "verify bankfidelity UI elements", "status": "SUCCESS"},
    ]
    with open(resp_log, "w", encoding="utf-8") as f:
        for rec in log_records:
            f.write(json.dumps(rec) + "\n")

    res = verify_r3(task_log_dir=log_dir, dry_run=False)
    assert res["trajectory_verified"] is True
    assert res["stage_id"] == "R3"


def test_stage_r3_pre_cleanup_exe_not_found():
    """pre_cleanup when BankFidelity exe doesn't exist should not crash."""
    # This test relies on the fact that pre_cleanup handles missing exe gracefully
    pre_cleanup_r3()  # Should not raise


def test_stage_r3_verify_via_output_dir(tmp_path):
    """resolve_log_path resolves via output_dir parameter."""
    from tests.eval_suite.verifiers import resolve_log_path
    result = resolve_log_path(output_dir=tmp_path)
    assert result == tmp_path


def test_stage_r3_verify_dry_run_via_task_log_dir_dict():
    """dry_run triggered when task_log_dir passed as dict with dry_run key."""
    res = verify_r3(task_log_dir={"dry_run": True})
    assert res["verified"] is True
    assert res["dry_run"] is True


def test_stage_r3_request_contains_exe_path():
    """DEFAULT_REQUEST includes BankFidelity executable path."""
    assert "BankFidelity_Stable.exe" in R3_DEFAULT_REQUEST


def test_stage_r3_mock_error_trajectory(tmp_path):
    """Trajectory with ERROR status should cause verified=False."""
    log_dir = tmp_path / "r3_error_traj"
    log_dir.mkdir(parents=True, exist_ok=True)
    resp_log = log_dir / "response.log"
    log_records = [
        {"step": 1, "action": "Open BankFidelity app", "status": "SUCCESS"},
        {"step": 2, "action": "verify bankfidelity UI", "status": "ERROR", "last_error": "Window not found"},
    ]
    with open(resp_log, "w", encoding="utf-8") as f:
        for rec in log_records:
            f.write(json.dumps(rec) + "\n")

    res = verify_session_logs(log_dir=log_dir, required_patterns=["bankfidelity"])
    assert res["verified"] is False
    assert len(res["errors"]) == 1


def test_stage_r3_verify_no_process_structure():
    """When BankFidelity not running, process detection returns structured result."""
    res = verify_bankfidelity_process(process_names=["non_existent_bankfidelity_9999.exe"])
    assert res["verified"] is False
    assert isinstance(res["running_processes"], list)


# ============================================================================
# Area 1 — New Tests: Stage R4 (BankFidelity Complex) — 6 additional tests
# ============================================================================


def test_stage_r4_cleanup_multiple_filenames():
    """pre_cleanup removes all candidate CSV filenames from Desktop."""
    desktop = get_desktop_dir()
    candidates = [R4_DEFAULT_REPORT_FILENAME, "transaction_history.csv", "bankfidelity_export.csv"]
    created = []
    try:
        for fname in candidates:
            fpath = desktop / fname
            fpath.write_text("test csv content", encoding="utf-8")
            created.append(fpath)

        pre_cleanup_r4(report_filename=R4_DEFAULT_REPORT_FILENAME)

        for fpath in created:
            assert not fpath.exists(), f"{fpath.name} should have been removed by pre_cleanup"
    finally:
        for fpath in created:
            if fpath.exists():
                fpath.unlink()


def test_stage_r4_verify_report_exists(tmp_path):
    """Live CSV file on Desktop should result in report_verified=True."""
    desktop = get_desktop_dir()
    test_csv = desktop / R4_DEFAULT_REPORT_FILENAME
    log_dir = tmp_path / "r4_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "step_1.json").write_text(
        json.dumps({"action": "bankfidelity export", "status": "SUCCESS"}), encoding="utf-8"
    )
    try:
        test_csv.write_text("date,amount\n2026-01-01,100.00\n", encoding="utf-8")
        res = verify_r4(task_log_dir=log_dir, dry_run=False)
        assert res["report_verified"] is True
    finally:
        if test_csv.exists():
            test_csv.unlink()


def test_stage_r4_verify_report_empty_file():
    """Empty CSV on Desktop should result in report_verified=False."""
    desktop = get_desktop_dir()
    test_csv = desktop / R4_DEFAULT_REPORT_FILENAME
    try:
        test_csv.write_text("", encoding="utf-8")
        res = verify_r4(dry_run=False)
        assert res["report_verified"] is False
    finally:
        if test_csv.exists():
            test_csv.unlink()


def test_stage_r4_verify_fallback_filename():
    """Report found via fallback filename 'transaction_history.csv' should pass."""
    desktop = get_desktop_dir()
    fallback_csv = desktop / "transaction_history.csv"
    try:
        fallback_csv.write_text("date,amount\n2026-01-01,50.00\n", encoding="utf-8")
        res = verify_r4(dry_run=False)
        assert res["report_verified"] is True
        assert "transaction_history.csv" in res.get("details", "")
    finally:
        if fallback_csv.exists():
            fallback_csv.unlink()


def test_stage_r4_config_has_required_fields():
    """Stage R4 config has all required fields including verifier and pre_cleanup."""
    config = get_config_r4()
    assert config["id"] == "R4"
    assert "timeout" not in config or isinstance(config.get("timeout"), (int, float))
    assert callable(config["verifier"])
    assert callable(config["pre_cleanup"])
    assert "description" in config


def test_stage_r4_verify_process_and_trajectory(tmp_path):
    """Combined process + trajectory checks with mock trajectory."""
    log_dir = tmp_path / "r4_combined"
    log_dir.mkdir(parents=True, exist_ok=True)
    resp_log = log_dir / "response.log"
    log_records = [
        {"step": 1, "action": "Open BankFidelity desktop app", "status": "SUCCESS"},
        {"step": 2, "action": "filter bankfidelity transactions", "status": "SUCCESS"},
    ]
    with open(resp_log, "w", encoding="utf-8") as f:
        for rec in log_records:
            f.write(json.dumps(rec) + "\n")

    traj_res = verify_session_logs(log_dir=log_dir, required_patterns=["bankfidelity"])
    assert traj_res["verified"] is True
    assert traj_res["total_steps"] == 2


# ============================================================================
# Area 1 — New Tests: Stage R5 (Multi-Agent) — 6 additional tests
# ============================================================================


def test_stage_r5_verify_multiple_candidate_files():
    """Verify falls back to candidate summary filenames."""
    desktop = get_desktop_dir()
    fallback_file = desktop / "account_summary.txt"
    try:
        fallback_file.write_text("Account balance: $1000.00", encoding="utf-8")
        res = verify_r5(dry_run=False)
        # Should find the fallback file and match keyword "balance"
        assert res["file_exists"] is True
        assert res["content_matched"] is True
    finally:
        if fallback_file.exists():
            fallback_file.unlink()


def test_stage_r5_verify_keyword_match():
    """Content containing 'balance' keyword should result in content_matched=True."""
    desktop = get_desktop_dir()
    test_file = desktop / R5_DEFAULT_SUMMARY_FILENAME
    try:
        test_file.write_text("Current balance is $5,000", encoding="utf-8")
        res = verify_file_on_desktop(
            filename=R5_DEFAULT_SUMMARY_FILENAME,
            expected_content="balance",
        )
        assert res["verified"] is True
        assert res["content_matched"] is True
    finally:
        if test_file.exists():
            test_file.unlink()


def test_stage_r5_verify_no_keyword():
    """Content without 'balance' keyword should result in content_matched=False."""
    desktop = get_desktop_dir()
    test_file = desktop / R5_DEFAULT_SUMMARY_FILENAME
    try:
        test_file.write_text("No relevant financial data here", encoding="utf-8")
        res = verify_file_on_desktop(
            filename=R5_DEFAULT_SUMMARY_FILENAME,
            expected_content="balance",
        )
        assert res["content_matched"] is False
    finally:
        if test_file.exists():
            test_file.unlink()


def test_stage_r5_pre_cleanup_all_candidates():
    """pre_cleanup removes all candidate summary filenames from Desktop."""
    desktop = get_desktop_dir()
    candidates = [R5_DEFAULT_SUMMARY_FILENAME, "account_summary.txt", "summary_report.txt"]
    created = []
    try:
        for fname in candidates:
            fpath = desktop / fname
            fpath.write_text("dummy", encoding="utf-8")
            created.append(fpath)

        pre_cleanup_r5(summary_filename=R5_DEFAULT_SUMMARY_FILENAME)

        for fpath in created:
            assert not fpath.exists(), f"{fpath.name} should have been removed by pre_cleanup"
    finally:
        for fpath in created:
            if fpath.exists():
                fpath.unlink()


def test_stage_r5_verify_missing_trajectory(tmp_path):
    """No trajectory logs should result in trajectory_verified=False."""
    empty_log_dir = tmp_path / "r5_empty_logs"
    empty_log_dir.mkdir(parents=True, exist_ok=True)

    desktop = get_desktop_dir()
    test_file = desktop / R5_DEFAULT_SUMMARY_FILENAME
    try:
        test_file.write_text("Account balance: $100", encoding="utf-8")
        res = verify_r5(task_log_dir=empty_log_dir, dry_run=False)
        assert res["trajectory_verified"] is False
    finally:
        if test_file.exists():
            test_file.unlink()


def test_stage_r5_config_target_app():
    """TARGET_APP should be 'Multi-App (BankFidelity + Notepad)'."""
    config = get_config_r5()
    assert config["target_app"] == "Multi-App (BankFidelity + Notepad)"
    assert config["id"] == "R5"


# ============================================================================
# Area 1 — New Tests: Harness & Compliance — 6 additional tests
# ============================================================================


@pytest.mark.asyncio
async def test_eval_runner_cli_exec_method(tmp_path):
    """EvaluationRunner with exec_method='cli' in dry-run mode."""
    runner = EvaluationRunner(output_dir=str(tmp_path), exec_method="cli", dry_run=True)
    res = await runner.run_stage("R1")
    assert res["status"] == "SUCCESS (DRY_RUN)"
    assert res["stage_id"] == "R1"


@pytest.mark.asyncio
async def test_eval_runner_report_timestamp_collision(tmp_path):
    """Two sequential suite runs produce unique, non-colliding report paths."""
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)

    summary1 = await runner.run_suite(stages=["R1"])
    summary2 = await runner.run_suite(stages=["R1"])

    # Collect all report files
    json_reports = list(tmp_path.glob("eval_results_*.json"))
    md_reports = list(tmp_path.glob("eval_summary_*.md"))

    assert len(json_reports) >= 2, f"Expected at least 2 JSON reports, found {len(json_reports)}"
    assert len(md_reports) >= 2, f"Expected at least 2 MD reports, found {len(md_reports)}"

    # All filenames should be unique
    json_names = [r.name for r in json_reports]
    assert len(json_names) == len(set(json_names)), "JSON report filenames should be unique"


@pytest.mark.asyncio
async def test_eval_runner_error_log_format(tmp_path):
    """Failed stage error message is a string in results."""
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    res = await runner.run_stage("R1")
    # In dry-run, error should be None
    assert res["error"] is None
    assert isinstance(res["status"], str)
    assert "DRY_RUN" in res["status"]


@pytest.mark.asyncio
async def test_eval_runner_request_override_single_stage(tmp_path):
    """Request override with single stage works correctly."""
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    custom_request = "Custom test request for R1"
    summary = await runner.run_suite(stages=["R1"], request_override=custom_request)
    assert summary["total_stages"] == 1
    assert summary["stage_results"][0]["request"] == custom_request


@pytest.mark.asyncio
async def test_eval_runner_request_override_multi_stage_raises(tmp_path):
    """Request override with multi-stage should raise ValueError."""
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    with pytest.raises(ValueError, match="Request override"):
        await runner.run_suite(stages=["R1", "R2"], request_override="Custom request")


@pytest.mark.asyncio
async def test_eval_runner_markdown_summary_format(tmp_path):
    """Generated markdown report has correct table structure."""
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    await runner.run_suite(stages=["R1", "R2"])

    md_files = list(tmp_path.glob("eval_summary_*.md"))
    assert len(md_files) >= 1

    content = md_files[0].read_text(encoding="utf-8")
    # Check for expected markdown structure
    assert "# UFO 5-Stage Evaluation Suite Execution Report" in content
    assert "## Stage Summary Table" in content
    assert "| Stage |" in content
    assert "| R1 |" in content
    assert "| R2 |" in content
