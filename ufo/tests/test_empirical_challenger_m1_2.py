"""
Empirical Challenger Test Suite for Milestone 1 (M1: Challenger 2).
Focus: Stress testing async non-blocking file writes in eval_runner.py under
high iteration, high concurrency (asyncio.gather), multithreaded parallel conditions,
and verifying event loop responsiveness.
"""
import asyncio
import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
import pytest
from tests.eval_suite.eval_runner import EvaluationRunner, _generate_unique_report_paths, _write_json_file_async

@pytest.fixture
def temp_output_dir():
    """Create temporary output directory for test evaluation logs."""
    temp_dir = tempfile.mkdtemp(prefix='ufo_challenger_m1_2_')
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)

@pytest.mark.asyncio
async def test_high_iteration_sequential_writes(temp_output_dir):
    """Stress test 50 sequential dry-run suite executions to ensure file writes remain clean and consistent."""
    runner = EvaluationRunner(output_dir=str(temp_output_dir), dry_run=True, log_level='ERROR')
    num_iterations = 50
    for i in range(num_iterations):
        summary = await runner.run_suite(stages=['ALL'])
        assert summary['passed_stages'] == 5
        assert summary['failed_stages'] == 0
    json_files = list(temp_output_dir.glob('eval_results_*.json'))
    md_files = list(temp_output_dir.glob('eval_summary_*.md'))
    assert len(json_files) == num_iterations
    assert len(md_files) == num_iterations
    for jf in json_files:
        assert jf.stat().st_size > 0
        with open(jf, 'r', encoding='utf-8') as f:
            data = json.load(f)
            assert data['total_stages'] == 5
            assert len(data['stage_results']) == 5
    for mf in md_files:
        assert mf.stat().st_size > 0
        content = mf.read_text(encoding='utf-8')
        assert '# UFO 5-Stage Evaluation Suite Execution Report' in content

@pytest.mark.asyncio
async def test_high_concurrency_async_gather_writes(temp_output_dir):
    """Stress test 50 concurrent async tasks executing run_suite simultaneously on a single event loop."""
    runner = EvaluationRunner(output_dir=str(temp_output_dir), dry_run=True, log_level='ERROR')
    num_concurrent = 50
    tasks = [runner.run_suite(stages=['ALL']) for _ in range(num_concurrent)]
    results = await asyncio.gather(*tasks)
    assert len(results) == num_concurrent
    for res in results:
        assert res['passed_stages'] == 5
    json_files = list(temp_output_dir.glob('eval_results_*.json'))
    md_files = list(temp_output_dir.glob('eval_summary_*.md'))
    assert len(json_files) == num_concurrent
    assert len(md_files) == num_concurrent
    seen_timestamps = set()
    for jf in json_files:
        assert jf.stat().st_size > 0
        with open(jf, 'r', encoding='utf-8') as f:
            data = json.load(f)
            assert data['passed_stages'] == 5
            seen_timestamps.add(data['timestamp'])
    for mf in md_files:
        assert mf.stat().st_size > 0

def _worker_thread_run(temp_output_dir, results_list, index):
    """Worker target for multithreaded stress test."""
    try:
        runner = EvaluationRunner(output_dir=str(temp_output_dir), dry_run=True, log_level='ERROR')
        res = asyncio.run(runner.run_suite(stages=['ALL']))
        results_list[index] = res
    except Exception as e:
        results_list[index] = e

def test_multithreaded_parallel_writes(temp_output_dir):
    """Stress test 20 parallel threads each executing run_suite in their own asyncio event loop."""
    num_threads = 20
    threads = []
    results = [None] * num_threads
    for i in range(num_threads):
        t = threading.Thread(target=_worker_thread_run, args=(temp_output_dir, results, i))
        threads.append(t)
        t.start()
    for t in threads:
        t.join(timeout=30)
    for i, res in enumerate(results):
        assert res is not None, f'Thread {i} did not produce a result'
        assert not isinstance(res, Exception), f'Thread {i} failed with: {res}'
        assert res['passed_stages'] == 5
    json_files = list(temp_output_dir.glob('eval_results_*.json'))
    md_files = list(temp_output_dir.glob('eval_summary_*.md'))
    assert len(json_files) == num_threads
    assert len(md_files) == num_threads

@pytest.mark.asyncio
async def test_event_loop_unblocked_during_async_writes(temp_output_dir):
    """Empirically measure event loop responsiveness during async file writes."""
    runner = EvaluationRunner(output_dir=str(temp_output_dir), dry_run=True, log_level='ERROR')
    ticker_count = 0
    stop_ticker = False

    async def ticker():
        nonlocal ticker_count
        while not stop_ticker:
            ticker_count += 1
            await asyncio.sleep(0.005)
    ticker_task = asyncio.create_task(ticker())
    tasks = [runner.run_suite(stages=['R1', 'R2']) for _ in range(30)]
    await asyncio.gather(*tasks)
    stop_ticker = True
    await ticker_task
    assert ticker_count >= 5, f'Event loop appears blocked! Ticker only ran {ticker_count} times.'

@pytest.mark.asyncio
async def test_atomic_unique_path_generation(temp_output_dir):
    """Verify that _generate_unique_report_paths handles simulated timestamp collisions perfectly under race conditions."""
    fixed_ts = '20260813_120000_000000'

    def get_path():
        return _generate_unique_report_paths(temp_output_dir, fixed_ts)
    paths = await asyncio.gather(*[asyncio.to_thread(get_path) for _ in range(30)])
    json_paths = [p[0] for p in paths]
    md_paths = [p[1] for p in paths]
    assert len(set(json_paths)) == 30
    assert len(set(md_paths)) == 30
    for jp, mp in paths:
        assert jp.exists()
        assert mp.exists()