"""
Microsoft UFO Benchmark Timing Harness
Measures exact E2E wall-clock execution time of UFO task runs using time.perf_counter().
Outputs structured timing report JSON and records wall-clock duration in seconds.
"""
import argparse
import json
import os
import sys
import subprocess
import time
from datetime import datetime
from pathlib import Path

def get_default_python():
    """Detect local python executable in c:/ufo/python_env if present, otherwise fallback to sys.executable."""
    local_env_python = Path('C:/ufo/python_env/python.exe')
    if local_env_python.exists():
        return str(local_env_python.resolve())
    return sys.executable

def parse_args():
    parser = argparse.ArgumentParser(description='Run UFO E2E benchmark timing harness.')
    parser.add_argument('--task-id', '-t', default='baseline_notepad_001', help='Task ID for UFO run (default: baseline_notepad_001)')
    parser.add_argument('--mode', '-m', default='normal', help='UFO mode (default: normal)')
    parser.add_argument('--request', '-r', default="open Notepad and type 'hello world'", help="User request for UFO (default: 'open Notepad and type \\'hello world\\'')")
    parser.add_argument('--log-level', default='INFO', help='Logging level for UFO (default: INFO)')
    parser.add_argument('--python-exe', default=None, help='Python executable path to run UFO module (default: auto-detected)')
    parser.add_argument('--output-json', '-o', default=None, help='File path to save JSON benchmark report')
    return parser.parse_args()

def run_benchmark(task_id, mode, request, log_level, python_exe, output_json_path):
    if not python_exe:
        python_exe = get_default_python()
    ufo_cmd = [python_exe, '-m', 'ufo', '--task', task_id, '--mode', mode, '--request', request, '--log-level', log_level]
    print('=' * 70)
    print(f'Starting UFO Benchmark Task: {task_id}')
    print(f'Request: {request}')
    print(f"Command: {' '.join(ufo_cmd)}")
    print(f'Start Time: {datetime.now().isoformat()}')
    print('=' * 70)
    start_timestamp = datetime.now().isoformat()
    start_time = time.perf_counter()
    env = dict(os.environ)
    env['PYTHONUTF8'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    try:
        proc = subprocess.run(ufo_cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd='C:/ufo', env=env)
        end_time = time.perf_counter()
        end_timestamp = datetime.now().isoformat()
        returncode = proc.returncode
        stdout = proc.stdout or ''
        stderr = proc.stderr or ''
    except Exception as e:
        end_time = time.perf_counter()
        end_timestamp = datetime.now().isoformat()
        returncode = -1
        stdout = ''
        stderr = f'Exception executing process: {str(e)}'
    wall_clock_seconds = round(end_time - start_time, 4)
    log_dir = Path(f'C:/ufo/logs/{task_id}')
    log_files = []
    if log_dir.exists() and log_dir.is_dir():
        log_files = [str(p.name) for p in log_dir.iterdir() if p.is_file()]
    step_details = []
    response_log = log_dir / 'response.log'
    if response_log.exists():
        try:
            with open(response_log, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                for line in lines:
                    if line.strip():
                        step_details.append(line.strip())
        except Exception:
            pass
    report = {'task_id': task_id, 'mode': mode, 'request': request, 'log_level': log_level, 'python_exe': python_exe, 'command': ' '.join(ufo_cmd), 'start_timestamp': start_timestamp, 'end_timestamp': end_timestamp, 'wall_clock_seconds': wall_clock_seconds, 'returncode': returncode, 'success': returncode == 0, 'log_dir': str(log_dir.resolve()) if log_dir.exists() else None, 'log_files': log_files, 'step_details': step_details, 'stdout_tail': stdout[-2000:] if len(stdout) > 2000 else stdout, 'stderr_tail': stderr[-2000:] if len(stderr) > 2000 else stderr, 'stdout_full': stdout, 'stderr_full': stderr}
    json_output = json.dumps(report, indent=2)
    print('\n' + '=' * 70)
    print(f'BENCHMARK COMPLETE: Task {task_id}')
    print(f'Wall-clock execution time: {wall_clock_seconds:.4f} seconds')
    print(f'Exit code: {returncode}')
    print(f"Log directory: {report['log_dir']}")
    print('=' * 70)
    print('\nStructured Timing Report JSON:')
    print(json_output)
    if output_json_path:
        out_path = Path(output_json_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(json_output)
        print(f'\nSaved benchmark report to {out_path}')
    return report
if __name__ == '__main__':
    args = parse_args()
    run_benchmark(task_id=args.task_id, mode=args.mode, request=args.request, log_level=args.log_level, python_exe=args.python_exe, output_json_path=args.output_json)