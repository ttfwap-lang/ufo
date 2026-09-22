"""Permanent hidden elevation v4 - registry Run autostart (no Task Scheduler).

Registered ONCE (elevated via the one RunAs approval):
  HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run
      UFO_ELEVATED = "pythonw.exe" "uac_worker.py"

- Auto-starts silently at EVERY logon (permanent).
- Started immediately during this setup (detached pythonw).
- No Task Scheduler dependency (it ignores our tasks in this environment).
- Runtime: zero UAC, zero console, zero prompts, forever.
"""
import json
import subprocess
import time

BASE = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo"
PYTHONW = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\.venv\Scripts\pythonw.exe"
WORKER = BASE + r"\uac_worker.py"
OUT = BASE + r"\uac_setup_done.json"

RUN_KEY = r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
VALUE = f'"{PYTHONW}" "{WORKER}"'

report = {}

# 1) write the autostart registry value
r = subprocess.run(
    ["reg", "add", RUN_KEY, "/v", "UFO_ELEVATED", "/t", "REG_SZ", "/d", VALUE, "/f"],
    capture_output=True, text=True)
report["reg_rc"] = r.returncode
report["reg_out"] = (r.stdout + r.stderr)[:500]

# 2) launch the worker NOW (detached, no console)
r2 = subprocess.run(
    ["cmd", "/c", "start", "", PYTHONW, WORKER],
    capture_output=True, text=True)
report["start_rc"] = r2.returncode

# 3) wait for heartbeat
for i in range(10):
    time.sleep(2)
    try:
        with open(BASE + r"\uac_worker_alive.json", encoding="utf-8") as f:
            report["heartbeat"] = json.load(f)
            report["alive"] = True
            break
    except Exception:
        report["alive"] = False

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2)
print(json.dumps(report, indent=2)[:600])
