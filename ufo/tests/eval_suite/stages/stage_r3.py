"""
Stage R3 Handler: Basic BankFidelity Task.
- Executes request: Open BankFidelity desktop application and verify basic UI elements.
- Verifies BankFidelity process execution and UI verification trajectory logs.
"""
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union
from tests.eval_suite.verifiers import resolve_log_path, verify_bankfidelity_process, verify_process_running, verify_session_logs
STAGE_ID = 'R3'
STAGE_NAME = 'Basic BankFidelity Task'
TARGET_APP = 'BankFidelity'
DEFAULT_REQUEST = 'Open BankFidelity desktop application (located at C:\\bankfidelity\\bankfidelity\\BankFidelity_Stable.exe) and verify basic UI elements.'
logger = logging.getLogger('EvalStage.R3')
import subprocess
import time

def pre_cleanup() -> None:
    """
    Pre-cleanup for Stage R3: Basic BankFidelity Task.
    Ensures BankFidelity is pre-launched or pre-warmed before step 0 data collection.
    """
    logger.info('[Stage R3 Pre-Cleanup] Ready for Basic BankFidelity Task.')
    try:
        proc_ver = verify_bankfidelity_process()
        if not proc_ver['verified']:
            bf_exe = Path('C:\\bankfidelity\\bankfidelity\\BankFidelity_Stable.exe')
            if bf_exe.exists():
                logger.info(f'[Stage R3 Pre-Cleanup] Pre-launching BankFidelity: {bf_exe}')
                subprocess.Popen([str(bf_exe)])
                time.sleep(1.0)
            else:
                logger.warning(f'[Stage R3 Pre-Cleanup] BankFidelity executable not found at {bf_exe}')
    except Exception as e:
        logger.warning(f'[Stage R3 Pre-Cleanup] Could not pre-launch BankFidelity: {e}')

def verify_r3(stage_data: Optional[Union[Dict[str, Any], str, Path]]=None, output_dir: Optional[Union[str, Path]]=None, task_log_dir: Optional[Union[str, Path]]=None, dry_run: bool=False) -> Dict[str, Any]:
    """
    Verify Stage R3 execution results.

    :param stage_data: Optional stage execution dict or log path.
    :param output_dir: Optional output directory path.
    :param task_log_dir: Path to UFO log directory.
    :param dry_run: If True, simulate verification pass.
    :return: Structured verification result dictionary.
    """
    if isinstance(stage_data, dict):
        dry_run = dry_run or stage_data.get('dry_run', False)
    elif isinstance(task_log_dir, dict):
        dry_run = dry_run or task_log_dir.get('dry_run', False)
    if dry_run:
        return {'verified': True, 'stage_id': STAGE_ID, 'dry_run': True, 'process_detected': True, 'trajectory_verified': True, 'details': '[DRY RUN] Stage R3 Basic BankFidelity Task verification simulated successfully.'}
    log_path = resolve_log_path(stage_data=stage_data, output_dir=output_dir, task_log_dir=task_log_dir)
    process_ver = verify_bankfidelity_process()
    trajectory_ver = verify_session_logs(log_dir=log_path, required_patterns=['bankfidelity'])
    overall_verified = process_ver['verified'] and trajectory_ver.get('verified', False)
    return {'verified': overall_verified, 'stage_id': STAGE_ID, 'dry_run': False, 'process_detected': process_ver['verified'], 'running_processes': process_ver.get('running_processes', []), 'trajectory_verified': trajectory_ver.get('verified', False), 'details': f"BankFidelity process detected: {process_ver['verified']}, Trajectory verified: {trajectory_ver.get('verified', False)}"}

def get_stage_config() -> Dict[str, Any]:
    """
    Get stage configuration dictionary for Stage R3.

    :return: Stage configuration dictionary containing id, name, request, pre_cleanup, and verifier.
    """
    return {'id': STAGE_ID, 'name': STAGE_NAME, 'target_app': TARGET_APP, 'request': DEFAULT_REQUEST, 'default_request': DEFAULT_REQUEST, 'description': 'Execute a request via UFO to interact with the BankFidelity desktop application.', 'pre_cleanup': pre_cleanup, 'verifier': verify_r3}