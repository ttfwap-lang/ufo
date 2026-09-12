# Empirical verification test suite written by EMPIRICAL CHALLENGER
# Stress-testing Bug 1 (JSON Log Duplication) and Bug 2 (Missing Log Dir False Positive Pass)

import json
from pathlib import Path
import pytest

from tests.eval_suite.verifiers import verify_session_logs, verify_file_on_desktop
from tests.eval_suite.stages.stage_r1 import verify_r1
from tests.eval_suite.stages.stage_r2 import verify_r2
from tests.eval_suite.stages.stage_r3 import verify_r3
from tests.eval_suite.stages.stage_r4 import verify_r4
from tests.eval_suite.stages.stage_r5 import verify_r5


# =====================================================================
# STRESS TEST SUITE 1: JSON LOG DEDUPLICATION (Bug 1)
# =====================================================================

def test_dedup_only_top_level_json_files(tmp_path):
    """Test that top-level json files are NOT processed twice."""
    log_dir = tmp_path / "top_level_only"
    log_dir.mkdir(parents=True, exist_ok=True)

    f1 = log_dir / "step_1.json"
    f2 = log_dir / "step_2.json"
    f3 = log_dir / "step_3.json"

    f1.write_text(json.dumps({"step": 1, "action": "click button", "status": "SUCCESS"}), encoding="utf-8")
    f2.write_text(json.dumps({"step": 2, "action": "type text Notepad", "status": "SUCCESS"}), encoding="utf-8")
    f3.write_text(json.dumps({"step": 3, "action": "save file", "status": "SUCCESS"}), encoding="utf-8")

    res = verify_session_logs(log_dir=log_dir, required_patterns=["Notepad"])
    assert res["verified"] is True
    assert res["total_steps"] == 3, f"Expected 3 steps, got {res['total_steps']} (DUPLICATION DETECTED!)"
    assert "Notepad" in res["matched_patterns"]


def test_dedup_mixed_top_level_and_nested_json_files(tmp_path):
    """Test top-level and sub-directory json files are deduplicated correctly."""
    log_dir = tmp_path / "mixed_levels"
    log_dir.mkdir(parents=True, exist_ok=True)
    sub_dir = log_dir / "subfolder"
    sub_dir.mkdir(parents=True, exist_ok=True)

    f1 = log_dir / "step_1.json"
    f2 = sub_dir / "step_2.json"

    f1.write_text(json.dumps({"step": 1, "action": "action1", "status": "SUCCESS"}), encoding="utf-8")
    f2.write_text(json.dumps({"step": 2, "action": "action2", "status": "SUCCESS"}), encoding="utf-8")

    res = verify_session_logs(log_dir=log_dir)
    assert res["verified"] is True
    assert res["total_steps"] == 2, f"Expected 2 steps, got {res['total_steps']}"


def test_dedup_many_top_level_files(tmp_path):
    """Stress test with 20 top-level json files to ensure zero duplication across larger batches."""
    log_dir = tmp_path / "batch_20"
    log_dir.mkdir(parents=True, exist_ok=True)

    for i in range(20):
        f = log_dir / f"step_{i:02d}.json"
        f.write_text(json.dumps({"step": i, "action": f"action_{i}", "status": "SUCCESS"}), encoding="utf-8")

    res = verify_session_logs(log_dir=log_dir)
    assert res["total_steps"] == 20, f"Expected 20 steps, got {res['total_steps']}"


def test_dedup_response_log_takes_precedence_over_json(tmp_path):
    """Verify response.log in root suppresses JSON fallback entirely."""
    log_dir = tmp_path / "resp_log_priority"
    log_dir.mkdir(parents=True, exist_ok=True)

    resp_log = log_dir / "response.log"
    resp_log.write_text(json.dumps({"step": 1, "action": "resp action", "status": "SUCCESS"}), encoding="utf-8")

    json_file = log_dir / "step_2.json"
    json_file.write_text(json.dumps({"step": 2, "action": "json action", "status": "SUCCESS"}), encoding="utf-8")

    res = verify_session_logs(log_dir=log_dir, required_patterns=["resp action"])
    assert res["total_steps"] == 1
    assert "resp action" in res["matched_patterns"]


def test_dedup_absolute_vs_relative_paths(tmp_path):
    """Test deduplication when log_dir is provided as absolute Path vs string."""
    log_dir = tmp_path / "abs_rel_test"
    log_dir.mkdir(parents=True, exist_ok=True)

    f1 = log_dir / "step_1.json"
    f1.write_text(json.dumps({"step": 1, "action": "step 1 action", "status": "SUCCESS"}), encoding="utf-8")

    res_str = verify_session_logs(log_dir=str(log_dir.resolve()))
    res_path = verify_session_logs(log_dir=log_dir.resolve())

    assert res_str["total_steps"] == 1
    assert res_path["total_steps"] == 1


# =====================================================================
# STRESS TEST SUITE 2: MISSING LOG DIR FALSE POSITIVE PASS (Bug 2)
# =====================================================================

def test_missing_log_dir_stage_r1(tmp_path):
    """Stage R1 must fail trajectory and overall when task_log_dir does not exist."""
    missing = tmp_path / "non_existent_r1_dir"
    res = verify_r1(task_log_dir=missing, dry_run=False)
    assert res["trajectory_verified"] is False, "Stage R1 trajectory_verified should be False for missing log dir"
    assert res["verified"] is False, "Stage R1 verified should be False for missing log dir"


def test_missing_log_dir_stage_r2(tmp_path):
    """Stage R2 must fail trajectory and overall when task_log_dir does not exist."""
    missing = tmp_path / "non_existent_r2_dir"
    res = verify_r2(task_log_dir=missing, dry_run=False)
    assert res["trajectory_verified"] is False, "Stage R2 trajectory_verified should be False for missing log dir"
    assert res["verified"] is False, "Stage R2 verified should be False for missing log dir"


def test_missing_log_dir_stage_r3_task_log_dir(tmp_path):
    """Stage R3 must fail trajectory and overall when task_log_dir does not exist."""
    missing = tmp_path / "non_existent_r3_dir"
    res = verify_r3(task_log_dir=missing, dry_run=False)
    assert res["trajectory_verified"] is False, "Stage R3 trajectory_verified should be False for missing log dir"
    assert res["verified"] is False, "Stage R3 verified should be False for missing log dir"


def test_missing_log_dir_stage_r3_output_dir(tmp_path):
    """Stage R3 must fail trajectory and overall when output_dir does not exist."""
    missing = tmp_path / "non_existent_r3_output_dir"
    res = verify_r3(output_dir=missing, dry_run=False)
    assert res["trajectory_verified"] is False, "Stage R3 trajectory_verified should be False for missing output dir"
    assert res["verified"] is False, "Stage R3 verified should be False for missing output dir"


def test_missing_log_dir_stage_r3_stage_data_dict(tmp_path):
    """Stage R3 must fail when stage_data dict specifies non-existent log_dir."""
    missing = tmp_path / "non_existent_r3_stage_data_dir"
    res = verify_r3(stage_data={"log_dir": str(missing)}, dry_run=False)
    assert res["trajectory_verified"] is False
    assert res["verified"] is False


def test_missing_log_dir_stage_r4(tmp_path):
    """Stage R4 must fail trajectory and overall when task_log_dir does not exist."""
    missing = tmp_path / "non_existent_r4_dir"
    res = verify_r4(task_log_dir=missing, dry_run=False)
    assert res["trajectory_verified"] is False, "Stage R4 trajectory_verified should be False for missing log dir"
    assert res["verified"] is False, "Stage R4 verified should be False for missing log dir"


def test_missing_log_dir_stage_r5(tmp_path):
    """Stage R5 must fail trajectory and overall when task_log_dir does not exist."""
    missing = tmp_path / "non_existent_r5_dir"
    res = verify_r5(task_log_dir=missing, dry_run=False)
    assert res["trajectory_verified"] is False, "Stage R5 trajectory_verified should be False for missing log dir"
    assert res["verified"] is False, "Stage R5 verified should be False for missing log dir"


def test_empty_existing_log_dir_all_stages(tmp_path):
    """Stage verifiers must fail when task_log_dir exists but contains NO log files."""
    empty_dir = tmp_path / "empty_existing_dir"
    empty_dir.mkdir(parents=True, exist_ok=True)

    for stage_name, ver_fn in [("R1", verify_r1), ("R2", verify_r2), ("R3", verify_r3), ("R4", verify_r4), ("R5", verify_r5)]:
        res = ver_fn(task_log_dir=empty_dir, dry_run=False)
        assert res["trajectory_verified"] is False, f"Stage {stage_name} trajectory_verified should be False for empty log dir"
        assert res["verified"] is False, f"Stage {stage_name} verified should be False for empty log dir"


def test_log_dir_pointing_to_file_all_stages(tmp_path):
    """Stage verifiers must fail gracefully when task_log_dir points to a regular file instead of a directory."""
    file_as_dir = tmp_path / "some_file.txt"
    file_as_dir.write_text("not a directory", encoding="utf-8")

    for stage_name, ver_fn in [("R1", verify_r1), ("R2", verify_r2), ("R3", verify_r3), ("R4", verify_r4), ("R5", verify_r5)]:
        res = ver_fn(task_log_dir=file_as_dir, dry_run=False)
        assert res["trajectory_verified"] is False, f"Stage {stage_name} trajectory_verified should be False when log_dir is a file"
        assert res["verified"] is False, f"Stage {stage_name} verified should be False when log_dir is a file"
