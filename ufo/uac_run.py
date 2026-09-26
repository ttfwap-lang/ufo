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
WORKER = os.path.join(BASE, "uac_worker.py")
CMD = os.path.join(BASE, "uac_command.json")
RESULT = os.path.join(BASE, "uac_result.json")
HEARTBEAT = os.path.join(BASE, "uac_worker_alive.json")
TASK_NAME = "UFO_ELEVATED"

# The daemon refreshes its heartbeat every ~5s. Anything older than this means
# it is gone (crashed, or killed at logoff). A heartbeat file that merely
# EXISTS proves nothing - it survives the process that wrote it, so checking
# existence made a dead daemon look alive and the client then sat out its full
# timeout on a command nobody was ever going to run.
HEARTBEAT_MAX_AGE = 20.0

_id = int(time.time() * 1000) % 100000000


def _heartbeat_age() -> float:
    """Seconds since the daemon last beat, or +inf if it never has."""
    try:
        return time.time() - os.path.getmtime(HEARTBEAT)
    except OSError:
        return float("inf")


def _daemon_alive() -> bool:
    return _heartbeat_age() < HEARTBEAT_MAX_AGE


def _wake_daemon() -> bool:
    """Best-effort start of the daemon. True if it beats within ~15s.

    The autostart is the "UFO_ELEVATED" scheduled task (SYSTEM, at logon), so
    `schtasks /run` is the correct wake-up.
    """
    try:
        subprocess.run(["schtasks", "/run", "/tn", TASK_NAME],
                       capture_output=True, text=True, timeout=60)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: could not trigger {TASK_NAME}: {exc}")

    deadline = time.time() + 15
    while time.time() < deadline:
        if _daemon_alive():
            return True
        time.sleep(0.5)
    return False


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python uac_run.py <script.py> [args...]")
        return 64
    script = sys.argv[1]
    args = sys.argv[2:]

    if not os.path.exists(WORKER):
        print(f"ERROR: daemon source missing: {WORKER}")
        return 3

    # The daemon runs as SYSTEM with its working directory at %SystemRoot%
    # (C:\Windows\System32), so a relative script path resolves against the
    # WRONG directory and fails to open. Always send an absolute path,
    # resolved against the caller's working directory.
    script = os.path.abspath(script)
    if not os.path.exists(script):
        print(f"ERROR: script not found: {script}")
        return 3

    # Ensure the daemon is alive, waking it if its heartbeat has gone stale.
    if not _daemon_alive():
        if not _wake_daemon():
            print(f"ERROR: {TASK_NAME} daemon is not responding "
                  f"(heartbeat age {_heartbeat_age():.0f}s). "
                  f"Re-register it elevated: python setup_uac.py")
            return 3

    # Drop any result left over from a previous run so a stale id can never be
    # mistaken for this command's output.
    try:
        os.remove(RESULT)
    except OSError:
        pass

    with open(CMD, "w", encoding="utf-8") as f:
        json.dump({"id": _id, "script": script, "args": args, "timeout": 600}, f)

    deadline = time.time() + 660
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
        # The daemon stopped beating mid-command: it died. Bail now instead of
        # sitting out the whole deadline.
        if _heartbeat_age() > HEARTBEAT_MAX_AGE:
            print("ERROR: daemon stopped beating while the command was in flight")
            return 3
        time.sleep(0.5)

    print("TIMEOUT waiting for elevated result")
    return 2


if __name__ == "__main__":
    sys.exit(main())
