# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Empirical Challenger Stress Harness for tests/eval_suite/eval_runner.py.
Created by Challenger 2 to empirically challenge and stress-test:
1. High-concurrency stage & suite execution.
2. Non-blocking event loop verification during heavy file writing & trajectory collection.
3. Race condition resilience and JSON report file integrity under shared output directory concurrency.
4. Trajectory log collection stress and corrupt file handling under concurrent read/write.
5. Pre-cleanup blocking I/O and dry-run side-effect leak verification.
"""

import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.eval_suite.eval_runner import EvaluationRunner, EVAL_STAGES, _generate_unique_report_paths, _write_json_file, _collect_trajectory_logs


@pytest.mark.asyncio
async def test_concurrent_suite_executions_high_load(tmp_path):
    """
    Stress test 25 concurrent run_suite instances.
    Verify all complete successfully and generate valid uncorrupted JSON and Markdown reports.
    """
    num_concurrent = 25
    runners = [
        EvaluationRunner(output_dir=str(tmp_path / f"runner_{i}"), dry_run=True)
        for i in range(num_concurrent)
    ]

    tasks = [
        runner.run_suite(stages=["R1", "R2"])
        for runner in runners
    ]

    results = await asyncio.gather(*tasks)

    assert len(results) == num_concurrent
    for i, summary in enumerate(results):
        assert summary["total_stages"] == 2
        assert summary["passed_stages"] == 2
        assert summary["failed_stages"] == 0
        assert len(summary["stage_results"]) == 2

        # Verify output files in each runner's dir
        r_dir = tmp_path / f"runner_{i}"
        json_reports = list(r_dir.glob("eval_results_*.json"))
        md_reports = list(r_dir.glob("eval_summary_*.md"))

        assert len(json_reports) == 1
        assert len(md_reports) == 1

        # Verify JSON file validity
        with open(json_reports[0], "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data["total_stages"] == 2
            assert len(data["stage_results"]) == 2


@pytest.mark.asyncio
async def test_event_loop_blocking_by_pre_cleanup(tmp_path):
    """
    Empirically test whether pre_cleanup_fn in run_stage blocks the asyncio event loop
    and leaks live side-effects during dry-run execution.
    """
    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    latencies = []
    stop_monitor = False

    async def monitor_event_loop():
        nonlocal latencies, stop_monitor
        tick_interval = 0.005  # 5ms
        while not stop_monitor:
            t0 = time.perf_counter()
            await asyncio.sleep(tick_interval)
            t1 = time.perf_counter()
            elapsed = t1 - t0
            latencies.append(elapsed - tick_interval)

    monitor_task = asyncio.create_task(monitor_event_loop())

    # Execute 5 concurrent run_stage calls for R3 (which calls pre_cleanup with time.sleep(1.0))
    stage_tasks = [
        runner.run_stage("R3")
        for _ in range(5)
    ]

    await asyncio.gather(*stage_tasks)
    stop_monitor = True
    await monitor_task

    max_latency = max(latencies) if latencies else 0.0
    print(f"Event Loop Max Latency during run_stage('R3'): {max_latency*1000:.2f}ms")

    # If pre_cleanup runs synchronously on main thread, latency will exceed 500ms (0.5s)
    # This assertion empirically exposes event loop blocking bug in eval_runner.py!
    assert max_latency < 0.1, f"Event loop severely blocked by pre_cleanup synchronously: max lag = {max_latency*1000:.2f}ms"


@pytest.mark.asyncio
async def test_race_condition_in_unique_report_path_generation(tmp_path):
    """
    Empirically test race condition when multiple concurrent tasks call _generate_unique_report_paths
    with the exact same timestamp string before files are written.
    """
    shared_dir = tmp_path / "race_test_logs"
    shared_dir.mkdir(parents=True, exist_ok=True)
    same_timestamp = "20260813_120000_000000"

    # Concurrently generate report paths and write files using asyncio.to_thread
    async def write_report(task_id: int):
        json_p, md_p = await asyncio.to_thread(_generate_unique_report_paths, shared_dir, same_timestamp)
        payload = {"task_id": task_id, "timestamp": same_timestamp, "data": "x"*500}
        await asyncio.to_thread(_write_json_file, json_p, payload)
        return json_p

    tasks = [write_report(i) for i in range(10)]
    written_paths = await asyncio.gather(*tasks)

    # Verify how many unique JSON files were created
    json_files = list(shared_dir.glob("eval_results_*.json"))
    unique_paths = set(written_paths)

    print(f"Written paths count: {len(written_paths)}, Unique returned paths: {len(unique_paths)}, Files on disk: {len(json_files)}")

    # Check for collisions
    assert len(unique_paths) == 10, f"Race condition detected! 10 concurrent requests yielded only {len(unique_paths)} unique paths: {written_paths}"
    assert len(json_files) == 10, f"File overwrite collision! Expected 10 files on disk, found {len(json_files)}"


@pytest.mark.asyncio
async def test_trajectory_collection_stress_and_corruption_resilience(tmp_path):
    """
    Stress test trajectory log collection (_collect_trajectory_logs) under heavy file load and corrupted JSON files.
    """
    task_dir = tmp_path / "heavy_task_logs"
    task_dir.mkdir(parents=True, exist_ok=True)

    # Create 50 valid trajectory files and 10 corrupted files
    for i in range(50):
        (task_dir / f"step_{i:03d}.json").write_text(json.dumps({"step": i, "action": f"test_action_{i}", "payload": "x"*1000}), encoding="utf-8")

    for i in range(10):
        (task_dir / f"corrupt_{i:03d}.json").write_text("{BAD_JSON_CONTENT: [1, 2, ", encoding="utf-8")

    runner = EvaluationRunner(output_dir=str(tmp_path), dry_run=False)

    # Run trajectory collection offloaded to thread concurrently 10 times
    tasks = [
        asyncio.to_thread(_collect_trajectory_logs, task_dir, runner.logger)
        for _ in range(10)
    ]

    results = await asyncio.gather(*tasks)

    for trajectories in results:
        # Should collect 50 valid trajectory logs and ignore 10 corrupted ones without throwing
        assert len(trajectories) == 50
        steps = [t["content"]["step"] for t in trajectories]
        assert len(steps) == 50
        assert set(steps) == set(range(50))


@pytest.mark.asyncio
async def test_concurrent_stage_execution_mixed_success_and_failure(tmp_path):
    """
    Test running multiple stages concurrently in the same runner, with a mix of valid dry-run stages
    and invalid live-mode stages to verify isolation of task failures.
    """
    runner_dry = EvaluationRunner(output_dir=str(tmp_path), dry_run=True)
    runner_live_err = EvaluationRunner(output_dir=str(tmp_path), dry_run=False)

    t1 = runner_dry.run_stage("R1")
    t2 = runner_dry.run_stage("R2")
    t3 = runner_live_err.run_stage("R3", mode="invalid_mode_forces_error")

    r1, r2, r3 = await asyncio.gather(t1, t2, t3)

    assert r1["status"] == "SUCCESS (DRY_RUN)"
    assert r2["status"] == "SUCCESS (DRY_RUN)"
    assert r3["status"] == "ERROR"
    assert "invalid_mode_forces_error" in str(r3.get("error") or "")
