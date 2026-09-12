"""
UFO Crash Report Generator
============================
When UFO encounters a fatal error during task execution, this module
captures full diagnostic context and writes a structured crash report
to the logs directory for post-mortem analysis.

Usage:
    from ufo.utils.crash_report import generate_crash_report

    try:
        await run_task()
    except Exception as e:
        generate_crash_report(e, task_name="my_task", log_dir="logs/")
"""
import json
import logging
import os
import platform
import sys
import traceback
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
logger = logging.getLogger(__name__)

def _probe_service(port: int) -> str:
    """Quick health probe returning UP/DOWN."""
    try:
        req = urllib.request.Request(f'http://127.0.0.1:{port}/health', method='GET')
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return f'UP (HTTP {resp.status})'
    except Exception as e:
        return f'DOWN ({type(e).__name__})'

def _get_system_info() -> Dict[str, Any]:
    """Collect system information for the crash report."""
    info = {'timestamp': datetime.now().isoformat(), 'platform': platform.platform(), 'python_version': sys.version, 'architecture': platform.machine(), 'processor': platform.processor(), 'cwd': os.getcwd()}
    try:
        import psutil
        mem = psutil.virtual_memory()
        info['ram_total_gb'] = round(mem.total / 1024 ** 3, 1)
        info['ram_available_gb'] = round(mem.available / 1024 ** 3, 1)
        info['ram_percent_used'] = mem.percent
        info['cpu_count'] = psutil.cpu_count()
        info['cpu_percent'] = psutil.cpu_percent(interval=0.1)
    except ImportError:
        info['ram_info'] = 'psutil not available'
    return info

def _get_service_status() -> Dict[str, str]:
    """Check health of all LLM services."""
    return {'qwen_8080': _probe_service(8080), 'gemma_8081': _probe_service(8081), 'litellm_4000': _probe_service(4000)}

def _get_config_snapshot() -> Dict[str, Any]:
    """Snapshot current configuration."""
    ufo_dir = Path(__file__).resolve().parent.parent
    config_dir = ufo_dir / 'config' / 'ufo'
    snapshot = {}
    try:
        import yaml
        for config_file in ['agents.yaml', 'system.yaml']:
            path = config_dir / config_file
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict):
                    safe_data = {}
                    for k, v in data.items():
                        if isinstance(v, dict):
                            safe_v = {sk: sv for sk, sv in v.items() if 'KEY' not in sk.upper()}
                            safe_data[k] = safe_v
                        elif 'KEY' not in str(k).upper():
                            safe_data[k] = v
                    snapshot[config_file] = safe_data
    except Exception as e:
        snapshot['error'] = str(e)
    return snapshot

def generate_crash_report(exception: Exception, task_name: Optional[str]=None, log_dir: Optional[str]=None, extra_context: Optional[Dict[str, Any]]=None) -> str:
    """
    Generate a structured crash report and save it to disk.

    :param exception: The exception that caused the crash.
    :param task_name: Name of the task that was running.
    :param log_dir: Directory to save the crash report.
    :param extra_context: Additional context to include.
    :returns: Path to the saved crash report file.
    """
    report = {'crash_report_version': '1.0', 'task_name': task_name or 'unknown', 'error': {'type': type(exception).__name__, 'message': str(exception), 'traceback': traceback.format_exception(type(exception), exception, exception.__traceback__)}, 'system': _get_system_info(), 'services': _get_service_status(), 'config': _get_config_snapshot()}
    if extra_context:
        report['extra_context'] = extra_context
    if log_dir is None:
        ufo_dir = Path(__file__).resolve().parent.parent
        log_dir = str(ufo_dir / 'logs' / 'crash_reports')
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'crash_{timestamp}_{type(exception).__name__}.json'
    filepath = os.path.join(log_dir, filename)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, default=str)
        logger.info(f'Crash report saved to: {filepath}')
    except Exception as write_err:
        logger.error(f'Failed to write crash report: {write_err}')
        print(json.dumps(report, indent=2, default=str), file=sys.stderr)
        filepath = '(printed to stderr)'
    return filepath