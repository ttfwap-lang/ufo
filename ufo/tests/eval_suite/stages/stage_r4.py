"""
Stage R4 Handler: Complex BankFidelity Task.
- Executes request: Open BankFidelity, navigate to transaction history, filter transactions for the last 30 days, and export the report.
- Verifies process execution, navigation & export trajectory logs, and exported report file.
"""
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union
from tests.eval_suite.verifiers import get_desktop_dir, resolve_log_path, verify_bankfidelity_process, verify_session_logs
STAGE_ID = 'R4'
STAGE_NAME = 'Complex BankFidelity Task'
TARGET_APP = 'BankFidelity'
DEFAULT_REQUEST = 'Open BankFidelity (located at C:\\bankfidelity\\bankfidelity\\BankFidelity_Stable.exe), navigate to transaction history, filter transactions for the last 30 days, and export the report.'
DEFAULT_REPORT_FILENAME = 'bankfidelity_report.csv'
logger = logging.getLogger('EvalStage.R4')
import subprocess
import time

def pre_cleanup(report_filename: str=DEFAULT_REPORT_FILENAME) -> None:
    """
    Pre-cleanup for Stage R4: Remove any existing exported report files from Desktop and pre-launch BankFidelity.

    :param report_filename: Target report filename to cleanup.
    """
    desktop = get_desktop_dir()
    for filename in [report_filename, 'transaction_history.csv', 'bankfidelity_export.csv']:
        target_path = desktop / filename
        if target_path.exists():
            try:
                target_path.unlink()
                logger.info(f'[Stage R4 Pre-Cleanup] Removed existing report file: {target_path}')
            except Exception as e:
                logger.warning(f'[Stage R4 Pre-Cleanup] Could not remove {target_path}: {e}')
    try:
        proc_ver = verify_bankfidelity_process()
        if not proc_ver['verified']:
            bf_exe = Path('C:\\bankfidelity\\bankfidelity\\BankFidelity_Stable.exe')
            if bf_exe.exists():
                logger.info(f'[Stage R4 Pre-Cleanup] Pre-launching BankFidelity: {bf_exe}')
                subprocess.Popen([str(bf_exe)])
                time.sleep(1.0)
    except Exception as e:
        logger.warning(f'[Stage R4 Pre-Cleanup] Could not pre-launch BankFidelity: {e}')

def verify_r4(stage_data: Optional[Union[Dict[str, Any], str, Path]]=None, output_dir: Optional[Union[str, Path]]=None, task_log_dir: Optional[Union[str, Path]]=None, dry_run: bool=False, report_filename: str=DEFAULT_REPORT_FILENAME) -> Dict[str, Any]:
    """
    Verify Stage R4 execution results.

    :param stage_data: Optional stage execution dict or log path.
    :param output_dir: Optional output directory path.
    :param task_log_dir: Path to UFO log directory.
    :param dry_run: If True, simulate verification pass.
    :param report_filename: Target exported report filename.
    :return: Structured verification result dictionary.
    """
    if isinstance(stage_data, dict):
        dry_run = dry_run or stage_data.get('dry_run', False)
    elif isinstance(task_log_dir, dict):
        dry_run = dry_run or task_log_dir.get('dry_run', False)
    if dry_run:
        return {'verified': True, 'stage_id': STAGE_ID, 'dry_run': True, 'process_detected': True, 'trajectory_verified': True, 'report_verified': True, 'details': '[DRY RUN] Stage R4 Complex BankFidelity Task verification simulated successfully.'}
    log_path = resolve_log_path(stage_data=stage_data, output_dir=output_dir, task_log_dir=task_log_dir)
    process_ver = verify_bankfidelity_process()
    trajectory_ver = verify_session_logs(log_dir=log_path, required_patterns=['bankfidelity'])
    desktop = get_desktop_dir()
    candidate_filenames = list(dict.fromkeys([report_filename, 'transaction_history.csv', 'bankfidelity_export.csv']))
    found_report_path = None
    for fname in candidate_filenames:
        target_path = desktop / fname
        if target_path.exists() and target_path.is_file() and (target_path.stat().st_size > 0):
            found_report_path = target_path
            break
    report_exists = found_report_path is not None
    overall_verified = process_ver['verified'] and trajectory_ver.get('verified', False) and report_exists
    details_msg = f"BankFidelity process detected: {process_ver['verified']}, Trajectory verified: {trajectory_ver.get('verified', False)}, Report file exists: {report_exists}"
    if found_report_path:
        details_msg += f' ({found_report_path.name})'
    elif not report_exists:
        details_msg += f' (CSV report missing or empty on Desktop: checked {candidate_filenames})'
    return {'verified': overall_verified, 'stage_id': STAGE_ID, 'dry_run': False, 'process_detected': process_ver['verified'], 'running_processes': process_ver.get('running_processes', []), 'trajectory_verified': trajectory_ver.get('verified', False), 'report_verified': report_exists, 'details': details_msg}

def get_stage_config() -> Dict[str, Any]:
    """
    Get stage configuration dictionary for Stage R4.

    :return: Stage configuration dictionary containing id, name, request, pre_cleanup, and verifier.
    """
    return {'id': STAGE_ID, 'name': STAGE_NAME, 'target_app': TARGET_APP, 'request': DEFAULT_REQUEST, 'default_request': DEFAULT_REQUEST, 'description': 'Execute a more advanced, multi-step interaction within BankFidelity.', 'pre_cleanup': pre_cleanup, 'verifier': verify_r4}