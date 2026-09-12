"""
Evaluation Test Harness & Runner for UFO 5-Stage GUI Automation Sequence.

Supported Stages:
    pass
- R1: Notepad Test (open Notepad, type text, save to Desktop)
- R2: Chrome Navigation (open Chrome, navigate to URLs)
- R3: Basic BankFidelity Task (open BankFidelity, verify UI)
- R4: Complex BankFidelity Task (multi-step BankFidelity flow)
- R5: Multi-Agent Task (HostAgent multi-application delegation)
"""
import argparse
import asyncio
import inspect
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from tests.eval_suite.stages import stage_r1, stage_r2, stage_r3, stage_r4, stage_r5
from tests.eval_suite.stages.stage_r1 import DEFAULT_FILENAME as R1_DEFAULT_FILENAME, DEFAULT_MESSAGE as R1_DEFAULT_MESSAGE, pre_cleanup as pre_cleanup_r1, verify_r1
from tests.eval_suite.stages.stage_r2 import verify_r2
from tests.eval_suite.stages.stage_r3 import verify_r3
from tests.eval_suite.stages.stage_r4 import verify_r4
from tests.eval_suite.stages.stage_r5 import verify_r5
EVAL_STAGES: Dict[str, Dict[str, Any]] = {'R1': stage_r1.get_stage_config(), 'R2': stage_r2.get_stage_config(), 'R3': stage_r3.get_stage_config(), 'R4': stage_r4.get_stage_config(), 'R5': stage_r5.get_stage_config()}

def _write_json_file(filepath: Path, data: Dict[str, Any]) -> None:
    """Helper to write JSON data to file synchronously."""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

async def _write_json_file_async(filepath: Path, data: Dict[str, Any]) -> None:
    """Helper to write JSON data to file asynchronously using asyncio.to_thread()."""
    await asyncio.to_thread(_write_json_file, filepath, data)
_REPORT_PATH_LOCK = threading.Lock()

def _generate_unique_report_paths(output_dir: Path, timestamp: str) -> Tuple[Path, Path]:
    """Helper to determine non-colliding JSON and Markdown report file paths thread-safely."""
    with _REPORT_PATH_LOCK:
        json_path = output_dir / f'eval_results_{timestamp}.json'
        md_path = output_dir / f'eval_summary_{timestamp}.md'
        counter = 1
        while True:
            if not json_path.exists() and (not md_path.exists()):
                try:
                    json_path.touch(exist_ok=False)
                    try:
                        md_path.touch(exist_ok=False)
                        break
                    except FileExistsError:
                        json_path.unlink(missing_ok=True)
                        raise
                except FileExistsError:
                    pass
            ts_unique = f'{timestamp}_{counter}'
            json_path = output_dir / f'eval_results_{ts_unique}.json'
            md_path = output_dir / f'eval_summary_{ts_unique}.md'
            counter += 1
        return (json_path, md_path)

def _collect_trajectory_logs(task_log_dir: Path, logger: logging.Logger) -> List[Dict[str, Any]]:
    """Helper to synchronously search and read trajectory JSON files from log dir."""
    trajectories: List[Dict[str, Any]] = []
    if task_log_dir.exists():
        for log_file in task_log_dir.glob('*.json'):
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    trajectories.append({'file': log_file.name, 'content': data})
            except Exception as e:
                logger.warning(f'Could not read trajectory log file {log_file}: {e}')
    return trajectories

class EvaluationRunner:
    """
    Test harness and runner for executing UFO evaluation stages programmatically.
    """

    def __init__(self, output_dir: Optional[str]=None, exec_method: str='api', dry_run: bool=False, log_level: str='INFO'):
        """
        Initialize the EvaluationRunner.

        :param output_dir: Directory to save evaluation logs and structured result artifacts.
        :param exec_method: 'api' (use SessionFactory / SessionPool) or 'cli' (subprocess python -m ufo).
        :param dry_run: If True, validate configuration without calling live LLM/UI execution.
        :param log_level: Logging level string.
        """
        self.output_dir = Path(output_dir) if output_dir else PROJECT_ROOT / 'logs' / 'eval_suite'
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.exec_method = exec_method.lower()
        self.dry_run = dry_run
        logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))
        self.logger = logging.getLogger('EvalRunner')

    async def run_stage(self, stage_id: str, request_override: Optional[str]=None, task_name_override: Optional[str]=None, mode: str='normal') -> Dict[str, Any]:
        """
        Run a single evaluation stage.

        :param stage_id: Stage key (e.g. 'R1', 'R2', 'R3', 'R4', 'R5').
        :param request_override: Custom request string to override stage default.
        :param task_name_override: Custom task name.
        :param mode: Session mode ('normal', 'follower', 'batch_normal', 'operator').
        :return: Structured result dictionary.
        """
        stage_id = stage_id.upper()
        if stage_id not in EVAL_STAGES:
            raise ValueError(f"Unknown evaluation stage '{stage_id}'. Available: {list(EVAL_STAGES.keys())}")
        stage_meta = EVAL_STAGES[stage_id]
        request_text: str = str(request_override or stage_meta.get('default_request') or stage_meta.get('request') or '')
        timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        task_name = task_name_override or f'eval_{stage_id}_{timestamp_str}'
        self.logger.info(f"--- Starting Stage {stage_id}: {stage_meta['name']} ---")
        self.logger.info(f'Task Name: {task_name}')
        self.logger.info(f'Request: {request_text}')
        self.logger.info(f'Execution Method: {self.exec_method} (Dry Run: {self.dry_run})')
        if not self.dry_run:
            pre_cleanup_fn = stage_meta.get('pre_cleanup')
            if pre_cleanup_fn and callable(pre_cleanup_fn):
                try:
                    if inspect.iscoroutinefunction(pre_cleanup_fn):
                        await pre_cleanup_fn()
                    else:
                        await asyncio.to_thread(pre_cleanup_fn)
                except Exception as e:
                    self.logger.warning(f'[Stage {stage_id} Pre-Cleanup] Failed: {e}')
        start_time = time.time()
        start_iso = datetime.now().isoformat()
        status = 'SUCCESS'
        error_msg = None
        trajectories: List[Dict[str, Any]] = []
        verifier_fn = stage_meta.get('verifier')
        if self.dry_run:
            self.logger.info(f'[DRY RUN] Simulating execution for Stage {stage_id}')
            await asyncio.sleep(0.1)
            duration = time.time() - start_time
            end_iso = datetime.now().isoformat()
            verification_result = {}
            if verifier_fn and callable(verifier_fn):
                verification_result = verifier_fn(dry_run=True)
            elif stage_id == 'R1':
                verification_result = verify_r1(dry_run=True)
            elif stage_id == 'R2':
                verification_result = verify_r2(dry_run=True)
            elif stage_id == 'R3':
                verification_result = verify_r3(dry_run=True)
            elif stage_id == 'R4':
                verification_result = verify_r4(dry_run=True)
            elif stage_id == 'R5':
                verification_result = verify_r5(dry_run=True)
            return {'stage_id': stage_id, 'stage_name': stage_meta['name'], 'target_app': stage_meta['target_app'], 'task_name': task_name, 'request': request_text, 'mode': mode, 'status': 'SUCCESS (DRY_RUN)', 'start_time': start_iso, 'end_time': end_iso, 'duration_seconds': round(duration, 3), 'error': None, 'trajectories': [{'step': 1, 'action': 'Dry run simulation completed successfully'}], 'verification': verification_result, 'log_dir': str(self.output_dir / task_name)}
        verification_result = {}
        try:
            if self.exec_method == 'api':
                from ufo.module.session_pool import SessionFactory, SessionPool
                sessions = SessionFactory().create_session(task=task_name, mode=mode, plan='', request=request_text)
                pool = SessionPool(sessions)
                await asyncio.sleep(0.25)
                try:
                    await asyncio.wait_for(pool.run_all(), timeout=3600)
                except asyncio.TimeoutError:
                    status = 'FAILED'
                    error_msg = f'Stage {stage_id} timed out after 3600 seconds'
                    self.logger.error(error_msg)
            elif self.exec_method == 'cli':
                cmd: List[str] = [sys.executable, '-m', 'ufo', '--task', task_name, '--request', request_text, '--mode', mode]
                self.logger.info(f"Executing CLI command: {' '.join(cmd)}")
                proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=str(PROJECT_ROOT))
                timeout_seconds = stage_meta.get('timeout', 3600)
                try:
                    try:
                        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
                    except asyncio.TimeoutError:
                        status = 'FAILED'
                        error_msg = f'Stage {stage_id} CLI execution timed out after {timeout_seconds} seconds'
                        self.logger.error(error_msg)
                    else:
                        if proc.returncode != 0:
                            status = 'FAILED'
                            error_msg = stderr.decode('utf-8', errors='replace')
                            self.logger.error(f'Stage {stage_id} CLI failed with exit code {proc.returncode}: {error_msg}')
                finally:
                    if proc.returncode is None:
                        try:
                            proc.kill()
                            await proc.wait()
                        except Exception:
                            pass
            task_log_dir = self.output_dir / task_name
            if not task_log_dir.exists():
                fallback_dir = PROJECT_ROOT / 'logs' / task_name
                if fallback_dir.exists():
                    task_log_dir = fallback_dir
            trajectories = await asyncio.to_thread(_collect_trajectory_logs, task_log_dir, self.logger)
            if verifier_fn and callable(verifier_fn):
                verification_result = verifier_fn(task_log_dir=task_log_dir, dry_run=self.dry_run)
            elif stage_id == 'R1':
                verification_result = verify_r1(task_log_dir=task_log_dir, dry_run=self.dry_run)
            elif stage_id == 'R2':
                verification_result = verify_r2(task_log_dir=task_log_dir, dry_run=self.dry_run)
            elif stage_id == 'R3':
                verification_result = verify_r3(task_log_dir=task_log_dir, dry_run=self.dry_run)
            elif stage_id == 'R4':
                verification_result = verify_r4(task_log_dir=task_log_dir, dry_run=self.dry_run)
            elif stage_id == 'R5':
                verification_result = verify_r5(task_log_dir=task_log_dir, dry_run=self.dry_run)
            if status == 'SUCCESS' and isinstance(verification_result, dict) and (not verification_result.get('verified', True)):
                status = 'FAILED (VERIFICATION_FAILED)'
                error_msg = str(verification_result.get('details') or verification_result.get('error') or 'Stage verification failed.')
        except Exception as ex:
            status = 'ERROR'
            error_msg = str(ex)
            self.logger.error(f'Unhandled exception during Stage {stage_id}: {ex}', exc_info=True)
        duration = time.time() - start_time
        end_iso = datetime.now().isoformat()
        result = {'stage_id': stage_id, 'stage_name': stage_meta['name'], 'target_app': stage_meta['target_app'], 'task_name': task_name, 'request': request_text, 'mode': mode, 'status': status, 'start_time': start_iso, 'end_time': end_iso, 'duration_seconds': round(duration, 3), 'error': error_msg, 'trajectories': trajectories, 'verification': verification_result, 'log_dir': str(self.output_dir / task_name)}
        self.logger.info(f'--- Stage {stage_id} Completed ({status}) in {duration:.2f}s ---')
        return result
    run_single_stage = run_stage

    async def run_suite(self, stages: Optional[List[str]]=None, request_override: Optional[str]=None, task_prefix: Optional[str]=None, mode: str='normal') -> Dict[str, Any]:
        """
        Run multiple evaluation stages sequentially and produce structured results.

        :param stages: List of stage keys or ['ALL']. If None or ['ALL'], runs R1 to R5.
        :param request_override: Optional request override (only applies if single stage specified).
        :param task_prefix: Optional prefix for task names.
        :param mode: Session mode.
        :return: Complete suite execution summary dictionary.
        """
        if not stages or 'ALL' in [s.strip().upper() for s in stages if s.strip()]:
            selected_stages = list(EVAL_STAGES.keys())
        else:
            invalid_stages = []
            selected_stages = []
            for s in stages:
                su = s.strip().upper()
                if not su:
                    continue
                if su not in EVAL_STAGES:
                    invalid_stages.append(s)
                elif su not in selected_stages:
                    selected_stages.append(su)
            if invalid_stages:
                raise ValueError(f"Invalid evaluation stage(s): {invalid_stages}. Available stages: {list(EVAL_STAGES.keys()) + ['ALL']}")
            if not selected_stages:
                raise ValueError('No valid evaluation stages specified.')
        if request_override and len(selected_stages) != 1:
            raise ValueError(f"Request override '--request' can only be specified when running a single stage (got {len(selected_stages)} stages: {selected_stages}).")
        suite_start_time = time.time()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        suite_results: List[Dict[str, Any]] = []
        self.logger.info(f"=== Starting UFO Evaluation Suite ({len(selected_stages)} Stages: {', '.join(selected_stages)}) ===")
        passed_count = 0
        failed_count = 0
        for stage_id in selected_stages:
            req = request_override if len(selected_stages) == 1 else None
            t_name = f'{task_prefix}_{stage_id}_{timestamp}' if task_prefix else None
            res = await self.run_stage(stage_id=stage_id, request_override=req, task_name_override=t_name, mode=mode)
            suite_results.append(res)
            if res['status'].startswith('SUCCESS'):
                passed_count += 1
            else:
                failed_count += 1
        suite_duration = time.time() - suite_start_time
        summary = {'title': 'UFO 5-Stage Evaluation Suite Execution Report', 'timestamp': timestamp, 'total_stages': len(selected_stages), 'passed_stages': passed_count, 'failed_stages': failed_count, 'duration_seconds': round(suite_duration, 3), 'execution_method': self.exec_method, 'dry_run': self.dry_run, 'stage_results': suite_results}
        json_report_path, md_report_path = await asyncio.to_thread(_generate_unique_report_paths, self.output_dir, timestamp)
        await _write_json_file_async(json_report_path, summary)
        await self._write_markdown_summary_async(summary, md_report_path)
        self.logger.info(f'=== Evaluation Suite Complete. Passed: {passed_count}/{len(selected_stages)} in {suite_duration:.2f}s ===')
        self.logger.info(f'Structured JSON output saved to: {json_report_path}')
        self.logger.info(f'Markdown summary report saved to: {md_report_path}')
        return summary

    async def _write_markdown_summary_async(self, summary: Dict[str, Any], filepath: Path) -> None:
        """Write human-readable Markdown summary report asynchronously using asyncio.to_thread()."""
        await asyncio.to_thread(self._write_markdown_summary, summary, filepath)

    def _write_markdown_summary(self, summary: Dict[str, Any], filepath: Path) -> None:
        """Write human-readable Markdown summary report."""
        lines = [f"# {summary['title']}", '', f"- **Timestamp**: {summary['timestamp']}", f"- **Execution Method**: `{summary['execution_method']}` (Dry Run: `{summary['dry_run']}`)", f"- **Total Duration**: {summary['duration_seconds']}s", f"- **Results**: {summary['passed_stages']} Passed / {summary['failed_stages']} Failed (Total: {summary['total_stages']})", '', '## Stage Summary Table', '', '| Stage | Name | Target App | Status | Duration (s) | Task Name |', '|---|---|---|---|---|---|']
        for r in summary['stage_results']:
            lines.append(f"| {r['stage_id']} | {r['stage_name']} | {r['target_app']} | **{r['status']}** | {r['duration_seconds']} | `{r['task_name']}` |")
        lines.extend(['', '## Detailed Trajectories & Execution Notes', ''])
        for r in summary['stage_results']:
            lines.extend([f"### Stage {r['stage_id']}: {r['stage_name']}", f"- **Request**: `{r['request']}`", f"- **Status**: `{r['status']}`", f"- **Start Time**: {r['start_time']}", f"- **End Time**: {r['end_time']}", f"- **Log Dir**: `{r['log_dir']}`"])
            if r.get('error'):
                lines.append(f"- **Error**: `{r['error']}`")
            lines.append('')
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

def parse_args(args_list: Optional[List[str]]=None) -> argparse.Namespace:
    """Parse CLI arguments for EvaluationRunner."""
    parser = argparse.ArgumentParser(description='UFO 5-Stage Evaluation Suite Test Harness & Runner')
    parser.add_argument('--stage', '-s', help='Evaluation stage(s) to run (R1, R2, R3, R4, R5, or ALL). Multiple can be comma-separated (e.g. R1,R2). Default: ALL', type=str, default='ALL')
    parser.add_argument('--request', '-r', help='Optional request description override for single stage execution.', type=str, default=None)
    parser.add_argument('--task', '-t', help='Optional custom task name or prefix.', type=str, default=None)
    parser.add_argument('--mode', '-m', help='Session mode (normal, follower, batch_normal, operator). Default: normal', type=str, default='normal')
    parser.add_argument('--exec-method', choices=['api', 'cli'], help="Execution method: 'api' (SessionFactory) or 'cli' (python -m ufo). Default: api", default='api')
    parser.add_argument('--output-dir', '-o', help='Directory to save evaluation reports and structured results.', type=str, default=None)
    parser.add_argument('--dry-run', action='store_true', help='Run harness in dry-run simulation mode for test verification.')
    parser.add_argument('--log-level', help='Log level (DEBUG, INFO, WARNING, ERROR). Default: INFO', type=str, default='INFO')
    return parser.parse_args(args_list)

async def main():
    """Main CLI entry point."""
    args = parse_args()
    runner = EvaluationRunner(output_dir=args.output_dir, exec_method=args.exec_method, dry_run=args.dry_run, log_level=args.log_level)
    stage_input = [s.strip() for s in args.stage.split(',') if s.strip()]
    try:
        await runner.run_suite(stages=stage_input, request_override=args.request, task_prefix=args.task, mode=args.mode)
    except ValueError as e:
        runner.logger.error(f'Execution failed: {e}')
        sys.exit(1)
if __name__ == '__main__':
    asyncio.run(main())