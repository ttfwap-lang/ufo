"""Follow the newest UFO session's events.jsonl and print each event.

Usage: python -m ufo.telemetry_daemon [logs_dir]
"""
import glob
import json
import os
import sys
import time
from datetime import datetime

DEFAULT_LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")


def _stamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def newest_events_file(logs_dir: str):
    files = glob.glob(os.path.join(logs_dir, "**", "events.jsonl"), recursive=True)
    return max(files, key=os.path.getmtime) if files else None


def format_event(line: str) -> str:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return f"[{_stamp()}] [RAW] {line.strip()}"
    action = record.get("selected_action_name") or record.get("action") or ""
    return f"[{_stamp()}] [{record.get('agent_name', '?')}] step={record.get('step_index', '?')} {action} {record.get('action_parameters', '')}"


def follow(logs_dir: str = DEFAULT_LOGS_DIR, poll: float = 0.5) -> None:
    current, handle = None, None
    print(f"[{_stamp()}] Watching {logs_dir} for UFO sessions (Ctrl+C to stop).")
    while True:
        latest = newest_events_file(logs_dir)
        if latest and latest != current:
            if handle:
                handle.close()
            current, handle = latest, open(latest, "r", encoding="utf-8")
            print(f"[{_stamp()}] Following {latest}")
        line = handle.readline() if handle else ""
        if line:
            print(format_event(line))
        else:
            time.sleep(poll)


if __name__ == "__main__":
    follow(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LOGS_DIR)
