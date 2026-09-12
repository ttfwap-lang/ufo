"""
Stage R5 Handler: Multi-Agent Task.
- Executes request: Open BankFidelity to retrieve current account balance, then open Notepad and save a summary report containing the account balance.
- Verifies multi-agent delegation trajectory logs and summary report file on Desktop.
"""
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union
from tests.eval_suite.verifiers import get_desktop_dir, resolve_log_path, verify_file_on_desktop, verify_session_logs
STAGE_ID = 'R5'
STAGE_NAME = 'Multi-Agent Task'
TARGET_APP = 'Multi-App (BankFidelity + Notepad)'
DEFAULT_REQUEST = 'Open BankFidelity (located at C:\\bankfidelity\\bankfidelity\\BankFidelity_Stable.exe) to retrieve current account balance, then open Notepad and save a summary report containing the account balance.'
DEFAULT_SUMMARY_FILENAME = 'bankfidelity_summary.txt'
logger = logging.getLogger('EvalStage.R5')
import subprocess
import time
from tests.eval_suite.verifiers import verify_bankfidelity_process, verify_process_running

def pre_cleanup(summary_filename: str=DEFAULT_SUMMARY_FILENAME) -> None:
    """
    Pre-cleanup for Stage R5: Remove any existing summary report files from Desktop and pre-launch target apps.

    :param summary_filename: Target summary filename to cleanup.
    """
    desktop = get_desktop_dir()
    for filename in [summary_filename, 'account_summary.txt', 'summary_report.txt']:
        target_path = desktop / filename
        if target_path.exists():
            try:
                target_path.unlink()
                logger.info(f'[Stage R5 Pre-Cleanup] Removed existing summary file: {target_path}')
            except Exception as e:
                logger.warning(f'[Stage R5 Pre-Cleanup] Could not remove {target_path}: {e}')
    try:
        proc_ver = verify_bankfidelity_process()
        if not proc_ver['verified']:
            bf_exe = Path('C:\\bankfidelity\\bankfidelity\\BankFidelity_Stable.exe')
            if bf_exe.exists():
                logger.info(f'[Stage R5 Pre-Cleanup] Pre-launching BankFidelity: {bf_exe}')
                subprocess.Popen([str(bf_exe)])
                time.sleep(1.0)
        np_ver = verify_process_running(['notepad.exe', 'notepad'])
        if not np_ver['verified']:
            logger.info('[Stage R5 Pre-Cleanup] Pre-launching Notepad.exe')
            subprocess.Popen(['notepad.exe'])
            time.sleep(0.5)
    except Exception as e:
        logger.warning(f'[Stage R5 Pre-Cleanup] Could not pre-launch target apps: {e}')

def verify_r5(stage_data: Optional[Union[Dict[str, Any], str, Path]]=None, output_dir: Optional[Union[str, Path]]=None, task_log_dir: Optional[Union[str, Path]]=None, dry_run: bool=False, summary_filename: str=DEFAULT_SUMMARY_FILENAME, expected_keyword: str='balance') -> Dict[str, Any]:
    """
    Verify Stage R5 execution results.

    :param stage_data: Optional stage execution dict or log path.
    :param output_dir: Optional output directory path.
    :param task_log_dir: Path to UFO log directory.
    :param dry_run: If True, simulate verification pass.
    :param summary_filename: Target summary filename on Desktop.
    :param expected_keyword: Keyword expected inside saved summary report.
    :return: Structured verification result dictionary.
    """
    if isinstance(stage_data, dict):
        dry_run = dry_run or stage_data.get('dry_run', False)
    elif isinstance(task_log_dir, dict):
        dry_run = dry_run or task_log_dir.get('dry_run', False)
    if dry_run:
        return {'verified': True, 'stage_id': STAGE_ID, 'dry_run': True, 'file_exists': True, 'content_matched': True, 'trajectory_verified': True, 'details': '[DRY RUN] Stage R5 Multi-Agent Task verification simulated successfully.'}
    log_path = resolve_log_path(stage_data=stage_data, output_dir=output_dir, task_log_dir=task_log_dir)
    candidate_summary_files = list(dict.fromkeys([summary_filename, 'account_summary.txt', 'summary_report.txt']))
    file_ver = {'verified': False, 'exists': False, 'content_matched': False, 'file_path': None}
    for fname in candidate_summary_files:
        ver = verify_file_on_desktop(filename=fname, expected_content=expected_keyword)
        if ver['verified']:
            file_ver = ver
            break
        elif ver['exists'] and (not file_ver['exists']):
            file_ver = ver
    trajectory_ver = verify_session_logs(log_dir=log_path, required_patterns=['bankfidelity'])
    overall_verified = file_ver['verified'] and trajectory_ver.get('verified', False)
    return {'verified': overall_verified, 'stage_id': STAGE_ID, 'dry_run': False, 'file_exists': file_ver['exists'], 'content_matched': file_ver['content_matched'], 'file_path': file_ver['file_path'], 'actual_content': file_ver.get('actual_content'), 'trajectory_verified': trajectory_ver.get('verified', False), 'details': f"File exists: {file_ver['exists']}, Content match: {file_ver['content_matched']}, Path: {file_ver['file_path']}"}

def post_cleanup() -> None:
    """
    Post-cleanup for Stage R5: Terminate BankFidelity and Notepad to prevent leaks.
    """
    try:
        subprocess.run(['taskkill', '/F', '/IM', 'BankFidelity_Stable.exe'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['taskkill', '/F', '/IM', 'notepad.exe'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info('[Stage R5 Post-Cleanup] Terminated BankFidelity and Notepad.')
    except Exception as e:
        logger.warning(f'[Stage R5 Post-Cleanup] Could not terminate target apps: {e}')

def get_stage_config() -> Dict[str, Any]:
    """
    Get stage configuration dictionary for Stage R5.

    :return: Stage configuration dictionary containing id, name, request, pre_cleanup, and verifier.
    """
    return {'id': STAGE_ID, 'name': STAGE_NAME, 'target_app': TARGET_APP, 'request': DEFAULT_REQUEST, 'default_request': DEFAULT_REQUEST, 'description': 'Execute a task that explicitly requires the UFO HostAgent to delegate to multiple different applications sequentially.', 'pre_cleanup': pre_cleanup, 'post_cleanup': post_cleanup, 'verifier': verify_r5}