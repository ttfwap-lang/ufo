"""
Stage R2 Handler: Chrome Navigation.
- Executes Chrome navigation request: open Chrome, navigate to initial URL, then second URL.
- Verifies Chrome process execution and navigation trajectory logs.
"""
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union
from tests.eval_suite.verifiers import resolve_log_path, verify_process_running, verify_session_logs
STAGE_ID = 'R2'
STAGE_NAME = 'Chrome Navigation'
TARGET_APP = 'Google Chrome'
DEFAULT_INITIAL_URL = 'https://www.example.com'
DEFAULT_SECOND_URL = 'https://www.wikipedia.org'
DEFAULT_REQUEST = f'Open Google Chrome, navigate to {DEFAULT_INITIAL_URL}, and then navigate to {DEFAULT_SECOND_URL}.'
logger = logging.getLogger('EvalStage.R2')

def verify_r2(task_log_dir: Optional[Union[str, Path]]=None, initial_url: str=DEFAULT_INITIAL_URL, second_url: str=DEFAULT_SECOND_URL, dry_run: bool=False, stage_data: Optional[Union[Dict[str, Any], str, Path]]=None, output_dir: Optional[Union[str, Path]]=None) -> Dict[str, Any]:
    """
    Verify Stage R2 execution results.

    :param task_log_dir: Path to UFO log directory.
    :param initial_url: Initial URL string.
    :param second_url: Second URL string.
    :param dry_run: If True, simulate verification pass.
    :param stage_data: Optional stage data dictionary, string, or Path.
    :param output_dir: Optional output directory path.
    :return: Structured verification result dictionary.
    """
    if isinstance(stage_data, dict):
        dry_run = dry_run or stage_data.get('dry_run', False)
    elif isinstance(task_log_dir, dict):
        dry_run = dry_run or task_log_dir.get('dry_run', False)
    if dry_run:
        return {'verified': True, 'stage_id': STAGE_ID, 'dry_run': True, 'chrome_process_detected': True, 'trajectory_verified': True, 'details': '[DRY RUN] Stage R2 Chrome Navigation verification simulated successfully.'}
    process_ver = verify_process_running(['chrome.exe', 'Google Chrome', 'chrome'])
    log_path = resolve_log_path(stage_data=stage_data, output_dir=output_dir, task_log_dir=task_log_dir)
    required_patterns = ['chrome']
    if initial_url:
        required_patterns.append(initial_url)
    if second_url:
        required_patterns.append(second_url)
    trajectory_ver = verify_session_logs(log_dir=log_path, required_patterns=required_patterns)
    overall_verified = process_ver['verified'] and trajectory_ver.get('verified', False)
    return {'verified': overall_verified, 'stage_id': STAGE_ID, 'dry_run': False, 'chrome_process_detected': process_ver['verified'], 'initial_url': initial_url, 'second_url': second_url, 'trajectory_verified': trajectory_ver.get('verified', False), 'details': f"Chrome process detected: {process_ver['verified']}, Trajectory verified: {trajectory_ver.get('verified', False)}"}
import subprocess
import time

def pre_cleanup() -> None:
    """
    Pre-cleanup for Stage R2: Chrome Navigation.
    Ensures Google Chrome is pre-launched or pre-warmed before step 0 data collection.
    """
    try:
        proc_ver = verify_process_running(['chrome.exe', 'Google Chrome', 'chrome'])
        if not proc_ver['verified']:
            logger.info('[Stage R2 Pre-Cleanup] Pre-launching Google Chrome')
            subprocess.Popen(['cmd.exe', '/c', 'start', 'chrome.exe', '--disable-gpu', '--disable-direct-composition', 'about:blank'])
            time.sleep(0.5)
    except Exception as e:
        logger.warning(f'[Stage R2 Pre-Cleanup] Could not pre-launch Chrome: {e}')

def get_stage_config() -> Dict[str, Any]:
    """
    Get stage configuration for Stage R2.

    :return: Stage configuration dictionary.
    """
    return {'id': STAGE_ID, 'name': STAGE_NAME, 'target_app': TARGET_APP, 'request': DEFAULT_REQUEST, 'default_request': DEFAULT_REQUEST, 'description': 'Execute a request via UFO to open Google Chrome, navigate to a simple URL, and perform a multi-URL navigational sequence.', 'pre_cleanup': pre_cleanup, 'verifier': verify_r2}