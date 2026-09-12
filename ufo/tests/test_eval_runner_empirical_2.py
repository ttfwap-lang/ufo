# Additional deep empirical stress tests for eval_runner.py

import asyncio
import json
import os
import sys
import time
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.eval_suite.eval_runner import EvaluationRunner, EVAL_STAGES, parse_args


@pytest.mark.asyncio
async def test_log_dir_path_inconsistency_between_dryrun_and_live(tmp_path):
    """
    Empirically test consistency between dry-run and live run log_dir paths.
    """
    custom_dir = tmp_path / "custom_logs"
    runner_dry = EvaluationRunner(output_dir=str(custom_dir), dry_run=True)
    res_dry = await runner_dry.run_stage("R1")
    
    # Check dry run log_dir
    assert res_dry["log_dir"] == str(custom_dir / res_dry["task_name"])
    
    runner_live = EvaluationRunner(output_dir=str(custom_dir), dry_run=False)
    res_live = await runner_live.run_stage("R1", mode="invalid_mode_forces_error")
    assert res_live["log_dir"] == str(custom_dir / res_live["task_name"])


@pytest.mark.asyncio
async def test_invalid_stage_cli_silent_pass(tmp_path):
    """
    Empirically test passing unknown/invalid stage names via CLI/suite raises ValueError.
    """
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    with pytest.raises(ValueError, match="Invalid evaluation stage"):
        await runner.run_suite(stages=["R99"])


@pytest.mark.asyncio
async def test_multistage_request_override_discarded(tmp_path):
    """
    Empirically test that passing --request with multiple stages raises ValueError.
    """
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    override_req = "CUSTOM_OVERRIDE_REQUEST_FOR_ALL"
    
    with pytest.raises(ValueError, match="Request override '--request' can only be specified when running a single stage"):
        await runner.run_suite(stages=["R1", "R2"], request_override=override_req)


@pytest.mark.asyncio
async def test_timestamp_filename_collision_rapid_runs(tmp_path):
    """
    Empirically test file overwrite collision prevention when running multiple suites rapidly.
    """
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    
    # Run 1
    s1 = await runner.run_suite(stages=["R1"], task_prefix="run1")
    # Run 2 immediately
    s2 = await runner.run_suite(stages=["R2"], task_prefix="run2")
    
    json_files = list(tmp_path.glob("eval_results_*.json"))
    md_files = list(tmp_path.glob("eval_summary_*.md"))
    
    assert len(json_files) == 2
    assert len(md_files) == 2


@pytest.mark.asyncio
async def test_unhandled_exception_in_stage_execution(tmp_path):
    """
    Empirically test how run_stage handles unexpected exceptions during session execution.
    """
    runner = EvaluationRunner(output_dir=str(tmp_path), exec_method="api", dry_run=False)
    
    res = await runner.run_stage("R1", mode="invalid_mode_raises_error")
    
    assert res["status"] == "ERROR"
    assert res["error"] is not None
    assert res["log_dir"] == str(tmp_path / res["task_name"])

