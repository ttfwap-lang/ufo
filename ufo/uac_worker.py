"""Permanent hidden UAC worker - runs elevated (SYSTEM) via scheduled task.

Started by scheduled task UFO_ELEVATED (pythonw.exe - NO console window, invisible).
Loops reading uac_command.json and executes the requested script elevated,
writing the result to uac_result.json. The client (uac_run.py) triggers it
with `schtasks /run` - no UAC prompt, ever, after one-time registration.
"""
import json
import os
import subprocess
import sys
import time

BASE = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo"
CMD = os.path.join(BASE, "uac_command.json")
RESULT = os.path.join(BASE, "uac_result.json")

HEARTBEAT = os.path.join(BASE, "uac_worker_alive.json")


def main() -> int:
    # Signal readiness (proves it runs elevated / hidden)
    try:
        with open(HEARTBEAT, "w") as f:
            json.dump({"alive": True, "time": time.time(), "user": "SYSTEM"}, f)
    except Exception:
        pass

    while True:
        try:
            if os.path.exists(CMD):
                with open(CMD, "r", encoding="utf-8") as f:
                    cmd = json.load(f)
                result = {"id": cmd.get("id", 0), "ok": False}
                try:
                    pr = subprocess.run(
                        [sys.executable, cmd["script"]] + list(cmd.get("args", [])),
                        capture_output=True, text=True,
                        timeout=cmd.get("timeout", 600),
                    )
                    result = {
                        "id": cmd.get("id", 0),
                        "ok": pr.returncode == 0,
                        "stdout": pr.stdout[-4000:],
                        "stderr": pr.stderr[-4000:],
                    }
                except Exception as e:  # noqa: BLE001 - report any worker error
                    result = {"id": cmd.get("id", 0), "ok": False, "error": repr(e)}
                with open(RESULT, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False)
                os.remove(CMD)
        except Exception:
            pass
        time.sleep(0.25)


if __name__ == "__main__":
    sys.exit(main())
