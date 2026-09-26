"""Register the permanent hidden-elevation daemon (the one step that prompts).

This is a thin, elevated launcher for scripts/uac_install.ps1, which is the
single source of truth for the install. Keeping one installer means the task
definition, the SYSTEM principal and the heartbeat check cannot drift apart.

    python setup_uac.py            # register + start (asks for UAC once)
    python setup_uac.py -Remove    # unregister

After it is registered, elevated work is silent forever:

    python uac_run.py <script.py> [args...]

WHY THIS EXISTS AT ALL
----------------------
An earlier version registered the daemon as a `HKLM\\...\\Run` value, believing
Task Scheduler "ignores our tasks in this environment". A Run value executes as
the logged-on user at that user's NORMAL integrity, and probing the live daemon
proved it: `is_user_an_admin: false`, running unelevated. Every script routed
through uac_run.py was therefore silently unelevated while appearing to work -
and the belief itself was false, since the "UFO litellm" and "UFO gx10 tunnel"
tasks both run fine here. Only a task with an explicit SYSTEM principal
delivers real elevation.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

BASE = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo"
INSTALLER = os.path.join(BASE, "scripts", "uac_install.ps1")
TASK_NAME = "UFO_ELEVATED"
HEARTBEAT = os.path.join(BASE, "uac_worker_alive.json")
HEARTBEAT_MAX_AGE = 20.0


def heartbeat_age() -> float:
    try:
        return time.time() - os.path.getmtime(HEARTBEAT)
    except OSError:
        return float("inf")


def main() -> int:
    if not os.path.exists(INSTALLER):
        print(f"ERROR: installer missing: {INSTALLER}")
        return 1

    args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", INSTALLER]
    if "-Remove" in sys.argv:
        args.append("-Remove")

    # Re-launch elevated. This is the ONLY UAC prompt this system ever shows.
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             f"Start-Process powershell.exe -Verb RunAs -Wait "
             f"-ArgumentList '{' '.join(args)}'"],
            check=False, timeout=300,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: could not launch the elevated installer: {exc}")
        return 1

    if "-Remove" in sys.argv:
        print("Removal requested.")
        return 0

    # Verify by heartbeat FRESHNESS, not existence: the file outlives the
    # process that wrote it, so its presence proves nothing.
    deadline = time.time() + 30
    while time.time() < deadline:
        if heartbeat_age() < HEARTBEAT_MAX_AGE:
            print(json.dumps({
                "task": TASK_NAME,
                "daemon_alive": True,
                "heartbeat_age_seconds": round(heartbeat_age(), 1),
                "usage": "python uac_run.py <script.py> [args...]",
            }, indent=2))
            return 0
        time.sleep(1)

    print(f"ERROR: no fresh heartbeat within 30s "
          f"(age {heartbeat_age():.0f}s). Inspect: "
          f"schtasks /query /tn \"{TASK_NAME}\" /fo list /v")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
