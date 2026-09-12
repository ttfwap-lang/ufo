# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Empirical test & stress harness for tests/eval_suite/eval_runner.py.
Created by Challenger 1 to stress test evaluation runner CLI and API.
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
import pytest

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.eval_suite.eval_runner import EvaluationRunner, EVAL_STAGES, parse_args


def test_cli_parse_args_valid():
    """Test valid CLI argument parsing."""
    args = parse_args(["--stage", "R1,R2", "--mode", "normal", "--dry-run", "--exec-method", "cli"])
    assert args.stage == "R1,R2"
    assert args.mode == "normal"
    assert args.dry_run is True
    assert args.exec_method == "cli"


def test_cli_parse_args_defaults():
    """Test CLI default arguments."""
    args = parse_args([])
    assert args.stage == "ALL"
    assert args.request is None
    assert args.task is None
    assert args.mode == "normal"
    assert args.exec_method == "api"
    assert args.output_dir is None
    assert args.dry_run is False
    assert args.log_level == "INFO"


def test_cli_parse_invalid_exec_method():
    """Test that invalid --exec-method raises SystemExit (argparse choice validation)."""
    with pytest.raises(SystemExit):
        parse_args(["--exec-method", "invalid_method"])


@pytest.mark.asyncio
async def test_invalid_stage_in_run_stage():
    """Test that running an invalid stage directly raises ValueError."""
    runner = EvaluationRunner(dry_run=True)
    with pytest.raises(ValueError, match="Unknown evaluation stage"):
        await runner.run_stage("INVALID_STAGE_999")


@pytest.mark.asyncio
async def test_stage_case_insensitivity():
    """Test stage ID case insensitivity in run_stage."""
    runner = EvaluationRunner(dry_run=True)
    res = await runner.run_stage("r1")
    assert res["stage_id"] == "R1"
    assert res["status"] == "SUCCESS (DRY_RUN)"


@pytest.mark.asyncio
async def test_run_suite_with_invalid_stages_handling(tmp_path):
    """
    Stress test run_suite when invalid stage names are passed (e.g. ['INVALID', 'r1', 'FOO']).
    Check that invalid stages raise ValueError.
    """
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    with pytest.raises(ValueError, match="Invalid evaluation stage"):
        await runner.run_suite(stages=["INVALID", "r1", "FOO"])


@pytest.mark.asyncio
async def test_run_suite_all_invalid_stages(tmp_path):
    """
    Test run_suite when ONLY invalid stage names are passed.
    Check that invalid stages raise ValueError.
    """
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    with pytest.raises(ValueError, match="Invalid evaluation stage"):
        await runner.run_suite(stages=["INVALID_1", "INVALID_2"])


@pytest.mark.asyncio
async def test_request_override_multistage_behavior(tmp_path):
    """
    Test --request override when multiple stages are executed vs single stage.
    Single stage should succeed; multi-stage request override should raise ValueError.
    """
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    
    # Single stage request override
    res_single = await runner.run_suite(stages=["R1"], request_override="Custom Single Request")
    assert res_single["stage_results"][0]["request"] == "Custom Single Request"
    
    # Multi stage request override should raise ValueError
    with pytest.raises(ValueError, match="Request override '--request' can only be specified when running a single stage"):
        await runner.run_suite(stages=["R1", "R2"], request_override="Custom Multi Request")


@pytest.mark.asyncio
async def test_custom_output_dir_nested_and_spaces(tmp_path):
    """Test custom output directory with deep nesting and spaces in path."""
    nested_dir = tmp_path / "deeply" / "nested folder" / "eval output"
    runner = EvaluationRunner(output_dir=str(nested_dir), dry_run=True)
    
    summary = await runner.run_suite(stages=["R1"])
    assert nested_dir.exists()
    
    json_reports = list(nested_dir.glob("eval_results_*.json"))
    md_reports = list(nested_dir.glob("eval_summary_*.md"))
    assert len(json_reports) == 1
    assert len(md_reports) == 1


@pytest.mark.asyncio
async def test_special_characters_in_request_and_task(tmp_path):
    """Test handling of special markdown chars (pipes |, newlines, quotes, unicode, HTML/SQL) in requests."""
    adversarial_request = "Test request with | pipe | characters, \n newlines, 'quotes', \"double quotes\", <script>alert(1)</script>, & unicode 🚀"
    adversarial_task = "task_with_special_chars_&_spaces"
    
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    summary = await runner.run_suite(stages=["R1"], request_override=adversarial_request, task_prefix=adversarial_task)
    
    json_reports = list(tmp_path.glob("eval_results_*.json"))
    md_reports = list(tmp_path.glob("eval_summary_*.md"))
    
    # Verify JSON serializability
    with open(json_reports[0], "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["stage_results"][0]["request"] == adversarial_request
        
    # Verify Markdown formatting safety
    with open(md_reports[0], "r", encoding="utf-8") as f:
        md_text = f.read()
        assert "Test request with" in md_text


@pytest.mark.asyncio
async def test_corrupted_trajectory_log_resilience(tmp_path):
    """Test resilience when a task log directory contains corrupted/invalid JSON files."""
    task_name = f"corrupt_test_task_{int(time.time())}"
    logs_task_dir = tmp_path / task_name
    logs_task_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # Create valid json and invalid json
        (logs_task_dir / "valid.json").write_text('{"step": 1, "status": "ok"}', encoding="utf-8")
        (logs_task_dir / "corrupted.json").write_text('{invalid json string: true,}', encoding="utf-8")
        
        runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=False)
        res = await runner.run_stage("R1", task_name_override=task_name, mode="invalid_mode_forces_exception")
        assert res["status"] == "ERROR"
        assert res["log_dir"] == str(tmp_path / task_name)
    finally:
        if logs_task_dir.exists():
            shutil.rmtree(logs_task_dir)


@pytest.mark.asyncio
async def test_timestamp_collision_under_rapid_execution(tmp_path):
    """Test rapid consecutive executions of run_suite for output report timestamp collision."""
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    
    # Execute two suites in same second
    s1 = await runner.run_suite(stages=["R1"])
    s2 = await runner.run_suite(stages=["R1"])
    
    json_reports = list(tmp_path.glob("eval_results_*.json"))
    md_reports = list(tmp_path.glob("eval_summary_*.md"))
    
    assert len(json_reports) == 2
    assert len(md_reports) == 2

