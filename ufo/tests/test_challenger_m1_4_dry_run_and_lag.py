# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Empirical Challenger Test Suite for Challenger 4 (Milestone M1 Iteration 2).
Target:
1. Verify --dry-run performs zero pre_cleanup actions (0 process spawns, 0 file modifications).
2. Verify non-dry-run pre_cleanup offloads execution without blocking the main asyncio event loop.
"""

import asyncio
import inspect
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.eval_suite.eval_runner import EVAL_STAGES, EvaluationRunner
from tests.eval_suite.verifiers import get_desktop_dir


@pytest.mark.asyncio
async def test_dry_run_zero_pre_cleanup_calls(tmp_path):
    """
    Empirical Verification 1:
    Verify that in --dry-run mode, pre_cleanup is NEVER called for any stage.
    """
    call_counts = {"R1": 0, "R2": 0, "R3": 0, "R4": 0, "R5": 0}

    def make_spy(stage_id):
        def spy_cleanup(*args, **kwargs):
            call_counts[stage_id] += 1
        return spy_cleanup

    # Patch EVAL_STAGES with spy pre_cleanup handlers
    patched_stages = {}
    for stage_id, config in EVAL_STAGES.items():
        copy_config = dict(config)
        copy_config["pre_cleanup"] = make_spy(stage_id)
        patched_stages[stage_id] = copy_config

    with patch.dict(EVAL_STAGES, patched_stages, clear=True):
        runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
        
        # Run individual stages
        for stage_id in ["R1", "R2", "R3", "R4", "R5"]:
            res = await runner.run_stage(stage_id)
            assert res["status"] == "SUCCESS (DRY_RUN)"

        # Run entire suite
        suite_res = await runner.run_suite(stages=["R1", "R2", "R3", "R4", "R5"])
        assert suite_res["passed_stages"] == 5

    # Empirically verify 0 calls across all stages
    for stage_id, count in call_counts.items():
        assert count == 0, f"Stage {stage_id} pre_cleanup was executed {count} times during dry run! Expected 0."


@pytest.mark.asyncio
async def test_dry_run_desktop_file_and_process_isolation(tmp_path):
    """
    Empirical Verification 2:
    Verify that dry-run execution on Stage R1 does NOT delete desktop sentinel file or spawn processes.
    """
    desktop_dir = get_desktop_dir()
    sentinel_filename = "ufo_test_dry_run_sentinel.txt"
    sentinel_path = desktop_dir / sentinel_filename
    
    # Write sentinel file on Desktop
    sentinel_path.write_text("SENTINEL_CONTENT_DO_NOT_DELETE", encoding="utf-8")
    
    try:
        runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)

        # Spy on subprocess.Popen / subprocess.run to verify zero processes spawned
        with patch("subprocess.Popen") as mock_popen, patch("subprocess.run") as mock_run:
            res = await runner.run_stage("R1")
            
            assert res["status"] == "SUCCESS (DRY_RUN)"
            assert sentinel_path.exists(), "Desktop sentinel file was deleted during dry run!"
            assert sentinel_path.read_text(encoding="utf-8") == "SENTINEL_CONTENT_DO_NOT_DELETE"
            assert mock_popen.call_count == 0, f"Process spawned during dry run! Popen calls: {mock_popen.call_count}"
            assert mock_run.call_count == 0, f"Process run during dry run! Run calls: {mock_run.call_count}"
    finally:
        if sentinel_path.exists():
            sentinel_path.unlink()


@pytest.mark.asyncio
async def test_non_dry_run_pre_cleanup_event_loop_offloading(tmp_path):
    """
    Empirical Verification 3:
    Verify that in standard live mode (dry_run=False), synchronous pre_cleanup functions
    are offloaded via asyncio.to_thread and DO NOT block the main asyncio event loop.
    """
    cleanup_executed = False

    def blocking_sync_cleanup():
        nonlocal cleanup_executed
        time.sleep(0.5)  # Blocking synchronous delay for 500ms
        cleanup_executed = True

    # Patch stage config R1 with blocking cleanup
    patched_r1 = dict(EVAL_STAGES["R1"])
    patched_r1["pre_cleanup"] = blocking_sync_cleanup

    with patch.dict(EVAL_STAGES, {"R1": patched_r1}):
        runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=False)
        
        latencies = []
        stop_monitor = False

        async def monitor_event_loop():
            nonlocal latencies, stop_monitor
            tick_interval = 0.005  # 5ms tick monitor
            while not stop_monitor:
                t0 = time.perf_counter()
                await asyncio.sleep(tick_interval)
                t1 = time.perf_counter()
                elapsed = t1 - t0
                latencies.append(elapsed - tick_interval)

        monitor_task = asyncio.create_task(monitor_event_loop())

        # Mock SessionFactory so run_stage doesn't attempt live UI execution after pre_cleanup
        with patch("ufo.module.session_pool.SessionFactory") as mock_factory, \
             patch("ufo.module.session_pool.SessionPool") as mock_pool:
            mock_pool.return_value.run_all = MagicMock(side_effect=lambda: asyncio.sleep(0.01))
            
            await runner.run_stage("R1")

        stop_monitor = True
        await monitor_task

        assert cleanup_executed is True, "Pre-cleanup function was not executed in live mode!"
        
        max_latency = max(latencies) if latencies else 0.0
        print(f"\n[Empirical Check] Max event loop latency during 500ms sync pre_cleanup: {max_latency * 1000:.2f}ms")

        # If blocking occurred on main thread, latency would be >= 500ms.
        # With asyncio.to_thread offloading, event loop lag remains < 50ms.
        assert max_latency < 0.05, f"Event loop was blocked by synchronous pre_cleanup! Max latency: {max_latency * 1000:.2f}ms"


@pytest.mark.asyncio
async def test_async_pre_cleanup_support(tmp_path):
    """
    Empirical Verification 4:
    Verify that pre_cleanup coroutines (async def pre_cleanup) are awaited properly without errors.
    """
    async_cleanup_executed = False

    async def async_cleanup():
        nonlocal async_cleanup_executed
        await asyncio.sleep(0.05)
        async_cleanup_executed = True

    patched_r2 = dict(EVAL_STAGES["R2"])
    patched_r2["pre_cleanup"] = async_cleanup

    with patch.dict(EVAL_STAGES, {"R2": patched_r2}):
        runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=False)

        with patch("ufo.module.session_pool.SessionFactory"), \
             patch("ufo.module.session_pool.SessionPool") as mock_pool:
            mock_pool.return_value.run_all = MagicMock(side_effect=lambda: asyncio.sleep(0.01))
            await runner.run_stage("R2")

    assert async_cleanup_executed is True, "Async pre_cleanup coroutine was not executed properly!"
