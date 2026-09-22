"""Client for the permanent hidden UAC daemon.

Usage:  python uac_run.py <script.py> [args...]

Writes uac_command.json - the SYSTEM daemon (always alive at logon) picks it
up and executes elevated; we poll uac_result.json. No UAC, no console.
"""
import json
import os
import subprocess
import sys
import time

BASE = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo"
CMD = os.path.join(BASE, "uac_command.json")
RESULT = os.path.join(BASE, "uac_result.json")
TASK_NAME = "UFO_ELEVATED"

_id = int(time.time() * 1000) % 100000000


def main() -> int:
    script = sys.argv[1]
    args = sys.argv[2:]

    # ensure daemon is alive (fallback trigger if it somehow died)
    alive = os.path.exists(os.path.join(BASE, "uac_worker_alive.json"))
    if not alive:
        subprocess.run(["schtasks", "/run", "/tn", TASK_NAME],
                       capture_output=True, text=True, timeout=60)
        time.sleep(2)

    with open(CMD, "w", encoding="utf-8") as f:
        json.dump({"id": _id, "script": script, "args": args, "timeout": 600}, f)

    deadline = time.time() + 600
    while time.time() < deadline:
        try:
            if os.path.exists(RESULT):
                with open(RESULT, "r", encoding="utf-8") as f:
                    r = json.load(f)
                if r.get("id") == _id:
                    print("STDOUT:\n", r.get("stdout", ""))
                    print("STDERR:\n", r.get("stderr", ""))
                    print("OK:", r.get("ok"))
                    return 0 if r.get("ok") else 1
        except Exception:
            pass
        time.sleep(0.5)

    print("TIMEOUT waiting for elevated result")
    return 2


if __name__ == "__main__":
    sys.exit(main())
