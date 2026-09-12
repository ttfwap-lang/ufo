"""
Stage R1 Handler: The Notepad Test.
- Executes Notepad request: open Notepad, type message, save to Desktop as ufo_test.txt.
- Verifies file creation, exact content match, and log trajectory.
"""
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union
from tests.eval_suite.verifiers import get_desktop_dir, resolve_log_path, verify_file_on_desktop, verify_session_logs
STAGE_ID = 'R1'
STAGE_NAME = 'Notepad Test'
TARGET_APP = 'Notepad'
DEFAULT_FILENAME = 'ufo_test.txt'
DEFAULT_MESSAGE = 'Hello from UFO 5-Stage Evaluation Suite!'
DEFAULT_REQUEST = f"Open Notepad, type '{DEFAULT_MESSAGE}', and save the file to the Desktop as {DEFAULT_FILENAME}."
logger = logging.getLogger('EvalStage.R1')
import subprocess
import time
from tests.eval_suite.verifiers import verify_process_running

def pre_cleanup(filename: str=DEFAULT_FILENAME) -> None:
    """
    Pre-cleanup: remove any existing test file on Desktop before test run and pre-launch Notepad.

    :param filename: Target filename to remove from Desktop.
    """
    desktop = get_desktop_dir()
    target_path = desktop / filename
    if target_path.exists():
        try:
            target_path.unlink()
            logger.info(f'[Stage R1 Pre-Cleanup] Removed existing target file: {target_path}')
        except Exception as e:
            logger.warning(f'[Stage R1 Pre-Cleanup] Could not remove {target_path}: {e}')
    home_path = Path.home() / filename
    if home_path.exists():
        try:
            home_path.unlink()
            logger.info(f'[Stage R1 Pre-Cleanup] Removed existing target file: {home_path}')
        except Exception as e:
            logger.warning(f'[Stage R1 Pre-Cleanup] Could not remove {home_path}: {e}')
    try:
        proc_ver = verify_process_running(['notepad.exe', 'notepad'])
        if not proc_ver['verified']:
            logger.info('[Stage R1 Pre-Cleanup] Pre-launching Notepad.exe')
            subprocess.Popen(['notepad.exe'])
            time.sleep(0.5)
    except Exception as e:
        logger.warning(f'[Stage R1 Pre-Cleanup] Could not pre-launch Notepad: {e}')

def verify_r1(task_log_dir: Optional[Union[str, Path]]=None, expected_message: str=DEFAULT_MESSAGE, target_filename: str=DEFAULT_FILENAME, dry_run: bool=False, stage_data: Optional[Union[Dict[str, Any], str, Path]]=None, output_dir: Optional[Union[str, Path]]=None) -> Dict[str, Any]:
    """
    Verify Stage R1 execution results.

    :param task_log_dir: Path to UFO log directory.
    :param expected_message: Predefined string expected inside saved text file.
    :param target_filename: Target filename on Desktop.
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
        return {'verified': True, 'stage_id': STAGE_ID, 'dry_run': True, 'file_exists': True, 'content_matched': True, 'trajectory_verified': True, 'details': '[DRY RUN] Stage R1 Notepad Test verification simulated successfully.'}
    desktop_ver = verify_file_on_desktop(filename=target_filename, expected_content=expected_message)
    log_path = resolve_log_path(stage_data=stage_data, output_dir=output_dir, task_log_dir=task_log_dir)
    trajectory_ver = verify_session_logs(log_dir=log_path, required_patterns=['Notepad'])
    overall_verified = desktop_ver['verified'] and trajectory_ver.get('verified', False)
    return {'verified': overall_verified, 'stage_id': STAGE_ID, 'dry_run': False, 'file_exists': desktop_ver['exists'], 'content_matched': desktop_ver['content_matched'], 'file_path': desktop_ver['file_path'], 'actual_content': desktop_ver.get('actual_content'), 'expected_content': expected_message, 'trajectory_verified': trajectory_ver.get('verified', False), 'details': f"File exists: {desktop_ver['exists']}, Content match: {desktop_ver['content_matched']}, Path: {desktop_ver['file_path']}"}

def get_stage_config() -> Dict[str, Any]:
    """
    Get stage configuration for Stage R1.

    :return: Stage configuration dictionary.
    """
    return {'id': STAGE_ID, 'name': STAGE_NAME, 'target_app': TARGET_APP, 'request': DEFAULT_REQUEST, 'default_request': DEFAULT_REQUEST, 'description': 'Execute a request via UFO to open Notepad, type a predefined message, and save the file to the Desktop.', 'pre_cleanup': pre_cleanup, 'verifier': verify_r1}