# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for EvaluationRunner and eval_suite harness."""

import pytest
import asyncio
from pathlib import Path
from tests.eval_suite.eval_runner import EvaluationRunner, EVAL_STAGES, parse_args


def test_eval_stages_registry():
    """Verify registry contains all 5 required evaluation stages R1-R5."""
    expected_stages = ["R1", "R2", "R3", "R4", "R5"]
    for s in expected_stages:
        assert s in EVAL_STAGES, f"Stage {s} missing from EVAL_STAGES"
        assert "name" in EVAL_STAGES[s]
        assert "default_request" in EVAL_STAGES[s]
        assert "target_app" in EVAL_STAGES[s]


def test_eval_runner_parse_args():
    """Test CLI argument parsing."""
    args = parse_args(["--stage", "R1,R2", "--dry-run", "--exec-method", "cli"])
    assert args.stage == "R1,R2"
    assert args.dry_run is True
    assert args.exec_method == "cli"


@pytest.mark.asyncio
async def test_eval_runner_dry_run(tmp_path):
    """Test running evaluation suite in dry-run mode."""
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    summary = await runner.run_suite(stages=["R1", "R2"])
    
    assert summary["total_stages"] == 2
    assert summary["passed_stages"] == 2
    assert summary["failed_stages"] == 0
    assert len(summary["stage_results"]) == 2
    
    # Verify report files created
    json_reports = list(tmp_path.glob("eval_results_*.json"))
    md_reports = list(tmp_path.glob("eval_summary_*.md"))
    assert len(json_reports) == 1
    assert len(md_reports) == 1
