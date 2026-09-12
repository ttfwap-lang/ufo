"""
Common verification utility functions for UFO Evaluation Suite.
"""
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
logger = logging.getLogger('EvalVerifiers')

def get_desktop_dir() -> Path:
    """
    Get absolute path to user's Desktop directory.

    :return: Path object pointing to Desktop directory.
    """
    user_profile = os.environ.get('USERPROFILE')
    if user_profile:
        onedrive_desktop = Path(user_profile) / 'OneDrive' / 'Desktop'
        if onedrive_desktop.exists():
            return onedrive_desktop
        desktop = Path(user_profile) / 'Desktop'
        if desktop.exists():
            return desktop
    return Path.home() / 'Desktop'

def verify_file_on_desktop(filename: str='ufo_test.txt', expected_content: Optional[str]=None) -> Dict[str, Any]:
    """
    Verify if a file exists on the Desktop and optionally verify its text content.

    :param filename: Filename to look for on the Desktop.
    :param expected_content: Optional expected string content.
    :return: Verification dict with 'verified', 'exists', 'content_matched', 'file_path', 'actual_content', 'error'.
    """
    desktop = get_desktop_dir()
    target_path = desktop / filename
    if not target_path.exists():
        home_path = Path.home() / filename
        if home_path.exists():
            target_path = home_path
        else:
            return {'verified': False, 'exists': False, 'content_matched': False, 'file_path': str(target_path), 'actual_content': None, 'error': f"File '{filename}' not found at '{target_path}'."}
    actual_content = ''
    read_success = False
    try:
        for encoding in ['utf-8', 'utf-8-sig', 'latin-1', 'mbcs']:
            try:
                actual_content = target_path.read_text(encoding=encoding)
                read_success = True
                break
            except UnicodeDecodeError:
                continue
    except Exception as e:
        return {'verified': False, 'exists': True, 'content_matched': False, 'file_path': str(target_path), 'actual_content': None, 'error': f"Error reading file '{target_path}': {e}"}
    if not read_success:
        return {'verified': False, 'exists': True, 'content_matched': False, 'file_path': str(target_path), 'actual_content': None, 'error': f"Failed to decode content of file '{target_path}'."}
    if actual_content.startswith('\ufeff'):
        actual_content = actual_content[1:]
    content_matched = True
    if expected_content is not None:
        normalized_actual = actual_content.replace('\r\n', '\n').lstrip('\ufeff').strip()
        normalized_expected = expected_content.replace('\r\n', '\n').lstrip('\ufeff').strip()
        content_matched = normalized_expected.lower() in normalized_actual.lower() or normalized_actual == normalized_expected
    return {'verified': content_matched, 'exists': True, 'content_matched': content_matched, 'file_path': str(target_path), 'actual_content': actual_content.lstrip('\ufeff').strip(), 'error': None if content_matched else f"Content mismatch. Expected '{expected_content}', got '{actual_content.strip()}'"}

def verify_process_running(process_name: Union[str, List[str]]) -> Dict[str, Any]:
    """
    Verify if any specified process name is currently running or active.

    :param process_name: Single process name string or list of process names (e.g. 'chrome.exe' or ['chrome.exe', 'Google Chrome']).
    :return: Verification dict with 'verified', 'running_processes', 'error'.
    """
    if isinstance(process_name, str):
        process_names = [process_name]
    else:
        process_names = list(process_name)
    running = []
    psutil_success = False
    try:
        import psutil
        try:
            for proc in psutil.process_iter(['name']):
                try:
                    pname = proc.info['name']
                    if pname and any((target.lower() in pname.lower() for target in process_names)):
                        running.append(pname)
                except Exception:
                    continue
            psutil_success = True
        except Exception as pe:
            logger.warning(f'psutil iteration error: {pe}')
    except ImportError:
        pass
    if not psutil_success:
        try:
            output = subprocess.check_output('tasklist', shell=True, text=True, errors='replace')
            for target in process_names:
                if target.lower() in output.lower():
                    running.append(target)
        except Exception as e:
            logger.warning(f'Process verification tasklist fallback error: {e}')
    verified = len(running) > 0
    return {'verified': verified, 'running_processes': list(set(running)), 'error': None if verified else f'None of processes {process_names} were detected running.'}

def resolve_log_path(stage_data: Optional[Union[Dict[str, Any], str, Path]]=None, output_dir: Optional[Union[str, Path]]=None, task_log_dir: Optional[Union[str, Path]]=None) -> Optional[Path]:
    """
    Safely resolve log directory path from stage_data, task_log_dir, or output_dir.
    Handles stage_data passed as str, Path, or dict, as well as task_log_dir passed as dict positionally.
    """
    if isinstance(task_log_dir, dict) and stage_data is None:
        stage_data = task_log_dir
        task_log_dir = None
    target = task_log_dir
    if not target and stage_data is not None:
        if isinstance(stage_data, (str, Path)):
            target = stage_data
        elif isinstance(stage_data, dict):
            target = stage_data.get('task_log_dir') or stage_data.get('log_dir') or stage_data.get('output_dir')
    if not target and output_dir is not None:
        target = output_dir
    if target is None:
        return None
    target_str = str(target).strip()
    if not target_str:
        return None
    return Path(target_str)

def verify_session_logs(log_dir: Optional[Union[str, Path]]=None, required_patterns: Optional[Union[str, List[str]]]=None, target_actions: Optional[List[str]]=None) -> Dict[str, Any]:
    """
    Parse UFO response.log or step logs to verify execution patterns and check for step errors.

    :param log_dir: Optional path to directory containing session logs.
    :param required_patterns: String or list of string patterns that must be present in the log.
    :param target_actions: Legacy parameter alias for required_patterns.
    :return: Dict with 'verified', 'total_steps', 'matched_patterns', 'errors', 'error'.
    """
    if log_dir is None:
        return {'verified': False, 'total_steps': 0, 'matched_patterns': [], 'errors': [], 'error': 'Log directory is None or not provided.'}
    patterns: List[str] = []
    if required_patterns is not None:
        patterns = [required_patterns] if isinstance(required_patterns, str) else list(required_patterns)
    elif target_actions is not None:
        patterns = list(target_actions)
    log_path = Path(log_dir)
    if not log_path.exists():
        return {'verified': False, 'total_steps': 0, 'matched_patterns': [], 'errors': [], 'error': f'Log directory does not exist: {log_path}'}
    if not log_path.is_dir():
        return {'verified': False, 'total_steps': 0, 'matched_patterns': [], 'errors': [], 'error': f'Log path is not a directory: {log_path}'}
    response_log = log_path / 'response.log'
    log_files = []
    if response_log.exists():
        log_files.append(response_log)
    else:
        sub_logs = list(log_path.glob('**/response.log'))
        if sub_logs:
            log_files.extend(sub_logs)
        else:
            seen_paths = set()
            json_logs = []
            for p in sorted(log_path.rglob('*.json'), key=lambda p: str(p)):
                if p.name.startswith('eval_results_') or p.name.startswith('eval_summary_'):
                    continue
                try:
                    resolved_p = p.resolve()
                except Exception:
                    resolved_p = p
                if resolved_p not in seen_paths:
                    seen_paths.add(resolved_p)
                    json_logs.append(p)
            if json_logs:
                log_files.extend(json_logs)
    if not log_files:
        return {'verified': False, 'total_steps': 0, 'matched_patterns': [], 'errors': [], 'error': f"No log files found in '{log_path}'."}
    matched_patterns = set()
    total_steps = 0
    errors_found = []
    for log_file in log_files:
        try:
            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
                lines = content.strip().splitlines()
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        total_steps += 1
                        status = data.get('status', '')
                        if status == 'ERROR':
                            errors_found.append(data.get('last_error') or 'Unknown step error')
                        record_str = str(data)
                    except json.JSONDecodeError:
                        record_str = line
                    for p in patterns:
                        if p.lower() in record_str.lower():
                            matched_patterns.add(p)
        except Exception as e:
            logger.warning(f"Error reading log file '{log_file}': {e}")
    patterns_satisfied = True
    if patterns:
        patterns_satisfied = all((p in matched_patterns for p in patterns))
    verified = total_steps > 0 and len(errors_found) == 0 and patterns_satisfied
    error_msg = None
    if not verified:
        reasons = []
        if total_steps == 0:
            reasons.append('No valid steps parsed from log files')
        if len(errors_found) > 0:
            reasons.append(f'Step errors detected: {errors_found}')
        if not patterns_satisfied:
            missing = [p for p in patterns if p not in matched_patterns]
            reasons.append(f'Missing required patterns: {missing}')
        error_msg = '; '.join(reasons) or 'Log verification failed.'
    return {'verified': verified, 'total_steps': total_steps, 'matched_patterns': list(matched_patterns), 'errors': errors_found, 'error': error_msg}

def verify_bankfidelity_process(process_names: Optional[List[str]]=None) -> Dict[str, Any]:
    """
    Verify if BankFidelity desktop application process is currently running or active.

    :param process_names: Optional custom list of process names to check.
    :return: Verification result dictionary.
    """
    targets = process_names or ['BankFidelity_Stable.exe', 'dual-core-pdf-pipeline.exe', 'bankfidelity.exe', 'bankfidelity', 'dual-core-pdf-pipeline']
    return verify_process_running(targets)